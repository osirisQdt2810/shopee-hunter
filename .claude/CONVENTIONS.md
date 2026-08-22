# Coding Conventions

This file defines coding standards for **Sale Hunter** (a PySide6/QML desktop app). All code must
comply. The `reviewer` agent uses this file as its rubric.

## How this file is organized

Three parts:
- **Part 1 — Universal Python Standards**: language-level, professional conventions that
  apply to any modern Python project (PEP 8, Google Python Style Guide, best practices).
- **Part 2 — Project-Specific Rules**: rules unique to *this* desktop app — the source-adapter
  model, the shared seams, packaging, cross-platform, core/Qt separation.
- **Part 3 — Agent Working Principles**: how the agent should *work* (adapted from the
  karpathy guidelines): think before coding, simplicity first, surgical changes,
  goal-driven execution.

When standards conflict, Part 2 overrides Part 1, and both override personal preference.
Part 3 governs *behavior*, not code shape.

---

# PART 1 — Universal Python Standards

These define what professional Python looks like at companies like Google, Meta, Anthropic.

## Style Guide References
- **PEP 8** — https://peps.python.org/pep-0008/
- **Google Python Style Guide** — https://google.github.io/styleguide/pyguide.html
- **PEP 484 (type hints)**, **PEP 257 (docstrings)**, **PEP 604 (unions)**, **PEP 585 (generics)**

## Tooling (enforced automatically)

| Tool | Purpose | Config |
|---|---|---|
| Black | Code formatter | line length 88, target Python 3.13 |
| Ruff | Linter | rules: E, F, W, N, UP, B, SIM, RUF |
| isort | Import sorter | profile = "black" |
| mypy | Type checker | strict mode (manual / CI; not a commit gate yet) |
| pytest | Test runner | with `pytest-mock` |
| pre-commit | Git hooks | runs Black, Ruff, isort, hygiene on staged files |

Run checks locally before committing:
```bash
pre-commit run
pytest tests/ -vv
```

## Type Hints — Required
- **Mandatory** on all public function/method parameters and return values.
- Use `from __future__ import annotations` at the top of every file (keeps annotations as
  strings — cheap, import-safe, and avoids runtime evaluation surprises).
- Generic types: `list[str]` not `List[str]` (PEP 585).
- Unions: prefer `X | None` (PEP 604). `Optional[X]` is tolerated where it reads clearer.
- No bare `Any` without a comment explaining why.

```python
from __future__ import annotations

def accuracy_ratio(good: int, bad: int, missed: int) -> float:
    ...
```

## Naming

| Item | Convention | Example |
|---|---|---|
| Module | `snake_case` | `ease_pipeline.py` |
| Function/method | `snake_case` | `register_transformer` |
| Variable | `snake_case` | `card_id` |
| Class | `PascalCase` | `FeaturePlugin` |
| Constant | `UPPER_SNAKE_CASE` | `DEFAULT_THRESHOLD` |
| Private | prefix `_` | `_apply_ease` |
| Test file | `test_*.py` | `test_overdue_guard.py` |
| Test class | `Test*` (PascalCase) | `TestOverdueRule` |
| Test method | `test_*` | `test_forced_ease_when_overdue` |

## Docstrings (Google Style)
Required on every public function/method, every class, and every module (top-of-file).
```python
def forced_ease(card: Card, requested: int) -> int | None:
    """Return the ease an overdue card should be graded at.

    Args:
        card: The card being answered.
        requested: The ease the user/another feature requested (1-4).

    Returns:
        The forced ease (1 or 2), or None to leave ``requested`` unchanged.
    """
```

## Error Handling
- **No** bare `except:` / `except Exception:` without re-raising — catch specific types.
- **No** silent failures (`except: pass`).
- Log with context; re-raise after logging unless at a process/UI boundary.
- In GUI glue, surface failures to the user (a toast / banner in the QML shell), never swallow
  silently. A scan that fails partially still reports the deals it did find.

## Imports
- isort order: stdlib → third-party → local (blank line between groups).
- No wildcard imports. Absolute imports preferred.
- **Lazy-import heavy or optional deps inside functions**, not at module top.

## Testing
- pytest only. File `test_<module>.py`. **Tests are grouped in `Test<Topic>` classes** —
  every test is a method `test_<behavior>_<condition>(self, …)`; **no bare module-level
  `def test_*` functions**. Module-level helpers/fixtures stay module-level (prefixed `_`).
- Coverage target ≥80% for new logic in `core/` and feature logic modules.
- Use `pytest.fixture` for setup (fixtures inject into methods normally).
- `core/` needs no Qt and no network; pure logic must be testable without either. Qt-touching
  tests use `pytest-qt` and are marked `gui`.
