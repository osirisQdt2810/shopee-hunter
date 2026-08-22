# docs/

- `screenshots/` — two views captured from the running app on demo data, used by the root
  README. Regenerate them (all four views, full resolution) with:

  ```bash
  python scripts/ui_screenshot.py --out .artifacts/ui
  ```

  `.artifacts/` is gitignored on purpose; only the two downscaled shots here are committed, so
  a UI change does not add a megabyte to every commit. Update them when the UI changes
  visibly — a README screenshot that no longer matches the app is worse than none.

Architecture decisions, conventions and the working log live in [`../.claude/`](../.claude/):

| File | What it holds |
|---|---|
| `CLAUDE.md` | Architecture, the layer rule, the four seams, the commands |
| `CONVENTIONS.md` | Coding standards — universal Python, then this project's rules |
| `DECISIONS.md` | ADRs. Start with 002 (QML not QWidgets), 004 (source adapters), 005 (what counts as a discount) |
| `WORKFLOW.md` | Setup, the build/verify loop, and the live-testing procedure |
| `JOURNAL.md` | Daily work log, newest first |
| `FEATURE_LOG.md` | One entry per large feature |
