#!/usr/bin/env python3
"""Run a REAL scan against Shopee and report what happened.

This is the other half of the live tier (ADR-008), and the fastest honest answer to "does the
tool still work?". The offline suite replaces exactly the parts that break — Shopee's wire
format and its anti-bot behaviour — so a green `pytest` proves the logic, not the tool.

    python scripts/live_check.py --keyword "tai nghe bluetooth" --max-price 500000
    python scripts/live_check.py --keyword "ban phim co" --source browser -v
    python scripts/live_check.py --print-settings          # what actually loaded, and from where

Exit codes are the result, so this can be a CI/pre-push gate:
    0  deals returned (or a clean empty result) — the pipeline works end to end
    2  the site refused us (SourceBlocked / SourceAuthRequired). NOT a bug: the adapter
       raised the typed error instead of pretending there were no deals.
    1  a real failure — a ParseError (the wire format moved), or an unexpected exception.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shopee_hunter.core.errors import (  # noqa: E402
    ParseError,
    SaleHunterError,
    SourceAuthRequired,
    SourceBlocked,
)
from shopee_hunter.core.logging import configure  # noqa: E402
from shopee_hunter.core.models import Deal  # noqa: E402
from shopee_hunter.core.settings import AppPaths, AppSettings  # noqa: E402

EXIT_OK = 0
EXIT_BUG = 1
EXIT_BLOCKED = 2


def build_settings(args: argparse.Namespace) -> AppSettings:
    """Load the real settings tree, then apply this run's overrides."""
    bundled = REPO_ROOT / "config" / "settings.toml"
    settings = AppSettings.load(
        bundled=bundled if bundled.is_file() else None,
        user=AppPaths.settings_file(),
    )
    if args.source:
        settings.sources.order = [args.source]
        # An explicitly-named source must actually be tried, so enable it for this run —
        # otherwise `--source browser` silently reports "not configured" and the operator
        # learns nothing about the adapter they asked about.
        for name in ("web", "browser", "affiliate"):
            block = getattr(settings.sources, name, None)
            if block is not None:
                block.enabled = name == args.source
    if args.demo:
        settings.demo_mode = True
    settings.scan.min_discount_pct = args.min_discount
    settings.scan.genuine_only = not args.include_unverified
    settings.scan.items_per_watch = args.limit
    return settings


def render_deal(index: int, deal: Deal) -> str:
    product = deal.product
    flags = ",".join(sorted(f.value for f in deal.flags)) or "-"
    return (
        f"{index:>2}. {product.name[:52]:<54}"
        f"{product.price.amount:>12,}"
        f"  ref {deal.reference_price.amount:>12,}"
        f"  −{deal.true_discount_pct:>5.1f}%"
        f"  score {deal.score:>5.1f}"
        f"  {deal.confidence.value:<6}"
        f"  {'genuine' if deal.is_genuine else 'SUSPECT'}"
        f"  {flags}"
    )


