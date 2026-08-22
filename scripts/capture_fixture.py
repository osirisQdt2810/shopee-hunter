#!/usr/bin/env python3
"""Record a REAL Shopee response into the offline fixtures.

Fixtures in this repo are captured, never hand-written (ADR-008). A hand-written fixture pins
what we *believe* the wire format is, so the parsing tests keep passing while the real
response drifts — which is precisely the failure the offline tier is supposed to catch.

    python scripts/capture_fixture.py --keyword "tai nghe" --out tests/fixtures/shopee_web/
    python scripts/capture_fixture.py --keyword "tai nghe" --source browser --out tests/fixtures/shopee_web/

The saved JSON is the raw body, unmodified except for one thing: fields that could carry
personal data (a logged-in user's id, recommendation tokens) are stripped, because these
files are committed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shopee_hunter.core.errors import SaleHunterError  # noqa: E402
from shopee_hunter.core.logging import configure  # noqa: E402
from shopee_hunter.core.settings import AppPaths, AppSettings  # noqa: E402

# Top-level keys that are per-user or per-session, so they must not be committed.
_STRIP_KEYS = frozenset(
    {
        "userid",
        "user_id",
        "adjust",
        "reserved_keyword",
        "algorithm",
        "tracking_info",
        "session_id",
        "rcmd_reason",
    }
)


def scrub(payload: Any) -> Any:
    """Recursively drop session/personal keys from a captured body."""
    if isinstance(payload, dict):
        return {k: scrub(v) for k, v in payload.items() if k not in _STRIP_KEYS}
    if isinstance(payload, list):
        return [scrub(item) for item in payload]
    return payload


async def run(args: argparse.Namespace) -> int:
    from shopee_hunter.core.models import SearchQuery
    from shopee_hunter.sources import build_source

    bundled = REPO_ROOT / "config" / "settings.toml"
    settings = AppSettings.load(
        bundled=bundled if bundled.is_file() else None, user=AppPaths.settings_file()
    )
    for name in ("web", "browser", "affiliate"):
        block = getattr(settings.sources, name, None)
        if block is not None:
            block.enabled = name == args.source

    adapter = build_source(args.source, settings)
    args.out.mkdir(parents=True, exist_ok=True)

    # Capture the RAW body, so go through the adapter's transport rather than its parser —
    # the whole point is to keep a copy of what the parser will be tested against.
    try:
        if args.source == "web":
            payload = await adapter._get_json(
                "/api/v4/search/search_items",
                {
                    "by": "relevancy",
                    "keyword": args.keyword,
                    "limit": 60,
                    "newest": 0,
                    "order": "desc",
                    "page_type": "search",
                    "scenario": "PAGE_GLOBAL_SEARCH",
                    "version": 2,
                },
                f"https://{settings.storefront.domain}/search?keyword={args.keyword}",
            )
        elif args.source == "browser":
            payload = await adapter._get_json(
                "/api/v4/search/search_items",
                {
                    "by": "relevancy",
                    "keyword": args.keyword,
                    "limit": 60,
                    "newest": 0,
                    "order": "desc",
                    "page_type": "search",
                    "scenario": "PAGE_GLOBAL_SEARCH",
                    "version": 2,
                },
            )
        else:
            print(
                f"capturing from {args.source!r} is not supported yet", file=sys.stderr
            )
            return 2
    except SaleHunterError as exc:
        print(f"capture failed: {exc}", file=sys.stderr)
        print(
            "\nNothing was written. A blocked capture is the usual case without cookies —",
            file=sys.stderr,
        )
        print(
            "paste a cookie string into config/secrets.toml, or use --source browser.",
            file=sys.stderr,
        )
        return 2
    finally:
        await adapter.aclose()

    cleaned = scrub(payload)
    target = args.out / args.name
    target.write_text(
        json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    items = cleaned.get("items") or []
    print(f"wrote {target}  ({len(items)} item(s), {target.stat().st_size:,} bytes)")
    print("\nNow make the parsing tests track it:")
    print("  pytest tests/sources -vv")
    # Prove the capture is parseable before the operator walks away thinking it is fine.
    from shopee_hunter.sources.parse import parse_search_response

    products = parse_search_response(cleaned, source="capture")
    print(
        f"parsed {len(products)} product(s) from the capture — e.g. {products[0].name[:60]!r}"
        if products
        else "capture parsed to zero products"
    )
    _ = SearchQuery  # imported for the type-level contract this capture satisfies
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--keyword", "-k", required=True)
    parser.add_argument("--source", "-s", default="web", choices=["web", "browser"])
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "tests" / "fixtures" / "shopee_web"
    )
    parser.add_argument("--name", default="search_items.json")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    configure(logging.DEBUG if args.verbose else logging.WARNING)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
