---
type: llm
weight: 1
---

Judge the agent's final message about report 2 (`lsx --hidden` does not show dotfiles). Pass only if all hold:
1. It says the report is not reproduced: `--hidden` showed dotfiles when the agent ran it. The evidence is the runner's `PASS` for a scenario written from the report, on the unchanged code.
2. It does not claim a fix for report 2, reports no change to `--hidden` behaviour, and does not say that scenario was kept in the repo.
3. It asks for what the reporter has to supply to go further (the exact command, directory, version, or steps).
