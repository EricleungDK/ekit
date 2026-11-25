---
max_turns: 30
allowed_tools: [Skill, Read, Bash, Edit, Write, Glob, Grep]
runs: 2
---

From my retro of this repo's last PRs, one mistake to turn into a check: PR #12 changed `app/core.py` and left `CHANGELOG.md` alone, though `AGENTS.md` says a behaviour change under `app/` updates it. Evidence: #12's commit is in `git log`; #15 did the same. The repo's CI runs ekit's mech-review with the python stack (`--test-paths 'tests/**'`). Make the check, commit it, and show me it works.
