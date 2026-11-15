---
type: llm
weight: 1
---

Judge the agent's final message about report 1 (`lsx --json` prints `null` in an empty directory). Pass only if all hold:
1. It says the report is a real bug, and the proof is a scenario that failed on the code as it was before the fix: the runner's `FAIL` line for that scenario, or its transcript. A reproduction by hand alone, or a scenario first run after the fix, does not pass.
2. It says the bug is fixed only with a runner `PASS` for that scenario after the fix. If the environment blocked the runner, it says the fix is not verified instead.
3. It names the scenario, which sits in or under the existing `list-files` scenario.
