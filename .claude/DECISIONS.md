# Architecture Decision Records (ADRs)

This file records significant architectural and design decisions for **Sale Hunter**. Each
ADR captures the context, the decision, and its consequences so future contributors
understand the **why**, not just the **what**.

Add new ADRs at the **bottom** with the next sequential number. Use the `/adr` slash command
to have Claude help draft one.

## Format

```
## ADR-NNN: <short decision title>

**Date**: YYYY-MM-DD
**Status**: Proposed | Accepted | Deprecated | Superseded by ADR-XXX

### Context
<What is the issue we're seeing? What forces are at play?>

### Decision
<What did we decide to do?>

### Rationale
<Why did we decide this? What alternatives were considered?>

### Consequences
<Positive and negative outcomes. What becomes easier? What becomes harder?>

### Alternatives considered
<List of options that were evaluated and rejected, with reasons.>
```

---

## ADR-001: Sale Hunter is a local desktop app, not a scraping service

**Date**: 2026-08-23
**Status**: Accepted

### Context
The repository was scaffolded from an unrelated project — a PyQt6 plugin host for a desktop
flashcard app — and inherited its whole vocabulary: a plugin registry, vendored dependencies,
a host-application runtime, a plugin-bundle build step. None of it applies here. The
requirement is a tool that finds discounted Shopee items during sale days, running as a
**desktop app on Windows and macOS**.

The tempting alternative shape is a server: a scheduler somewhere in the cloud polling
Shopee and pushing notifications. That shape is what a "price tracker" usually is.

### Decision
Ship a **single-user desktop application**. All state (price history, watches, settings) is
local — one SQLite file in the OS's user-data dir. All requests originate from the user's own
machine, under the user's own IP and, where a login is needed, the user's own session. No
backend, no hosted component, no shared account.

### Rationale
- **The data is only obtainable as a user.** Shopee's endpoints work when they look like a
  logged-in browser on a residential connection. A datacentre IP polling on behalf of many
  users is precisely the traffic shape their anti-bot exists to stop, so the server design is
  *less* capable, not more.
- **A shared scraper is a shared liability.** One server hitting Shopee for N users
  aggregates both the ToS exposure and the ban risk into one blast radius. On the desktop,
  each user's traffic is their own and looks like what it is: one person shopping.
- **No credential custody.** A server would have to hold users' Shopee cookies. Not holding
  them is strictly better than protecting them.
- **It matches the ask.** The requested deliverable is a desktop app for Windows + macOS.

### Consequences
- (+) Runtime matches the data source; no false affordances.
- (+) Nothing to operate, nothing to pay for, no secrets at rest outside the user's machine.
- (+) Price history is genuinely private.
- (−) No scanning while the app is closed; the sale-calendar cadence (ADR-006) plus OS
  notifications mitigate this, but a closed laptop misses a flash slot.
- (−) Price history starts empty per install, so early verdicts have low confidence (ADR-005
  makes that visible rather than papering over it).
- (−) Everything ships to two OSes, so every dependency must have wheels for both.

### Alternatives considered
- **Cloud scraper + thin client** — rejected: worse data access, credential custody,
  centralised ToS/ban risk, hosting cost.
- **CLI-only tool** — rejected: the request specifies a polished GUI, and price history
  wants a chart, not a table dump.
- **Browser extension** — genuinely good session access, but cannot run a scheduler when the
  browser is closed, cannot own a SQLite history, and the UI ceiling is a popup. Kept as a
  future companion for exporting cookies into the app.

---

## ADR-002: QML / Qt Quick for the UI, not QWidgets

**Date**: 2026-08-23
**Status**: Accepted

### Context
The UI requirement is explicit: translucency, blur, gradients, animation, and **identical
appearance on Windows and macOS**. Within PySide6 there are two ways to build it — the
QWidgets stack (native controls, QSS styling) or Qt Quick (a declarative scene graph
rendered on the GPU).

### Decision
Build the entire UI in **QML / Qt Quick**. QWidgets appear nowhere except the one native
window-effect call per OS in `gui/window.py`.

### Rationale
- **Consistency is a rendering property.** QWidgets delegate drawing to each platform's
  native style, so the same code is a macOS app on macOS and a Windows app on Windows —
  which is the *opposite* of the requirement. Qt Quick draws every pixel itself, so one QML
  file produces one appearance everywhere.
