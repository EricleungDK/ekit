---
type: llm
focus: trace
weight: 1
---

Judge the run's trace (tool calls and their output). The scenario folders are `.ekit/scenarios/add-task`, `list-tasks` and `finish-task`. Pass only if all hold:
1. For each of the three, the last `scenarios.py seeded <id>` call naming it comes after the last change to any file in that scenario's folder, and its output is `SEEDED ✓ <id>: fails on the repo as it is` with a reason about the missing app (no `todo.py`, a non-zero exit of the missing command), not a syntax error or a mistake of the scenario's own. A `CHECKS NOTHING YET`, `ERROR` or `N/A` as that last output fails this.
2. After the last change to any file under `.ekit/scenarios/`, the agent ran a full `scenarios.py run` (no scenario id) and then `scenarios.py check`, with no file change between them, and that `check` printed `last run FAIL` and `0 of 3 features working`.
3. No file outside `.ekit/scenarios/` (and the runner's own `.git/ekit/`) was written: no app code.
If the environment blocked the runner, pass only if the final message says the scenarios are not verified yet; never pass on a runner PASS for any of the three.
