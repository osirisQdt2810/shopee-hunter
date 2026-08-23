---
description: Run the live tier — a real Shopee scan plus a real window — and report the evidence
argument-hint: optional keyword (defaults to a cheap generic one)
---

Run the **live** test tier for Sale Hunter and report what actually happened. The offline
`pytest` suite is not evidence that this tool works (see ADR-008) — this command produces the
evidence that goes in a PR.

Keyword: `$ARGUMENTS` (if empty, use `tai nghe bluetooth`).

Steps:

1. Confirm the venv and settings are sane:
   ```bash
   .venv/bin/python -c "import shopee_hunter, PySide6; print('import ok')"
   ```

2. **End-to-end scan against the real site.** Run each configured source explicitly so a
   fallback chain cannot hide a broken primary adapter:
   ```bash
   .venv/bin/python scripts/live_check.py --keyword "<keyword>" -v
   .venv/bin/python scripts/live_check.py --keyword "<keyword>" --source web -v
   ```
   Interpret the exit code, don't just report it:
   - `0` — deals returned. Quote the top 3 rows (name, price, observed discount, score).
   - `2` — `SourceBlocked`. This is a **pass for the adapter** (it raised the typed error
     instead of pretending). Say which source was blocked and what the fallback did.
   - `1` — a real bug. Capture the traceback and hand it to the `debugger` agent.

3. **The real window.** Screenshot every view and actually look at the images:
   ```bash
   .venv/bin/python scripts/ui_screenshot.py --out .artifacts/ui
   ```
   Read the PNGs back and check: no missing/blank panels, no unstyled default-grey areas, no
   clipped text, gradients and glass panels rendering. Report any QML warning verbatim — a
   QML warning is a defect even when the window looks fine.

4. **Live pytest tier** (optional but preferred before a release):
   ```bash
   .venv/bin/python -m pytest -m live -vv
   ```

5. If the wire format moved (a `ParseError`, or fields quietly missing), re-capture the
   fixture and re-run the offline parsing tests so they track reality:
   ```bash
   .venv/bin/python scripts/capture_fixture.py --keyword "<keyword>" --out tests/fixtures/shopee_web/
   .venv/bin/python -m pytest tests/sources -vv
   ```

Report in this shape, with **real output**, not claims:

```
## Live check — <date>
### Scan
- command: …
- exit: 0 | 2 | 1  → <interpretation>
- top results: <3 rows, or the block reason>
### UI
- screenshots: <paths>  | QML warnings: <verbatim, or "none">
- visual issues: <list, or "none">
### Verdict
<Does the tool work right now? If a source is blocked, is the app degrading correctly?>
### Follow-ups
<fixtures to re-capture, bugs to file, or "none">
```