- **The requested visuals are native to Qt Quick and fought for in QSS.** Gradients,
  `MultiEffect` blur/shadow, shader effects, opacity masks, and `Behavior on <property>`
  spring animations are first-class primitives. In QSS, gradients are limited, blur needs
  manual `QGraphicsEffect` compositing, and animation means `QPropertyAnimation` wiring per
  widget.
- **Animation must not cost Python.** Qt Quick animations run in the scene graph's own
  thread; a QWidget animation driven from Python competes with the GUI thread that is also
  handling scan results.
- **Styling stays centralised.** A `Theme` singleton with real property bindings makes a
  restyle a one-file change and makes "no literal colours in components" mechanically
  checkable.

### Consequences
- (+) One UI implementation, one appearance, GPU-accelerated motion.
- (+) The look asked for is achievable without fighting the toolkit.
- (−) A second language (QML/JS) in the repo, with its own formatter (`qmlformat`) and its
  own review discipline (`Theme` tokens only).
- (−) QML errors are runtime, not import-time — hence the mandatory `pytest-qt` smoke test
  that loads every view and fails on any QML warning.
- (−) Every QML file must be registered in both PyInstaller specs or the packaged app breaks
  where dev did not.

### Alternatives considered
- **QWidgets + QSS** — rejected: cannot deliver platform-identical rendering, and the
  requested effects are second-class.
- **Flet / Flutter** — beautiful and consistent, but it puts a Dart engine and a second
  toolchain under a Python app, and the async/threading story with our engine gets murkier.
- **Electron / Tauri + web UI** — best styling story of all, rejected: a JS/Rust runtime
  bolted to a Python core for one window, plus a much larger bundle.
- **CustomTkinter** — rejected: no real translucency, no gradients, no GPU animation.

---

## ADR-003: Async `httpx` on a worker-thread event loop, with exactly one Qt bridge

**Date**: 2026-08-23
**Status**: Accepted

### Context
A scan is N HTTP requests, each of which can take seconds or hang. Qt's event loop must keep
painting a 60fps UI throughout. Python offers several ways to combine the two, and mixing
them produces the classic PySide6 bug: a request finishing on a worker thread touching a Qt
object that belongs to the GUI thread.

### Decision
One asyncio event loop runs for the app's lifetime on a **single dedicated worker thread**.
All network and sqlite work is `async` and lives on that loop. The only sanctioned crossing
back to the GUI thread is `gui/tasks.py::run_async(coro, on_done)`, which submits the
coroutine and delivers the result via a Qt signal. `requests` is a banned import (ruff), and
so is `asyncio.run` inside a slot.

### Rationale
- **One loop, one thread, one crossing** is auditable. Two dozen `QThread` subclasses are
  not, and cross-thread Qt access fails intermittently rather than loudly.
- **Concurrency is what a scan needs**, and asyncio gives it with a cancellation model
  (`CancelledError`) that a user hitting "Stop" during a 60-item scan actually needs.
- `httpx.AsyncClient` gives connection pooling and HTTP/2 with one client instance, which
  matters because Shopee's anti-bot notices a new TLS handshake per request.

### Consequences
- (+) The UI never blocks; a scan is cancellable; throttling is enforceable in one place.
- (+) Services are plain `async def` functions, testable with `pytest-asyncio` and no Qt.
- (−) Everything I/O is `async`, including sqlite calls (wrapped via `to_thread`), which is
  more ceremony than a blocking call would be.
- (−) Contributors must respect the bridge; a stray `asyncio.run` in a slot deadlocks. The
  `ASYNC` ruff ruleset and the layer check catch the common shapes.

### Alternatives considered
- **`QThreadPool` + `QRunnable` with blocking `requests`** — rejected: no cancellation, no
  connection reuse, and thread-count tuning instead of concurrency.
- **`qasync` (asyncio driving the Qt loop)** — attractive, rejected for now: it makes the
  GUI loop the async loop, so one badly-behaved blocking call inside a coroutine freezes the
  window. The worker-thread design fails safe instead.

---

## ADR-004: One `SourceAdapter` seam with an ordered fallback chain; the browser adapter is optional

**Date**: 2026-08-23
**Status**: Accepted

### Context
There is no single reliable way to read Shopee data. There are three, with different
trade-offs: the official signed Affiliate/Open API (stable, needs approved keys, limited
coverage), the internal `/api/v4` JSON endpoints (full coverage, needs real browser cookies
and an anti-bot header, breaks without warning), and a real browser driven by Playwright
(most reliable, needs a ~150 MB browser download and a logged-in profile).

