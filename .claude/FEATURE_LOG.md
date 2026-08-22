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