- **Provider functionality uses the contract pattern, not mock-only.** Default unit tests
  mock the HTTP/transport layer (inject a fake), but each provider's behaviour is also
  exercised against the REAL provider via an abstract base test class with two subclasses: a
  `Fake…` subclass that always runs (free, offline) and a real subclass marked
  `@pytest.mark.llm` (LLM) or `@pytest.mark.integration` (other live APIs) that builds the
  configured provider and **auto-skips when credentials are absent** (so CI stays green).
  Real creds/cookies come from an untracked override (`config/secrets.toml` or `SALEHUNTER_*` env),
  never the tracked bundled config. Run `-m "not llm and not integration"` to stay free.

## Code Organization
- Single Responsibility: 1 class = 1 clear purpose.
- Soft limits: function < 50 lines, class < 300 lines — split if larger.
- Constructor injection for dependencies — **no** global mutable state, no singletons
  (the one allowed singleton is the `AppContext`, created once in `app.py` at startup).

## Security
- **Never** hard-code secrets/API keys. Provider keys live in the config store.
- Validate input at boundaries (config values, `pycmd` payloads, note fields).
- **Never** log API keys, auth tokens, or PII.

## Comments
- Comments explain **why**, not **what**. No commented-out code (Git remembers).
- TODO format: `# TODO(username): description`.

## Git Commit
- Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
- One commit = one logical change. Subject ≤72 chars, English, imperative.

## Convention Enforcement on Existing Code
"Touch it, fix it": bring lines you change up to standard; don't auto-format surrounding
unchanged lines. New files: full compliance. Pre-commit runs on **staged files only** —
never `black .` / `ruff check .` at the repo root.

---


# PART 2 — Project-Specific Rules (Sale Hunter / PySide6 desktop app)

## The three-layer rule (this is the architecture — protect it)

```
core/  ──► pure Python. NO PySide6, NO httpx, NO sqlite, NO I/O of any kind.
sources/, storage/, services/  ──► I/O. May import core/. NEVER import gui/.
gui/  ──► Qt + QML only. May import core/ and call services/. Holds NO business rule.
```

Import direction is one-way and enforced by `tests/test_architecture.py`:
- `core/*` must not import `PySide6`, `httpx`, `sqlite3`, `playwright`, or any sibling layer.
- `sources/*`, `storage/*`, `services/*` must not import `gui/*` or `PySide6`.
- `gui/*` must not contain price/discount/deal logic — it renders what `core/` decided.

If a rule "needs" to live in the GUI to be convenient, the rule is in the wrong place.

## Source adapters (all site access goes through one seam)
- Every way of getting data out of Shopee is a `SourceAdapter` subclass in `sources/`,
  registered with `@register_source("<id>")`, built by `build_source(id, settings)`.
- The adapter contract is small on purpose: `search()`, `fetch_item()`, `flash_sale()`.
  Adding a transport (official API, browser, another marketplace) = one subclass + one
  registration + one settings block. No caller changes.
- **Adapters return `core.models` objects, never raw JSON.** Parsing/normalising Shopee's
  wire format (prices are integers ×100_000, `raw_discount` is a percent int, …) happens in
  the adapter's `parse` module — a pure function that a fixture test pins.
- Never put an adapter's retry/backoff in the caller. `sources/base.py` owns rate limiting
  and retry; an adapter only describes one request.

## Talking to Shopee (be honest about this)
- Shopee has real anti-bot protection. Assume **any** unauthenticated request can return
  `error: 10 / server busy`, a captcha page, or an empty result set — that is normal
  operation, not a bug. Handle it as a typed `SourceBlocked` error and let the UI say so.
- Order of preference: official Affiliate/Open API (signed, stable) → browser adapter using
  the user's own logged-in session → raw HTTP with imported cookies. Never ship a
  hard-coded credential, token, or someone else's cookie.
- **Rate limit by default, always.** The token bucket in `core/rate_limit.py` is not
  optional and its defaults are conservative. This is a personal deal-watcher, not a
  crawler: no fan-out over shops, no unbounded pagination, no parallel keyword sweeps
  beyond the configured worker count.
- Respect the user's session: the browser adapter uses a persistent profile the user logs
  into themselves. The app never asks for a Shopee password and never stores one.

## Threading (never block the Qt main thread)
- Network, sqlite, and browser work run off the GUI thread. The only sanctioned bridge is
  `gui/tasks.py` (`run_async(coro, on_done)`) which drives an asyncio loop on a worker
  thread and marshals the result back with a Qt signal.
- QML never calls a `sources/` or `storage/` function directly; it calls a slot on a bridge
  object, which delegates to a service.
- A long scan must stay cancellable (`asyncio.CancelledError` propagates) and must report
  progress through a signal, not by polling.

