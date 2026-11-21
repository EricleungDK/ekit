---
max_turns: 20
allowed_tools: [Read, Bash, Glob, Grep]
runs: 2
---

/ekit:orchestrate-agent Model: Haiku (already picked). Task, free-form: `div(a, b)` in `calc.py` must raise `ValueError("division by zero")` when `b == 0`, and CI must also run `python3 -m compileall -q calc.py` before the tests. Branch `main` and HEAD are right; nothing to fetch. No subagent tools this run: show me the checklist and the units, then stop before any agent would start. Do not edit files.
