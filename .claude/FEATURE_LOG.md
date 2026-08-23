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

## 2026-08-23 — No silent defaults in the shared parser; the ADR-002 guard can finally see

**What:** Round-3 review findings, plus an independent adversarial pass over round 2's own
fixes. The shared `sources/parse.py` — used by *both* the web and browser adapters — no
longer coerces an unreadable `raw_discount`, `rating_star`, `rating_count` or
`historical_sold` into a neutral default. `SourceChain` now falls back on `ParseError`. The
Theme guard sees `Qt.rgba(...)` and ternary branches, and its pre-commit half actually runs
on QML-only commits. Six hand-mixed colours and sizes became tokens.

**Why:** round 2 fixed the swallow-and-default shape in the *secondary* adapter and left it
in the primary path. `int(basic.get("raw_discount") or 0)` turning `"52%"` into `0` means
`claimed - true_pct` can never exceed the inflation tolerance, so `CLAIM_INFLATED` never
fires, `is_genuine` stops filtering, the score penalty stops applying — and every
permanently-"−50%" listing, the exact thing ADR-005 exists to suppress, ranks as verified
while the card prints "Shopee claims −0%" in calm grey. The fake listing ends up looking
*more* trustworthy than an honest one.

Three of the fixes were defects in round 2's fixes, found by an adversarial pass rather than
by the reviewer:

- **`ParseError` did not actually restore the fallback round 2 claimed it did.**
  `_first_answer` caught only the three availability errors, so the ordered chain was useless
  in the one case it exists for. The comment asserting otherwise was wrong and is gone.
