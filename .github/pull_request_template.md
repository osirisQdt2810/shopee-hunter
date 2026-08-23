## Context
<!-- Why is this change needed? What problem does it solve? -->
<!-- Link related issues or incidents -->
- Related issue:
- Background / motivation:
- Constraints / assumptions:

---

## Content / Changes
<!-- What exactly changed in this PR -->
-
-
-

<!-- Optional: call out non-obvious changes -->
- Refactors:
- New features:
- Removed / deprecated behavior:

---

## Test Plan
<!-- How was this change validated -->

### Test Details
<!-- Commands, configs, or steps used to test -->
-

### Test Output / Feature Demonstration
<!-- Paste test output, logs, screenshots, benchmarks, or example requests/responses -->
-

---

## Sale Hunter checklist
<!-- Delete a line only when it genuinely cannot apply. "N/A — why" is a valid answer. -->

- **Live evidence**: for any change under `sources/`, `services/` or `gui/`, paste real output
  from `python scripts/live_check.py …` and/or a `scripts/ui_screenshot.py` PNG. A green
  offline suite is not evidence that the tool works (ADR-008).
  <!-- exit 0 = deals found, 2 = SourceBlocked (an acceptable pass), 1 = a bug -->
- **Platforms**: the app ships on **Windows + macOS**. CI covers both plus Linux; say so, or
  name what you ran by hand and where. Any new dep must have wheels for macOS arm64/x86_64
  and Windows.
- **Python**: runtime code must import on 3.11–3.13. Anything touching imports, typing, or
  dataclass behaviour needs the older end checked, not just the newest.
- **Layers (ADR-001..005)**: did anything cross a boundary?
  - `core/` still imports no PySide6 / httpx / sqlite3 / playwright:
  - `gui/` (Python **and** QML) still holds no business rule:
  - `core/deals.py` is still the only place a `Deal` is created:
- **Source adapters (ADR-004)**: new/changed transport? Confirm it goes through
  `SourceAdapter`, parses via `sources/parse.py`, and its fixture was **captured**, not
  hand-written.
- **Failure paths (ADR-007)**: blocked → `SourceBlocked`, changed field → `ParseError`,
  missing creds → `SourceAuthRequired`. Nothing returns `[]` to mean "blocked".
- **Rate limiting**: every new request path passes the token bucket; retries stay few and
  slow; no unbounded pagination or keyword fan-out.
- **Threading (ADR-003)**: no blocking call on the GUI thread; no `QThread` subclass; no
  `asyncio.run` in a slot; a long scan is still cancellable.
- **UI (ADR-002)**: QML uses only `Theme.*` tokens. New QML/resource files added to **both**
  specs in `packaging/`:
- **Settings (ADR-009)**: new/renamed/removed keys, and what an OLDER build does when it
  reads this file. Secrets stay out of `AppSettings.save()`.
- **Secrets**: no cookie, token, or API key in the diff — including tests and fixtures.
- **User-visible change / migration**: what an existing user notices after upgrading, and
  what (if anything) they must do.
- **Docs**: `.claude/FEATURE_LOG.md` for a large feature / new adapter / seam change;
  `.claude/DECISIONS.md` (ADR) when an architectural pattern changes.
