---
type: llm
focus: trace
weight: 1
---

Judge the run's trace (tool calls and their output). The scenario folders are `.ekit/scenarios/add-note` and `export-notes`; `share-note` was rejected. Pass only if all hold:
1. For each of the two, the last `scenarios.py seeded <id>` call naming it comes after the last change to any file in that scenario's folder, and its output is `SEEDED ✓ <id>: fails on the repo as it is` with a reason about the missing app (no `notes.py`, a non-zero exit of the missing command), not a syntax error or a mistake of the scenario's own. A `CHECKS NOTHING YET`, `ERROR` or `N/A` as that last output fails this.
2. After the last change to any file under `.ekit/scenarios/`, the agent ran a full `scenarios.py run` (no scenario id) and then `scenarios.py check`, with no file change between them, and that `check` printed `last run FAIL` and `0 of 2 features working`.
3. Nothing for `share-note` exists at the end (no folder or file, at any depth), and the `export-notes` files written last use the JSON wording (`out.json`), not the CSV one.
4. No file outside `.ekit/scenarios/` (and the runner's own `.git/ekit/`) was written: no app code.
If the environment blocked the runner, pass only if the final message says the scenarios are not verified yet; never pass on a runner PASS for either.