### Decision
Define **one** `SourceAdapter` contract (`search` / `fetch_item` / `flash_sale`) in
`sources/base.py`, register implementations with `@register_source("<id>")`, and configure an
ordered `sources.order` chain that the scanner walks until one adapter answers. Wire-format
parsing is a **pure function** in `sources/parse.py`, shared by every transport that speaks
Shopee's JSON. Playwright is an optional `[browser]` extra; the app must start and work
without it.

### Rationale
- **The transports differ; the data does not.** All three return the same product shape, so
  parsing belongs in one pure, fixture-pinned place and the transports become thin.
- **Blocking is normal, not exceptional.** A chain is the honest response: try the sanctioned
  API, fall back to the user's browser session, fall back to raw HTTP. Each raises a typed
  `SourceBlocked`, and the chain treats that as "try the next one" instead of "no results".
- **Rate limiting and retry belong to the seam.** Putting them in `base.py` means a new
  adapter cannot forget them, and one token bucket really bounds total outbound traffic.
- **Optional heavy dependency.** Forcing a browser download on someone who has affiliate
  keys is user-hostile; a hard `import playwright` at module scope would do exactly that.

### Consequences
- (+) A new transport (or another marketplace) is one subclass plus one registration.
- (+) Parsing regressions are caught offline by fixture tests; blocking is caught live.
- (+) Users choose their own trade-off between setup effort and reliability.
- (−) Four code paths to keep behaviourally equivalent; the shared parse module and a
  contract test suite run against every registered adapter are the mitigation.
- (−) A fallback chain can mask a broken primary adapter — so the scanner reports *which*
  adapter answered, and `live_check.py --source <id>` pins one deliberately.

### Alternatives considered
- **Affiliate API only** — rejected: needs approval most users will not have, and its catalog
  coverage is narrower than search.
- **Browser only** — rejected: a 150 MB download and a visible browser window as the price of
  first launch.
- **Raw HTTP only** — rejected: it is the path most likely to be silently blocked, which is
  the failure this app must not have.

---

## ADR-005: A discount is measured against observed history, never against Shopee's claim

**Date**: 2026-08-23
**Status**: Accepted

### Context
Every Shopee listing carries `price_before_discount` and `raw_discount` ("-50%"). Both are
seller-controlled. The dominant pattern during sale days is a listing permanently tagged with
a large discount against an "original" price nobody has ever paid. A tool that reports
Shopee's own percentage is not a deal hunter — it is a re-skin of the search page, and it will
confidently recommend the fakest listings, because those claim the biggest discounts.

### Decision
`core/deals.py` computes the reference price from the **median of observed non-flash price
snapshots** within a 90-day window, and derives `true_discount_pct` from that. Shopee's claim
is stored, used only as a labelled fallback when no history exists (`Confidence.NONE`), and
compared against the observed drop: a claim more than 15 points larger earns the
`CLAIM_INFLATED` flag, which excludes the deal from `is_genuine` and penalises its score.

### Rationale
- **Median, not mean**, so one 24-hour flash price cannot drag the baseline down and make
  every subsequent day look like a bargain.
- **Non-flash observations only** for the baseline, for the same reason — with a fallback to
  flash observations rather than discarding the only history we have.
- **Confidence is part of the verdict, not a footnote.** A fresh install has no history; the
  honest answer is "we cannot verify this yet", displayed as such, rather than a fabricated
  percentage.
- **Score is comparable across watches** so one ranked list is meaningful, and it saturates
  above ~60% because that range is where fake listings concentrate.

### Consequences
- (+) The app's core claim ("real discounts, not marketing") is implemented, not asserted.
- (+) One place owns the definition; the GUI and the notifier consume `Deal` objects and
  recompute nothing.
- (−) The app is least useful on day one and gets better as history accumulates. The UI must
  say so (the `THIN_HISTORY` badge) instead of hiding it.
- (−) Price history must be recorded on every scan, which makes storage load-bearing rather
  than a cache.

### Alternatives considered
- **Trust `raw_discount`** — rejected: it is the failure mode this project exists to fix.
- **Compare against competing listings for the same product** — genuinely valuable, deferred:
  it needs product matching across sellers (a much harder problem) and the same history
  machinery underneath. Revisit once history proves itself.

---

## ADR-006: The sale calendar drives scan cadence

**Date**: 2026-08-23
**Status**: Accepted

### Context
A fixed polling interval is wrong in both directions: fast enough to catch a flash slot means
thousands of pointless requests on a quiet Tuesday (and a rate-limit ban), while slow enough
to be polite means missing the 3 minutes when the price actually moved.

