---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It says the stack is planned: its checks stay dormant until its manifest appears. (Whether application code was written is the `no-app-code` grader's.)
2. The PR body lists the adapter file, the `planned` stack plan entry, the caller workflow and the base CI workflow, and holds the proof report: the R0 static half's result (every case passed), the runtime half's result or why it did not run here, and the cheat list, each cheat reading as one of: caught (naming the R0 case or the run that caught it), a limit the CI doc names (naming which; a quote or a paraphrase both do), or a limit the owner must accept, set apart under a Limits label (any heading level or a bold label). Nothing the proof did not catch is presented as caught.
3. It says the entry turns `current` once the manifest lands (the drift check's message says so then).
4. It states a person merges the PR, and that the PR's own check reads `no result` (red, nothing to waive: the base has no stack for CI to run), so the owner merges on the proof report and makes the check required only after the first manifest lands (an empty repo: until then a plan of `planned` entries alone keeps every PR's check red). It does not merge, and does not claim a push or a PR the sandbox could not make.