## UI (the app is supposed to look good — that is a requirement, not a nice-to-have)
- The UI is **QML/Qt Quick**, not QWidgets. Qt Quick renders through its own scene graph, so
  the same QML is pixel-identical on Windows and macOS — that consistency is the reason for
  the choice, and it is why native-widget styling must not creep in.
- **All** colors, radii, spacings, durations, easings, font sizes come from the
  `Theme` QML singleton (`gui/qml/Theme/Theme.qml`). A literal `#rrggbb`, `radius: 12`, or
  `duration: 200` in a component is a review defect.
- Animation: use `Behavior on <prop>`, `states`+`transitions`, or `SequentialAnimation`.
  Never animate by driving a property from a Python timer.
- Frameless + translucent windows are done once, in `gui/window.py` +
  `gui/qml/AppWindow.qml`; components must not touch window flags. macOS gets its real
  vibrancy blur, Windows gets the acrylic/`DwmSetWindowAttribute` path, and both fall back
  to a painted gradient scrim — every visual must remain legible with the blur *absent*.
- Motion respects `Theme.reducedMotion` (driven by the OS setting); durations collapse to 0
  rather than being skipped conditionally at each call site.

## Cross-platform (macOS + Windows are both first-class)
- Use `pathlib` and `platformdirs` for every path. No `/tmp`, no `~/Library`, no `%APPDATA%`
  written by hand, no `os.system`.
- Anything platform-specific lives behind a function in `core/platform_api.py` (or
  `gui/window.py` for window effects) with a working fallback on the other OS. `if
  sys.platform == "darwin"` scattered through feature code is a defect.
- Deps must have wheels for macOS (arm64 + x86_64) and Windows. Check before adding.
- Both PyInstaller specs (`packaging/`) must be updated in the same change as any new
  QML file, resource, or data dir — a missing entry only fails after a build, never in dev.

## Config & secrets
- Settings are a Pydantic model tree (`core/settings.py`) loaded from
  `config/settings.toml`, overridden by `SALEHUNTER_*` env vars, persisted to the user
  config dir. Persisted models tolerate unknown keys (a newer version's key must not
  crash an older build); never-stored payload models are strict.
- Secrets (API keys, cookie jars) live in `config/secrets.toml` / the OS keyring — both
  gitignored. Nothing secret is ever logged, and `logging` redacts known key names.

## Testing (two tiers, both required)
- **Tier 1 — offline (`pytest`, default):** pure `core/` logic, adapter parsing against
  committed fixtures under `tests/fixtures/`, architecture rules, and `gui` smoke tests
  under `pytest-qt`. Must be fast, deterministic, and network-free — `tests/conftest.py`
  fails any test that opens a socket unless it is marked `live`.
- **Tier 2 — live (`pytest -m live`, opt-in):** hits the real site and launches the real
  window. Never runs in the default suite or in PR CI. See `.claude/WORKFLOW.md` for the
  commands. A live test may be skipped for missing credentials but must never be silently
  green when the site refused it — assert the typed error instead.
- A fixture is captured, not hand-written: `scripts/capture_fixture.py` records a real
  response so parsing tests track reality.

## When you discover a new project rule
Add it here in the same change, with one line of *why*. If it is an architectural choice,
record an ADR in `.claude/DECISIONS.md` and reference it.

# PART 3 — Agent Working Principles

Adapted from the *karpathy guidelines* (the karpathy agent guidelines). These govern
how the agent should work, not how code is shaped.

## 1. Think before coding
- State assumptions explicitly. If genuinely uncertain, ask — don't pick silently.
- If multiple interpretations exist, surface them. Push back when a simpler path exists.

## 2. Simplicity first
- The minimum code that solves the problem. No features beyond what was asked.
- No abstraction for single-use code; an abstraction is earned by ≥2 real call sites.
- No "flexibility"/config that wasn't requested. No error handling for impossible cases.
- Heuristic: "Would a senior engineer call this overcomplicated?" If yes, rewrite. If 200
  lines could be 50, rewrite. (This sits in tension with Part 2's seams — the seams *are*
  the earned abstractions here, justified by multiple features; do not invent new ones
  speculatively beyond them.)

## 3. Surgical changes
- Touch only what the task requires. Every changed line traces to the request.
- Don't "improve" adjacent code, comments, or formatting. Match existing style.
- Remove imports/vars/functions *your* change made unused; leave pre-existing dead code
  (mention it, don't delete it) unless asked.

## 4. Goal-driven execution
- Turn imperative tasks into verifiable goals:
  - "Add validation" → "write tests for invalid inputs, then make them pass".
  - "Fix the bug" → "write a test that reproduces it, then make it pass".
- For multi-step work, state a brief plan with a verification check per step, then loop
  until every check is green.