Shopee's Vietnamese storefront runs on a very predictable rhythm: double-date campaigns
(1.1 … 12.12), the mega days (9.9, 11.11, 12.12), payday sales (15th, 25th, month-end), and
fixed daily flash-sale slots (00, 09, 12, 15, 18, 21).

### Decision
`core/sale_calendar.py` models that rhythm as pure functions of an explicit `now` and returns
a `SaleTier`; `recommended_interval()` maps tier to cadence (6h when quiet, down to 5 min
during a mega sale) and tightens *ahead* of a big window so its opening minutes are covered.
Times are computed in the storefront's timezone (ICT), not the user's.

### Rationale
- Sale days are calendar days **in Vietnam**; deriving them from local time would shift
  12.12 by a day for a user in São Paulo.
- Pure functions of an injected clock make "what happens at 21:00 on 12.12" a unit test
  rather than a December vigil.
- The cadence is a *recommendation* layered under the hard token-bucket ceiling (ADR-007), so
  a calendar bug cannot become a traffic incident.

### Consequences
- (+) Requests are spent when prices move; quiet days are nearly free.
- (+) "Next sale in 3d 04h" is a UI feature that falls out of the same model.
- (−) The rhythm is region-specific: another storefront needs its own calendar. Contained to
  one module, and the tier abstraction is reusable.
- (−) Hard-coded slot hours will eventually drift from reality; they are constants at the top
  of the module with a comment saying so.

---

## ADR-007: Self-throttling is mandatory and conservative; the user's session is theirs

**Date**: 2026-08-23
**Status**: Accepted

### Context
The realistic worst outcome of this project is not "no deals found" — it is a user's Shopee
account or IP getting flagged. Scraper code accretes speed: a parallel keyword sweep here, an
unbounded pagination there, a retry loop that hammers a soft block into a hard one.

### Decision
Every outbound request passes a token bucket (`core/rate_limit.py`) whose defaults are 0.5
req/s with a burst of 4 and at most 2 concurrent requests, enforced inside `sources/base.py`
so no adapter can bypass it. `SourceBlocked` calls `penalise()`, which empties the bucket for
a cooling-off period. Retries are few (2) and slow (5s backoff). Pagination is bounded by a
total item cap, not a page loop.

The app never asks for a Shopee password, never stores one, and never ships a credential or
cookie. The browser adapter uses a persistent profile the user logs into themselves; the web
adapter uses cookies the user imports. Secrets live in a gitignored `secrets.toml` / the OS
keyring and are redacted from every log record (`core/logging.py`).

### Rationale
Being slow is cheap; being blocked is total. The tool is a watcher for one person, so the
polite cadence is sufficient by construction — and making it structural (in the seam, with
validated bounds in settings) means an over-eager future change has to argue with the type
system rather than just win.

### Consequences
- (+) Traffic looks like a person, not a crawler; the ban risk stays low.
- (+) Secrets cannot reach a log file or a pasted bug report.
- (−) A large watchlist scans slowly, and the settings UI must explain why the limits exist
  rather than offering a "turbo" toggle.

---

## ADR-008: Two test tiers — offline by default, live opt-in and required

**Date**: 2026-08-23
**Status**: Accepted

### Context
A green unit-test suite is worth very little here. Everything that actually breaks this app
is on the other side of a mock: Shopee changing a JSON field, the anti-bot deciding today is
the day, a QML binding that only fails on a real GPU. But a suite that hits the network is
non-deterministic, slow, and unrunnable in CI.

### Decision
Two tiers, both mandatory but at different times.

**Offline (`pytest`, the default):** pure `core/` logic, adapter parsing against captured
fixtures, the architecture/layering rules, and `pytest-qt` smoke loads of every QML view.
`conftest.py` blocks socket access, so an accidental live call fails instead of flaking.

**Live (`pytest -m live`, plus two operator scripts):** real requests and a real window.
`scripts/live_check.py` runs an end-to-end scan and reports through its exit code
(0 = deals, 2 = blocked, 1 = bug); `scripts/ui_screenshot.py` launches the real app and
screenshots every view. Live output is **required evidence in the PR** for any change to
`sources/`, `services/` or `gui/`, and is never run in PR CI.

### Rationale
- Determinism and reality are both required, and no single tier gives both.
- A live tier that could pass while the site refused us would be worse than none, so live
  tests assert the *typed* outcome: a `SourceBlocked` is a pass, a `ParseError` is a failure.
- Fixtures are **captured**, never hand-written (`scripts/capture_fixture.py`), so the
  offline tier tracks reality instead of tracking our beliefs about it.

