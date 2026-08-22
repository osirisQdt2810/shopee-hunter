---
name: commit-coauthor-only-on-large-commits
description: Add the Co-Authored-By Claude trailer only to large feature/refactor commits, never to small ones
metadata:
  type: feedback
---

Only large commits — a real feature, a substantial refactor, a new source adapter or a new
QML view — carry `Co-Authored-By: Claude ...`. Small standalone commits that feel like
something the user could have written themselves (a config line, a doc correction, a
one-line fix, a `.gitignore` tweak) get **no** coauthor trailer.

**Why:** the trailer marks genuine co-authorship of substantial work. Stamping it on every
trivial commit inflates the signal until it means nothing, and it misattributes edits the
user would never have thought of as "assisted".

**How to apply:** judge by the weight of the change, not by who typed it. Default to
omitting the trailer and add it only when the commit is clearly a large piece of work. This
overrides the harness default of appending the trailer to every commit message.

See [[memory-lives-in-the-repo]] for why this file is here rather than in the per-device
memory directory.
