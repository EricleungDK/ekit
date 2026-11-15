---
max_turns: 20
allowed_tools: [Read, Bash, Glob, Grep]
runs: 2
---

/ekit:orchestrate-agent Model: Haiku (already picked). Task, free-form: `div(a, b)` in `calc.py` must raise `ValueError("division by zero")` when `b == 0`, and `cli.py` must print `error: division by zero` and exit 2 in that case. Branch `main` and HEAD are right; nothing to fetch. No subagent tools this run: do steps 2 to 4 up to the point where an agent would start. Show me the checklist and the units, do everything step 4 has you do before an agent starts, then stop and tell me what you would dispatch. Do not edit code.
