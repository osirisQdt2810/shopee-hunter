---
name: memory-lives-in-the-repo
description: Write project memories into .claude/memory/ in the repo, not the per-device memory directory
metadata:
  type: feedback
---

Memories for this project belong in `.claude/memory/` **inside the repository**, committed
with the code — not in the machine-local `~/.claude/projects/<slug>/memory/` directory the
harness defaults to.

**Why:** the user develops across more than one device. A memory that lives under `~/.claude`
exists only on the machine that wrote it, so the next device starts blind and the same
correction has to be given again. Committed to the repo, it travels with a clone and is
reviewable in a PR like any other project decision.

**How to apply:** same file-per-fact format and frontmatter as the harness memory system,
indexed by `.claude/memory/MEMORY.md`, which `.claude/CLAUDE.md` points at so it is read at
session start. Do not write to the per-device directory for this project.