async def run(args: argparse.Namespace) -> int:
    from shopee_hunter.services.scanner import Scanner
    from shopee_hunter.sources import build_chain
    from shopee_hunter.storage.repository import Repository

    settings = build_settings(args)

    if args.print_settings:
        print("settings actually in force:")
        print(
            json.dumps(
                settings.model_dump(mode="json", exclude=_SECRET_PATHS),
                indent=2,
                ensure_ascii=False,
            )
        )
        print(f"\nconfig dir: {AppPaths.config_dir}")
        print(f"database:   {AppPaths.database_file()}")
        return EXIT_OK

    # A scratch database by default: a live check must not pollute the real price history
    # with a one-off keyword, and must not depend on what is already in there.
    with tempfile.TemporaryDirectory(prefix="sale-hunter-live-") as scratch:
        db_path = (
            AppPaths.database_file()
            if args.use_real_db
            else Path(scratch) / "live.sqlite3"
        )
        repository = Repository(db_path)
        chain = build_chain(settings, only=[args.source] if args.source else None)
        scanner = Scanner(settings, chain, repository)

        print(f"storefront : https://{settings.storefront.domain}")
        print(f"sources    : {' -> '.join(a.id for a in chain.adapters)}")
        print(f"keyword    : {args.keyword!r}")
        print(
            f"filters    : max_price={args.max_price or '-'}  min_real_discount={args.min_discount}%  "
            f"genuine_only={settings.scan.genuine_only}"
        )
        print(f"database   : {db_path}")
        print("-" * 118)

        try:
            result = await scanner.scan_keyword(
                args.keyword,
                max_price=args.max_price or None,
                min_discount_pct=args.min_discount,
                limit=args.limit,
            )
        except (SourceBlocked, SourceAuthRequired) as exc:
            print(f"BLOCKED: {exc}")
            print(
                "\nThis is a PASS for the adapter: it raised the typed error instead of"
            )
            print(
                "reporting 'no deals'. Options: wait a few minutes, paste fresh cookies into"
            )
            print(
                "config/secrets.toml, or use --source browser with a logged-in profile."
            )
            return EXIT_BLOCKED
        except ParseError as exc:
            print(f"PARSE FAILURE: {exc}")
            print(
                "\nShopee's wire format has probably changed. Re-capture the fixture and fix"
            )
            print(
                "sources/parse.py:  python scripts/capture_fixture.py --keyword "
                f"{args.keyword!r} --out tests/fixtures/shopee_web/"
            )
            return EXIT_BUG
        except SaleHunterError as exc:
            print(f"FAILURE: {exc}")
            return EXIT_BUG
        finally:
            await chain.aclose()
            await repository.close()

        if result.broken:
            print("FAILURE (needs a code fix, not patience):")
            for failure in result.failures:
                print(f"  - {failure}")
            for refusal in result.refusals:
                print(f"  - (also refused) {refusal}")
            return EXIT_BUG

        if result.blocked:
            print("REFUSED: every configured source turned us away")
            for refusal in result.refusals:
                print(f"  - {refusal}")
            print(
                "\nThe adapters behaved correctly — they raised the typed error instead of"
            )
            print(
                "reporting 'no deals'. Next step depends on the message above: wait and retry"
            )
            print(
                "for a rate limit, or sign in once (--source browser with headless = false)"
            )
            print("for a risk-control refusal.")
            return EXIT_BLOCKED

        for error in result.errors:
            print(f"  warning: {error}")

        for index, deal in enumerate(result.deals, start=1):
            print(render_deal(index, deal))

        print("-" * 118)
        print(f"{result.summary()}  |  snapshots written: {result.snapshots_written}")
        if not result.deals:
            print(
                "\nNo deals passed the filters. That is a valid result — the scan worked, and"
            )
            print(
                f"{result.products_seen} listing(s) were recorded into price history for next time."
            )
            print(
                "Try --min-discount 0 --include-unverified to see everything the source returned."
            )
        if args.json:
            print(
                "\n"
                + json.dumps(
                    {
                        "source": result.source_used,
                        "products_seen": result.products_seen,
                        "deals": [
                            {
                                "name": d.product.name,
                                "url": d.product.url,
                                "price": d.product.price.amount,
                                "reference": d.reference_price.amount,
                                "true_discount_pct": d.true_discount_pct,
                                "claimed_discount_pct": d.product.claimed_discount_pct,
                                "score": d.score,
                                "confidence": d.confidence.value,
                                "genuine": d.is_genuine,
                                "flags": sorted(f.value for f in d.flags),
                            }
                            for d in result.deals
                        ],
                        "errors": result.errors,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        return EXIT_OK


_SECRET_PATHS = {"sources": {"web": {"cookie_string"}, "affiliate": {"app_secret"}}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--keyword", "-k", default="tai nghe bluetooth")
    parser.add_argument(
        "--source",
        "-s",
        default=None,
        help="pin one adapter: web | browser | affiliate | fixture",
    )
    parser.add_argument(
        "--max-price", type=int, default=0, help="in whole currency units; 0 = no limit"
    )
    parser.add_argument(
        "--min-discount", type=float, default=10.0, help="minimum OBSERVED discount %%"
    )
    parser.add_argument("--limit", type=int, default=60, help="max listings to fetch")
    parser.add_argument(
        "--include-unverified",
        action="store_true",
        help="keep deals the engine cannot vouch for",
    )
    parser.add_argument(
        "--use-real-db",
        action="store_true",
        help="write into the app's real price history",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="offline demo catalogue (a self-test of this script)",
    )
    parser.add_argument(
        "--json", action="store_true", help="also print machine-readable output"
    )
    parser.add_argument(
        "--print-settings",
        action="store_true",
        help="show the loaded settings and exit",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    configure(logging.DEBUG if args.verbose else logging.WARNING)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\ninterrupted")
        return EXIT_BUG


if __name__ == "__main__":
    raise SystemExit(main())
