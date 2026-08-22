# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Sale Hunter** (`shopee_hunter`) is a **cross-platform desktop app** that hunts discounted
items on Shopee during sale days. You define *watches* (keyword, price ceiling, minimum
discount, shop, rating floor); the app scans on a schedule — and hard around the sale
windows (`1.1`, `2.2`, … `12.12`, payday `15`/`25`, Shopee Live flash sales) — keeps a local
price history, and surfaces the items whose current price is a genuine drop rather than a
marked-up "discount".

Two halves, deliberately separated:

- a **deal engine** that is pure Python (no Qt, no network) — price normalisation, discount
  scoring against *observed* history, watch matching, sale-calendar logic;
- a **QML/Qt Quick shell** that is deliberately good-looking — frameless translucent
  window, real blur, gradients, spring animations — and pixel-identical on Windows and
  macOS because Qt Quick draws every pixel itself.

## Stack & runtime reality (read this before anything else)

- **Language:** Python **3.13** (dev venv is `.venv`, created from `python3.13`). Keep code
  3.11+-compatible so a user's older interpreter still runs it from source.
- **GUI:** **PySide6** (Qt 6.9) + **QML / Qt Quick**. Not QWidgets — see ADR-002. QML gives
  GPU-accelerated animation, real gradients, shader effects, and the same rendering on both
  OSes; widgets would look native-but-different and cannot do the requested visuals.
- **This is NOT a server.** No Flask, no Celery, no Redis, no Docker runtime. It is a
  double-clickable app that runs on the user's machine: **Windows 10+ and macOS 12+**, both
  first-class.
- **Async I/O:** `httpx.AsyncClient` on an asyncio loop that lives on a **worker thread**;
  results marshal back to the GUI thread through Qt signals (`gui/tasks.py`). The Qt main
  thread must never block on a request, a sqlite write, or a browser call.
- **Storage:** one local SQLite file (price history + watches + cache) in the OS's user data
  dir via `platformdirs`. No ORM — plain `sqlite3` behind `storage/repository.py`.
- **Dependencies are pip-installed** (there is no vendoring): every dep must have wheels for
  macOS arm64 + x86_64 and Windows x64. Playwright (browser adapter) is an **optional
  extra** — the app must start and work without it.
- **Distribution:** PyInstaller, one spec per OS (`packaging/`), producing `Sale Hunter.app`
  and `SaleHunter.exe`.

### Where commands run
On the **host**, in the repo's `.venv` (macOS here; the same commands work on Windows with
`.venv\Scripts\`). There is no container. `deploy/Dockerfile` exists only to run the offline
test suite + linters reproducibly for CI — it can never run the GUI.

## Architecture (layered; one-way imports)

```
src/shopee_hunter/
├── __main__.py             # python -m shopee_hunter
├── app.py                  # bootstrap: AppContext, QML engine, bridge registration
├── envs.py                 # SALEHUNTER_* env overrides (dev switches, no secrets)
│
├── core/                   # PURE. no PySide6, no httpx, no sqlite, no I/O.
│   ├── models.py           # Money, Product, PriceSnapshot, Deal, Watch, SearchQuery
│   ├── deals.py            # discount scoring: claimed vs. observed-history drop
│   ├── watchlist.py        # Watch matching rules
│   ├── sale_calendar.py    # sale-day windows (double dates, payday, flash-sale slots)
│   ├── rate_limit.py       # token bucket (mandatory, conservative defaults)
│   ├── settings.py         # Pydantic settings tree (toml + env + user overrides)
│   ├── errors.py           # SourceBlocked / SourceUnavailable / ParseError …
│   └── logging.py          # logger factory + secret redaction
│
├── sources/                # ALL Shopee access. one seam, many transports.
│   ├── base.py             # SourceAdapter ABC + rate limit + retry/backoff
│   ├── registry.py         # @register_source / build_source
│   ├── parse.py            # pure wire-format → core.models (fixture-pinned)
│   ├── shopee_web.py       # /api/v4 JSON over httpx (needs imported cookies)
│   ├── shopee_browser.py   # Playwright persistent profile — the user's own session
│   ├── affiliate_api.py    # official signed Open/Affiliate API (when the user has keys)
│   └── fixture.py          # offline fixtures — the default in tests and demo mode
│
├── storage/                # sqlite: schema, migrations, repository
├── services/               # orchestration: scanner, price_history, scheduler, notifier
└── gui/                    # Qt + QML ONLY. no business rules.
    ├── window.py           # frameless + translucency + per-OS blur (with fallback)
    ├── tasks.py            # run_async(): asyncio worker thread ↔ Qt signals
    ├── bridge.py           # QObject slots QML calls
    ├── models.py           # QAbstractListModel for deals / watches
    └── qml/
        ├── AppWindow.qml   # the shell (drag region, traffic lights, glass background)
        ├── Theme/          # Theme.qml singleton — every token lives here
        ├── components/     # GlassCard, GradientButton, DealCard, Sparkline, Toast …
        └── views/          # Deals, Watches, History, Settings

