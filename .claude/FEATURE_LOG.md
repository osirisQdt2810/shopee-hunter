# Feature Log

Per-feature record of **large** changes to Sale Hunter, so anyone can see what was done and
why without re-reading the whole diff. Newest entries at the top.

One entry per large feature/change (a new source adapter, a new view, a change to a shared
seam: the adapter contract, the deal engine, the async bridge, the Theme singleton). Skip
tiny edits, typo fixes, and pure docs — those belong in `JOURNAL.md` (daily) or nowhere.

Format for each entry:

```
## YYYY-MM-DD — <Feature / change title>

**What:** <1–3 sentences: what now exists or changed>
**Why:** <the goal / problem it solves>
**Files:** <key files added/modified — paths>
**How to verify:** <exact command(s) or steps — including the LIVE check, not just pytest>
**Notes / rollback:** <gotchas, follow-ups, how to undo if needed>
```

---

## 2026-08-23 — Shopee refuses anonymous search: measured, and encoded in the adapters

**What:** The browser adapter no longer imitates Shopee's API request — it navigates to the
page a shopper would open and reads the response Shopee's **own** JavaScript receives.
`error: 90309999` and a redirect to `/verify/traffic/*` are now classified as
`SourceAuthRequired` (log in) rather than `SourceBlocked` (wait), and `ScanResult` separates
`refusals` from `failures` so a `ParseError` can no longer be reported as "blocked".

**Why:** measured, not assumed. From a residential IP with no Shopee session:

| attempt | result |
|---|---|
| plain HTTPS to `/api/v4/search/search_items` | `HTTP 403` |
| headless Chromium, `fetch()` from inside the real page | `HTTP 403` |
| headful real Chrome, `fetch()` from inside the real page | `HTTP 403` |
| headful Chrome, navigate to `/search?keyword=…`, read the page's OWN response | redirected to `/verify/traffic/error?…&is_logged_in=false&type=4`; `search_items` answered `error: 90309999`; **0** product cards rendered |

Headless and headful failing *identically* is the tell: the block is not browser
fingerprinting, it is a per-request signature Shopee's front end computes in JavaScript. A
`fetch` from the console does not carry it, so the request looks like a bot *inside* a real
browser. Reading the page's own response sidesteps the problem entirely — we are no longer
the one signing.

**Conclusion that follows:** `shopee.vn` requires a **signed-in session** to search. Waiting
does not help, so calling it a "block" would have sent users retrying forever. The working
setup is one sign-in into the persistent browser profile.

**Files:** `src/shopee_hunter/sources/shopee_browser.py` (`_capture`,
`_assert_not_interstitial`, `INTERSTITIAL_MARKERS`), `src/shopee_hunter/sources/parse.py`
(`ERROR_AUTH_CODES`), `src/shopee_hunter/services/scanner.py` (`refusals` / `failures` /
`broken`), `scripts/live_check.py`, `README.md`, `tests/live/test_sources_live.py`.

**How to verify:**
```bash
python scripts/live_check.py --keyword "tai nghe bluetooth" --source web      # expect exit 2, HTTP 403
SALEHUNTER_SOURCES__BROWSER__ENABLED=true \
  python scripts/live_check.py --keyword "tai nghe bluetooth" --source browser # expect exit 2, error 90309999
pytest -m live -vv                                                            # the refusal must be TYPED
```
A refusal is a **pass**; a `ParseError` is a failure.

**Notes / rollback:** the interstitial paths and the error codes are constants at the top of
their modules because they will drift — when a live run starts reporting a bare `ParseError`
with an unrecognised code, add it to the right frozenset rather than widening an `except`.
Two live-only bugs were fixed alongside this: `RedactingFilter` coerced every log argument
with `str()` (so the line reporting a block raised its own TypeError), and the scheduler
called a bridge slot from the asyncio thread (`Cannot create children for a parent that is
in a different thread`) — now routed through a queued signal, `AppBridge.request_scan`.

## 2026-08-23 — Project foundation: repo re-founded, toolchain rebuilt, deal engine written

**What:** The repository stopped being a copy of an unrelated PyQt6 plugin-host project and
became **Sale Hunter** — a Windows + macOS desktop app that hunts real Shopee discounts. Three
things landed together: every `.claude/*` brief rewritten for this app, a working PySide6
toolchain (`pyproject.toml`, `.pre-commit-config.yaml`, a Python 3.13 venv), and the pure
deal engine under `src/shopee_hunter/core/`.

**Why:** The inherited scaffold described a runtime that does not exist here (a plugin host,
vendored dependencies, a plugin-bundle build), so every instruction an agent read was wrong
in a way that would produce wrong code. And the app's central claim — "find items that are
*actually* discounted" — needed a definition before any UI could display it: Shopee's own
`raw_discount` is seller-controlled marketing, so a tool that repeats it recommends the fakest
listings first (ADR-005).

**Files:**
- Briefs: `.claude/CLAUDE.md`, `.claude/CONVENTIONS.md` (Part 2 rewritten, Parts 1/3 kept),
  `.claude/WORKFLOW.md`, `.claude/DECISIONS.md` (ADR-001…010), `.claude/JOURNAL.md`,
  `.claude/agents/{planner,coder,reviewer,debugger}.md`
- Toolchain: `pyproject.toml`, `.pre-commit-config.yaml`, `scripts/hooks/check_layers.py`,
  `scripts/hooks/run_qmlformat.py`
- Engine: `src/shopee_hunter/core/{models,deals,sale_calendar,rate_limit,settings,logging,errors}.py`

**How to verify:**
```bash
pytest                                              # offline suite
pre-commit run --all-files                          # incl. the layer boundary check
python scripts/live_check.py --keyword "tai nghe"    # LIVE end-to-end scan
```

**Notes / rollback:** The four architectural commitments worth knowing before touching any of
this: the layers import one way only (`core/` is pure — no PySide6, no httpx, no sqlite, and
`tests/test_architecture.py` enforces it); all Shopee access goes through the
`SourceAdapter` seam; a discount is only real if observed history says so; and the token
bucket in `core/rate_limit.py` is not optional. Rollback is per-file — nothing here has a
migration or persisted state yet.
