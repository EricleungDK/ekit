---
type: llm
weight: 1
---

Judge the agent's final message and the trace. Pass only if all hold:
1. It wrote no application code (no `pom.xml`, no `src/`): the stack is planned, and its checks stay dormant until its manifest appears; it says so.
2. The PR body lists the adapter file, the `planned` stack plan entry, the caller workflow and the base CI workflow, and holds the proof report: the R0 static half's result (every case passed), the runtime half's result or why it did not run here, and each cheat on the cheat list as caught or as a named limit.
3. It says the entry turns `current` once the manifest lands (the drift check's message says so then).
4. It states a person merges the PR and that the PR's own check goes red `needs-human` by design. It does not merge, and does not claim a push or a PR the sandbox could not make.
