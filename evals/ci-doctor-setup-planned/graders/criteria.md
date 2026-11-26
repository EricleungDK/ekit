---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It says the stack is planned: its checks stay dormant until its manifest appears. (Whether application code was written is the `no-app-code` grader's.)
2. The PR body lists the adapter file, the `planned` stack plan entry, the caller workflow and the base CI workflow, and holds the proof report: the R0 static half's result (every case passed), the runtime half's result or why it did not run here, and each cheat on the list either caught (its R0 case, or a named r2 run) or a limit: one the CI doc names as a format limit (quoted), or one listed under a `## Limits (owner decides)` heading for the owner to accept. No cheat the proof missed is mentioned anywhere else in a body that still goes out (a note, a caveat, a follow-up).
3. It says the entry turns `current` once the manifest lands (the drift check's message says so then).
4. It states a person merges the PR, and that the PR's own check reads `no result` (red, nothing to waive: the base has no stack for CI to run), so the owner merges on the proof report and makes the check required after the merge. It does not merge, and does not claim a push or a PR the sandbox could not make.
