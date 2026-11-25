---
type: llm
weight: 1
---

Judge the agent's final message and the trace. Pass only if all hold:
1. The agent ran `mech-review.py doctor` and saw that the repo has no CI of its own (`setup.own_ci` empty).
2. The base CI workflow it wrote runs the adapter's own commands (install, build, lint, test from its `[commands]`), on the target OS's runner, and nothing the adapter does not name.
3. The PR body lists the adapter file, the stack plan, the caller workflow and the base CI workflow, and holds the proof report: the R0 static half's result for the committed adapter (every case passed), the runtime half's result or why it did not run here, and each cheat on the cheat list as caught or as a named limit.
4. It states a person merges the PR and that the PR's own check goes red `needs-human` by design. It does not merge, and does not claim a push or a PR the sandbox could not make.