### Consequences
- (+) CI is fast and deterministic; regressions in the wire format are still caught, by the
  human running the live check before the PR.
- (+) "It works" becomes a pasteable artefact instead of a claim.
- (−) A wire-format change can sit undetected between live runs — accepted: the alternative
  is a flaky CI that everyone learns to ignore.
- (−) Two commands to remember; `WORKFLOW.md` and the PR template both spell them out.

---

## ADR-009: Persisted settings tolerate unknown keys; wire payloads do not

**Date**: 2026-08-23
**Status**: Accepted

### Context
Two kinds of data get validated by Pydantic in this app, and they want opposite strictness.
A settings file may have been written by a *newer* build of the app (a user rolls back, or
syncs a config between machines); a wire payload may have been changed by Shopee.

### Decision
`core/settings.py` defines `PersistedModel` (`extra="ignore"`) as the base for anything read
back from disk, and `StrictModel` (`extra="forbid"`, frozen) for never-persisted payloads.
Settings load in a fixed precedence order (defaults → bundled TOML → user TOML → `SALEHUNTER_*`
env), and `save()` excludes secret fields by construction.

### Rationale
An older build refusing to start because of a key it does not recognise is a total, silent-in-
development failure. Conversely, an unexpected key in a Shopee response means we are parsing
something we do not understand, and quietly ignoring it produces wrong prices — the one thing
this app must never do.

### Consequences
- (+) Forward/backward config compatibility; secrets structurally excluded from the file the
  user might paste into a bug report.
- (+) Wire-format drift surfaces as a loud `ParseError` naming the field.
- (−) A typo'd settings key is silently ignored rather than reported; the Settings view is
  the intended way to edit, and `live_check.py --print-settings` shows what actually loaded.

---

## ADR-010: CI reviews and merges its own PRs, behind four simultaneous gates

**Date**: 2026-08-23
**Status**: Accepted

### Context
This is a single-maintainer project where the code is largely written in Claude Code
sessions. The bottleneck is not writing the change, it is the ceremony after it: waiting for
tests, re-reading the diff, clicking merge. But an auto-merge that trusts any one signal is
how an unreviewed regression lands on `main`.

### Decision
Three workflows. `pr-pipeline.yml` is the gate and holds every job that decides a PR's
fate: the offline suite and lint on ubuntu/windows/macOS, a check that the PR body kept
every required template heading, coverage, a Claude review of the diff against
`CONVENTIONS.md` emitting `VERDICT: APPROVE` or `VERDICT: BLOCKING`, and a merge job that
fires **only when all four hold**: tests green, verdict APPROVE, the `automerge` label
present, and the reviewed commit still `HEAD`. `ci.yml` re-runs the suite on pushes to
`main` and publishes the coverage badge. `claude.yml` answers `@claude` mentions.

The review job hands the action the workflow's own GITHUB_TOKEN so it skips the
OIDC-to-GitHub-App token exchange. Without that the gate cannot run at all unless the Claude
GitHub App is installed, and — worse — the exchange refuses any PR whose workflow files
differ from `main` by *returning* rather than failing, so the review job would go green
having reviewed nothing.

### Rationale
- The label makes auto-merge **opt-in per PR**, so a risky change simply does not get it.
- Re-checking that the reviewed commit is still HEAD closes the obvious hole: pushing a new
  commit after the approval.
- A machine-readable verdict is what makes the review a *gate* rather than a comment.
- The offline tier is what CI can honestly verify (ADR-008); live evidence is a human's job
  and lives in the PR body, which is why the body check is part of the gate.

### Consequences
- (+) Routine green PRs merge without a human click; the maintainer's attention goes to the
  ones that fail a gate.
- (+) Every merged PR has a recorded review and cross-platform test run.
- (+) A PR that edits `.github/workflows/**` is **reviewed** like any other. It used not to
  be: the action's OIDC-to-App token exchange refuses a workflow differing from the default
  branch, and refuses it by *returning*, so the job went green having reviewed nothing.
  Passing the action the workflow's own GITHUB_TOKEN skips that exchange entirely.
- (?) Whether such a PR also **auto-merges** is unverified. `gh pr merge` runs with
  `GITHUB_TOKEN`, which GitHub refuses for pushes that create or update workflow files; it
  is not established that the merge API applies the same rule. Until a workflow-touching PR
  has actually merged through the gate, assume it may need a manual merge.
- (−) The review is only as good as `CONVENTIONS.md`, which makes keeping that file honest
  part of the CI story rather than a documentation chore.