- **One bad node aborted the whole affiliate page**, contradicting the per-item tolerance
  `parse_search_response` documents ("one malformed listing among sixty should not cost the
  user the other fifty-nine"). Raising had replaced a silent wrong answer with a loud total
  failure.
- **`items_per_watch`'s hard bound could brick startup.** `AppSettings.load` turns any
  validation error into a fatal `ConfigError`, so a file written by a build that allowed 600
  would stop a newer build from opening — precisely what ADR-009 exists to prevent. Now
  clamped with a warning.

Also: `_ensure_page`'s opening navigation was the one request path not paying a token;
`app_secret=…` was never redacted (`\bsecret\b` cannot match inside `app_secret`, since `_`
is a word character); `genuine` — the engine's headline verdict — was computed, exposed,
assigned to `DealCard` and then read by nothing, so a rejected listing rendered identically
to a verified one, and the "verified deals" tile counted rows rather than genuine deals.

**Files:** `sources/parse.py` (`_number`, `_rating`), `sources/affiliate_api.py`,
`sources/base.py`, `sources/shopee_browser.py`, `core/settings.py`, `core/logging.py`,
`gui/models.py`, `gui/bridge.py` (`tone_for_tier`, `genuineCount`), `gui/qml/Theme/Theme.qml`
(`panelShadow`, `ringTrack`, `auroraScrim`, `fontXxs`), six QML components,
`tests/test_architecture.py`, `scripts/hooks/check_layers.py`, `.pre-commit-config.yaml`,
`.github/workflows/pr-pipeline.yml`, and seven test modules (+81 tests, 350 → 432).

**How to verify:**
```bash
bash scripts/run_tests.sh -q            # 432 passed
pre-commit run --all-files
python scripts/ui_screenshot.py --out .artifacts/ui   # exit 0 = zero QML warnings
```

**Notes / rollback:** the Theme guard's docstring now states exactly what it does *not*
catch — a literal inside an otherwise-derived expression, which is how
`Math.max(600, Theme.durSlow * 2)` defeated `reducedMotion`. Two earlier versions of that
docstring overclaimed, which is worse than no guard because it is trusted. The verdict
fallback in `pr-pipeline.yml` is now restricted by time as well as author, since any workflow
in the repo can post as `github-actions[bot]`.

---

## 2026-08-23 — The rate limiter charges per request, and the UI stops making judgements

**What:** Six defects from the PR #1 review, five of them behavioural. The token bucket is
now charged in the per-request helpers (`_throttle`) instead of once per `_guarded`
operation; the affiliate adapter raises `ParseError` naming the field instead of coercing an
unreadable `priceDiscountRate`/`ratingStar` to a default; QML no longer decides what an
inflated claim is or which sale tiers are loud; and the ADR-002 guard now covers all four
value kinds it always claimed to.

**Why:** each one failed *silently*, which is what made them worth fixing together.

- **Rate limiting (ADR-007).** `_guarded` took one token per operation, but a search is not
  one request — the web and browser adapters loop over `query.page_count`, and the affiliate
  adapter pages until it has `query.limit` items. Raising `items_per_watch` to 600 bought ten
  back-to-back requests with a single token: ~10 req/s against a bucket set to 0.5 with a
  burst of 4. At the default of 60 the loop runs once, so nothing showed. The seam's own
  claim — "rate limiting is enforced here so no adapter can bypass it" — was false for every
  multi-page search.
- **Typed failures (ADR-004).** `except (TypeError, ValueError): rate = 0` turned a wire
  format change into `claimed_discount_pct=0` on every item, which disables `CLAIM_INFLATED`
  (no claim left to compare) and then filters the whole page out against
  `min_discount_pct` — "no deals" during a live sale, with nothing naming the field. The
  `ratingStar` coercion sat outside the try entirely, so a bare `ValueError` escaped
  `SourceChain` (which only catches `SourceError`) and skipped the fallback to the next
  adapter.
- **Business rules in QML (ADR-002/005).** `DealCard.qml` re-implemented
  `CLAIM_INFLATION_TOLERANCE_PCT` as a literal `15`; retuning the constant in `core/deals.py`
  would drop a listing from `is_genuine` while the card still painted its claim calm grey.
  `CalendarView.qml` and `AppWindow.qml` asked `tierLevel >= 3`, hardcoding which `SaleTier`
  members are campaigns — inserting a tier renders 12.12 as a neutral badge.
- **The guard itself.** `test_architecture.py` and `check_layers.py` matched hex colours
  only, while the rubric and the PR checklist said colour/radius/duration/font size. Twelve
  literals had slipped through, including a `radius: 13` one pixel off `Theme.radiusMd` and a
  `duration: 1200` that cannot honour `reducedMotion`.

**Files:** `sources/base.py` (`_throttle`), `sources/shopee_web.py`,
`sources/shopee_browser.py`, `sources/affiliate_api.py`, `core/sale_calendar.py`
(`PEAK_TIERS`, `is_peak`, `is_elevated`), `core/settings.py` (`items_per_watch` bound),
`gui/models.py` (`ClaimInflatedRole`), `gui/bridge.py` (`tierIsPeak`, `tierTone`), twelve
`gui/qml/**` files, `gui/qml/Theme/Theme.qml` (`durSweep`, `fontGlyph`),
`tests/test_architecture.py`, `scripts/hooks/check_layers.py`, and five test modules
(+53 tests).

**How to verify:**
```bash
bash scripts/run_tests.sh -q            # 350 passed
pre-commit run --all-files              # includes the widened layer/Theme guard
python scripts/ui_screenshot.py --out .artifacts/ui   # exit 0 = zero QML warnings
python scripts/live_check.py --keyword "tai nghe bluetooth" --source web --min-discount 5
```
The rate-limit fix has a real regression test: `test_every_page_of_a_search_pays_the_rate_limiter`
drives the actual `_get_json` path through respx and fails (`0 == 3`) if `_throttle` is removed.

**Notes / rollback:** `tierLevel` still exists and is still correct for `Theme.tierGlow`,
which ramps an intensity rather than branching; `test_qml_never_branches_on_the_sale_tier_ordinal`
is what keeps the distinction. `Theme.radiusPill` is used for every dot and pill — Qt clamps
`radius` to half the smaller side, so one token expresses all of them.

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
