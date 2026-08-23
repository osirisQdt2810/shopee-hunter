# Project Journal

Daily work log for **Sale Hunter**. Newest entries at the top.

Format for each entry:

```
## YYYY-MM-DD (Weekday)

### Done today
- <completed item with file references where useful>

### In progress
- <half-finished item>
- File: `path/to/file.py:line`
- Status: <what's left>

### Decisions made
- <brief decision; if formal, link to DECISIONS.md ADR number>

### Next up
- <what to pick up next session>
```

---

## 2026-08-23 (Sunday)

### Done today
- **Repo re-founded as Sale Hunter.** The tree was scaffolded from an unrelated PyQt6
  plugin-host project and every trace of it is gone: `.claude/CLAUDE.md`,
  `CONVENTIONS.md` (Part 2 rewritten; Parts 1 and 3 kept), `WORKFLOW.md`, `DECISIONS.md`,
  `FEATURE_LOG.md`, this journal, and all four subagent briefs now describe *this* app.
- **Toolchain rebuilt for a PySide6 desktop app.** `pyproject.toml` is now a real project
  definition (setuptools src-layout, `[dev]` / `[browser]` / `[package]` extras, gui-script
  entry point, package-data globs for QML) with Black/Ruff/isort/mypy/pytest configured for
  Python 3.11–3.13. Ruff gained `ASYNC`, `PTH`, `DTZ`, `C4` and two banned imports
  (`requests`, `PyQt6`). `.pre-commit-config.yaml` gained TOML/JSON/LF/private-key hygiene
  plus two local hooks: `qmlformat` (from the PySide6 wheel) and `check_layers.py`.
- **Dev venv on Python 3.13.9** with PySide6 6.9.3, httpx 0.28, pydantic 2.13.
- **Core deal engine (pure, no Qt/network):** `core/models.py` (Money with Shopee's
  ×100_000 wire scale, Product, PriceSnapshot, Deal, Watch, SearchQuery),
  `core/deals.py` (median-of-observed-history reference price, claim-inflation detection,
  0–100 score), `core/sale_calendar.py` (double-date/mega/payday/flash-slot windows in ICT,
  tier → scan cadence), `core/rate_limit.py` (token bucket + async facade),
  `core/settings.py` (four-layer settings tree, secrets excluded from `save()`),
  `core/logging.py` (secret-redacting filter), `core/errors.py` (typed source failures).
- **Repo published** as `osirisQdt2810/shopee-hunter` (renamed from `shopee-bot` at the
  user's request). `main` carries a scaffolding commit; the app itself is PR #1, so the
  pipeline gets exercised on real content rather than on an unreviewable initial import.

### In progress
- Source adapters, storage, services, and the QML shell — the layers below `core/`.
- Status: `core/` is written and smoke-tested by hand; the pytest suite, the live tier, the
  CI workflows, and the packaging specs are still to come.

### Decisions made
- ADR-001 — local desktop app, not a cloud scraper (data access, credential custody, ban
  blast radius).
- ADR-002 — QML/Qt Quick, not QWidgets: platform-identical rendering is the requirement, and
  QWidgets delegate drawing to each OS's native style.
- ADR-003 — async httpx on one worker-thread loop, one Qt bridge (`gui/tasks.py`).
- ADR-004 — one `SourceAdapter` seam, ordered fallback chain, Playwright optional.
- ADR-005 — a discount is measured against observed price history, never Shopee's claim.
- ADR-006 — the sale calendar drives scan cadence (6h quiet → 5min mega).
- ADR-007 — self-throttling is mandatory and conservative; the user's session stays theirs.
- ADR-008 — two test tiers: offline `pytest` by default, `live` opt-in and required as PR
  evidence.
- ADR-009 — persisted settings tolerate unknown keys; wire payloads are strict.
- ADR-010 — CI reviews and merges its own PRs behind four simultaneous gates.

### Next up
- **Two one-time GitHub setup steps before auto-merge can work** (they need the account
  owner): install the Claude GitHub App on the repo, and add a `CLAUDE_CODE_OAUTH_TOKEN`
  actions secret (`claude setup-token`). Both are now **done**, and the first turned out not
  to be required at all: the review job passes the action its own GITHUB_TOKEN, which skips
  the App-token exchange that the App would otherwise be needed for. Skipping it also
  retired the "workflow-editing PRs can never be reviewed" exception, which would have hit
  PR #1 itself. The `automerge` label already existed and is now applied.
- **Windows hand-verification**: the DWM acrylic path in `gui/window.py` and the PowerShell
  toast in `services/notifier.py` have documented fallbacks but no real-hardware run.
- **Capture a wire fixture** once a signed-in browser profile exists; the three skipped
  parse tests unskip themselves.
- **mypy**: 83 findings under `strict`, mostly PySide6 stub gaps and unannotated `gui/`
  helpers. Not a gate, but it independently caught the cross-thread bug, so it is worth
  burning down.
