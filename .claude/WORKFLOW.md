# Daily Workflow

Quick reference for working on **Sale Hunter** (`shopee_hunter`) — a PySide6/QML desktop
app that hunts Shopee discounts — with Claude Code.

---

## First-time setup (once)

**macOS / Linux**
```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # add ".[browser]" for the Playwright source adapter
pre-commit install             # installs git hooks into .git/hooks/
```

**Windows (PowerShell)**
```powershell
py -3.13 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install
```

Optional (only for the browser adapter):
```bash
pip install -e ".[browser]" && playwright install chromium
```

Verify the toolchain:
```bash
pre-commit run --all-files     # dry run on everything
pytest                         # offline suite must be green before you start
```

---

## Start a session

```bash
cd <repo root>
claude
```
Inside Claude Code, run `/resume` to read `JOURNAL.md` and get oriented.

---

## The build/verify loop (host venv — no container)

```bash
python -m shopee_hunter                 # run the app
python scripts/run_dev.py --reload      # run it with QML hot-reload while styling
pytest                                  # offline suite (network blocked by conftest)
pytest tests/core/test_deals.py -vv     # one file
pre-commit run                          # black + ruff + isort + qmlformat + layer check
mypy src/shopee_hunter                  # strict types (manual; not a commit gate yet)
```

`QT_QPA_PLATFORM=offscreen pytest -m gui` runs the Qt tests without a visible window —
that is exactly what CI does.

---

## Live testing (REQUIRED — "pytest is green" is not evidence)

The offline suite proves the *logic* is right against recorded fixtures. It cannot prove the
tool still works, because the part that breaks is the part fixtures replace: Shopee's wire
format, its anti-bot behaviour, and the real window on a real GPU. So every change that
touches `sources/`, `services/`, or `gui/` needs a live run, and the output goes in the PR.

**1. End-to-end scan in the terminal** — the fastest real signal:
```bash
python scripts/live_check.py --keyword "tai nghe bluetooth" --max-price 500000
python scripts/live_check.py --keyword "ban phim co" --source browser --json
```
Exit code is the result: `0` deals found, `2` the site blocked us (expected sometimes — that
is a *pass* for the adapter: it raised `SourceBlocked` instead of pretending), `1` a real bug.

**2. The real window, screenshotted** — proves the UI actually renders:
```bash
python scripts/ui_screenshot.py --out .artifacts/ui       # every view
```
Attach the PNGs to the PR when the change is visual.

**3. Live pytest tier** — opt-in, never in PR CI:
```bash
pytest -m live -vv                       # real Shopee + a real window
pytest -m live tests/live/test_shopee_web_live.py -vv
```
A live test may skip for missing credentials. It must never pass silently when the site
refused it — it asserts the typed `SourceBlocked`, so a block is a known outcome and a
*changed wire format* is a failure.

**4. Refresh a fixture when the wire format moved:**
```bash
python scripts/capture_fixture.py --keyword "tai nghe" --out tests/fixtures/shopee_web/
pytest tests/sources -vv                 # parsing tests now track reality
```

---

## Before you push

```bash
pytest && pre-commit run --all-files && python scripts/live_check.py --keyword "tai nghe"
```
Then branch + PR (never commit non-trivial work to `main`):
```bash
git checkout -b feat/<short-kebab-topic>
git push -u origin HEAD
sed -e 's/^<!--.*-->$//' .github/pull_request_template.md > /tmp/pr-body.md   # fill it in
gh pr create --base main --title "…" --body-file /tmp/pr-body.md
gh pr edit --add-label automerge      # optional: let CI merge it once green + APPROVE
```

### What CI does to your PR
1. **`ci.yml`** — offline suite + lint on ubuntu, windows and macOS (py3.11 + 3.13), plus a
   `pr-body` check that every required template heading is present.
2. **`pr-review.yml`** — Claude reviews the diff against `CONVENTIONS.md` and must end with
   `VERDICT: APPROVE` or `VERDICT: BLOCKING`.
3. **`automerge.yml`** — squash-merges only when tests are green **and** the verdict is
   APPROVE **and** the `automerge` label is on **and** the reviewed commit is still HEAD.
4. **`claude.yml`** — replies to `@claude` in a PR/issue comment.

Known permanent exception: a PR touching `.github/workflows/**` cannot pass `pr-review`
(GitHub withholds a token when workflow content differs from the default branch) — merge
those by hand.

---

## Packaging

```bash
python packaging/build.py            # current OS -> dist/
# macOS   -> dist/Sale Hunter.app   (then: python packaging/build.py --dmg)
# Windows -> dist/SaleHunter/SaleHunter.exe
```
Adding a QML file, an icon, or a data dir? Update **both** specs in `packaging/` in the same
commit — a missing entry works in dev and only fails in the bundle.

---

## Subagent workflow (ENABLED)

For non-trivial features/refactors:
1. **Explore** (built-in) — locate the relevant seams, adapters, views, tests.
2. **planner** — produce the plan (files, signatures, edge cases). No code.
3. **coder** — implement the plan + tests; validate with the tooling.
4. **reviewer** — solution-architecture review (abstraction, reuse, cohesion, coupling) +
   correctness, conventions, the two test tiers.
5. **debugger** — only when something fails; root-cause first, minimal fix.

Small tasks (<~20 lines) or obvious fixes: do them directly in the main session.

---

## Pre-commit hooks (what runs on `git commit`)

| Hook | What it does | If it fails |
|------|--------------|-------------|
| hygiene set | trailing whitespace, EOF, YAML/TOML/JSON syntax, LF endings, big files, private keys | re-stage the fixed files |
| `isort` | import order (profile=black) | auto-fixed; re-stage |
| `black` | formatting | auto-fixed; re-stage |
| `ruff --fix` | lint (incl. `ASYNC`, `PTH`, `DTZ`) | fix the reported rule |
| `qmlformat` | QML formatting via the PySide6 wheel | auto-fixed; re-stage |
| `layer-check` | one-way imports: `core/` pure, `gui/` ruleless | move the code, don't silence it |

`mypy` is deliberately **not** a commit gate yet — run it manually on what you touched.

---

## End of session

Run `/daily-wrap` to append today's entry to `JOURNAL.md`. If the change was large (a new
source adapter, a new view, a change to a shared seam), also append to `FEATURE_LOG.md`;
if it changed an architectural pattern, run `/adr`.
