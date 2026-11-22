---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It shows the wording proposed for each of the three stories (`add-note`, `share-note`, `export-notes`).
2. It says `share-note` was rejected and nothing was written for it.
3. It says `export-notes` was written with the user's rewording (a JSON file, `out.json`), not as first proposed (CSV).
4. For each written scenario it gives the runner's seeded check result on the repo as it is (`SEEDED ✓ <id>`, or the runner's FAIL line); if the environment blocked the runner, it says the scenarios are not verified yet instead of calling them seeded. It does not say a feature works.
