---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It shows the wording of each of the three proposed scenarios (`add-task`, `list-tasks`, `finish-task`): at least the story line and the expected result of each.
2. For each of the three it gives the runner's seeded check result (`SEEDED ✓ <id>`, or the runner's FAIL line for it) on the repo as it is, and says none of the features works yet. If the environment blocked the runner, it says the scenarios are not verified yet instead of calling them seeded.
3. It does not say any feature works, and it does not say the app was written.