config/     *.example.toml templates + secrets.README.md (live *.toml are gitignored)
packaging/  PyInstaller specs (macos.spec, windows.spec) + icons
scripts/    run_dev.py, live_check.py, capture_fixture.py, ui_screenshot.py
tests/      offline suite (default) + tests/live/ (opt-in, real site & real window)
```

### The four shared seams (this is the design — protect it)
1. **Source adapters** (`sources/base.py`, `registry.py`): one `SourceAdapter` contract
   (`search` / `fetch_item` / `flash_sale`), one registry, one place that owns rate
   limiting and retry. A new transport is a subclass + a registration.
2. **Deal engine** (`core/deals.py`): the *only* place that decides what counts as a deal.
   Shopee's own `raw_discount` is treated as a claim to be verified against observed price
   history, never as truth. GUI and notifier both consume its `Deal` objects.
3. **Async bridge** (`gui/tasks.py`): the single sanctioned crossing between the asyncio
   world and the Qt main thread. No `QThread` subclasses in feature code, no `asyncio.run`
   from a slot.
4. **Theme singleton** (`gui/qml/Theme/Theme.qml`): every color/radius/duration/easing/
   font token, plus `reducedMotion`. Components never hard-code a visual value — that is
   what keeps the two platforms looking identical and a restyle a one-file change.

### Coupling rule (enforced in review *and* in `tests/test_architecture.py`)
`core/` imports nothing from the project but `core/`. `sources|storage|services` may import
`core/` and never `gui/`. `gui/` holds no business rule. Pure logic must not import
`PySide6` at module level so it unit-tests headless.

## Adding a new source adapter
1. Create `src/shopee_hunter/sources/<name>.py`; subclass `SourceAdapter`.
2. Implement `search()` / `fetch_item()` / `flash_sale()`; return `core.models` objects by
   delegating wire-parsing to a pure function in `sources/parse.py`. Raise the typed errors
   from `core/errors.py` — never return an empty list to mean "blocked".
3. Decorate with `@register_source("<name>")` and import the module in
   `sources/__init__.py` so the decorator runs (the registry is empty until it does).
4. Add its settings block to `core/settings.py` **and** `config/settings.example.toml`.
5. Capture a real response with `python scripts/capture_fixture.py` into
   `tests/fixtures/<name>/` and add `tests/sources/test_<name>_parse.py` against it.
6. Add a live test in `tests/live/test_<name>_live.py` marked `@pytest.mark.live`.

## Adding a new QML view
1. Add `gui/qml/views/<Name>.qml`, using only `Theme.*` tokens; register the route in
   `AppWindow.qml`'s navigation model.
2. Data comes from a bridge slot / list model — never a direct Python call from QML.
3. Add the file to **both** PyInstaller specs' datas (a missing QML file only breaks the
   packaged build).
4. Add a `pytest-qt` smoke test that loads the view and asserts no QML warnings.

## Testing: two tiers, both mandatory
- **Offline (default, must stay green):** `pytest` — pure logic, fixture-based parsing,
  architecture rules, QML smoke loads. Network is blocked by `conftest.py`.
- **Live (opt-in, run before every release and after touching a source):**
  `pytest -m live` — real Shopee traffic and a real window. Plus two operator scripts:
  `python scripts/live_check.py --keyword "tai nghe"` (end-to-end scan in the terminal) and
  `python scripts/ui_screenshot.py` (launches the real app, screenshots every view).
  "The offline suite is green" is **not** evidence the tool works — a live run is.

## Branching & PRs (branch + PR for everything non-trivial)

1. Never commit non-trivial work directly to `main`. `git checkout -b feat/<kebab-topic>`
   (`fix/…`, `chore/…`, `docs/…`), implement there.
2. Push the branch and surface the PR URL; **do not merge into main yourself** unless told
   to — or unless the PR carries the `automerge` label and CI's own gate merges it.
3. Small standalone edits not tied to a feature (a `.gitignore` line, a `.claude/*` tweak)
   may go straight on main.

### PR description format (MANDATORY)
Every PR body follows `.github/pull_request_template.md`: **Context → Content / Changes →
Test Plan** (with `### Test Details` and `### Test Output / Feature Demonstration`), then
the checklist. `gh pr create --body` bypasses GitHub's template, so fill it explicitly:

```bash
sed -e 's/^<!--.*-->$//' .github/pull_request_template.md > /tmp/pr-body.md   # then fill it
gh pr create --base main --title "…" --body-file /tmp/pr-body.md
```
- **Paraphrase the request in Context — never paste the chat message.** Requests often
  arrive in Vietnamese; the PR states the problem in the author's own English words.
- **Never delete a heading.** A non-applicable section gets `N/A — <reason>`; the CI
  `pr-body` check fails a PR missing a required heading.
- **Test Output is evidence, not a claim.** Paste the real `pytest` tail, the
  `live_check.py` output, or a UI screenshot. "Tests pass" is not a test plan.

### CI: auto-review and auto-merge
`.github/workflows/` holds `ci.yml` (offline suite + lint on ubuntu/windows/macos),
`pr-review.yml` (Claude reviews the diff and must emit `VERDICT: APPROVE|BLOCKING`),
`automerge.yml` (merges only when: tests green **and** verdict APPROVE **and** the
`automerge` label is present **and** the reviewed commit is still HEAD), and `claude.yml`
(responds to `@claude` in comments). Known permanent exception: a PR that edits
`.github/workflows/**` cannot pass the review job — GitHub refuses the app a token when
workflow content differs from the default branch — so those need a manual merge.

## Common Commands

```bash
# Setup (host venv)
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # add ".[browser]" for the Playwright adapter
pre-commit install

# Run the app
python -m shopee_hunter                  # or: python scripts/run_dev.py --reload

# Tests
pytest                                   # offline suite (network blocked)
pytest -m live                           # LIVE: real Shopee + real window (opt-in)
pytest tests/core/test_deals.py -vv      # one file

# Live operator checks (evidence for a PR)
python scripts/live_check.py --keyword "tai nghe bluetooth" --max-price 500000
python scripts/ui_screenshot.py --out .artifacts/ui

# Quality
pre-commit run --all-files
mypy src/shopee_hunter                   # strict; not a commit gate yet

# Package
python packaging/build.py                # -> dist/ (.app on macOS, .exe on Windows)
```

## Documentation Language
All documentation (README, `docs/`, any process/feature `.md`, docstrings, comments,
commit messages, PR bodies, ADRs) **must be in English**, regardless of the conversation
language. Exception: only when the user explicitly asks for Vietnamese in a specific file.

## Coding Conventions
Standards live in **`.claude/CONVENTIONS.md`** — read it in full before non-trivial work.
Part 1 = universal Python (PEP 8, Google docstrings, type hints, Black/Ruff/isort/mypy).
Part 2 = project-specific (the three-layer rule, source adapters, the honest limits of
scraping Shopee, threading, UI/Theme rules, cross-platform, the two test tiers).
Part 3 = **Agent Working Principles** (think before coding, simplicity first, surgical
changes, goal-driven execution).

## Project State Files (DYNAMIC — read at session start)
- **`.claude/JOURNAL.md`** — daily work log; newest on top. Read first for recent context.
- **`.claude/FEATURE_LOG.md`** — one entry per large feature (append-only, newest on top).
- **`.claude/DECISIONS.md`** — ADRs; read before changing an architectural pattern.
- **`.claude/WORKFLOW.md`** — startup, the build/verify loop, live testing, pre-commit.

**Feature-log rule:** after any large feature/change (a new source adapter, a new view, a
change to a shared seam), append an entry to `.claude/FEATURE_LOG.md`. Skip it for tiny
edits, typo fixes, and pure docs.

## Sub-agent Workflow

> **STATUS: ENABLED** for non-trivial feature/refactor work. Small tasks (<~20 lines) or
> obvious fixes: do them directly in the main session.

| Phase  | Agent                | Tools                   | Purpose |
|--------|----------------------|-------------------------|---------|
| Search | `Explore` (built-in) | read-only               | Locate code/patterns before planning. |
| Plan   | `planner`            | Read, Grep, Glob        | Produce the implementation plan; writes no code. |
| Build  | `coder`              | Bash, Read, Write, Edit | Implement the plan + tests; validate with the tooling. |
| Verify | `reviewer`           | Read, Grep, Bash        | Senior **solution-architecture** review: abstraction, reuse, cohesion, coupling — plus correctness, conventions, tests. |
| Fix    | `debugger`           | Read, Grep, Bash, Edit  | Root-cause a failing test/error; minimal fix. |

Typical order: **Explore → planner → coder → reviewer**, invoking `debugger` only when a
test or run fails.

## Slash Commands
- `/resume` — read JOURNAL.md and brief on where work left off
- `/daily-wrap` — update JOURNAL.md with today's session summary
- `/adr` — create a new Architecture Decision Record in DECISIONS.md
