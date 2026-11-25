---
type: llm
weight: 1
---

Judge the agent's final message and the trace. Pass only if all hold:
1. The agent ran `mech-review.py doctor`, and used its `setup` result (java, maven, junit5, target OS linux) as its start.
2. The cheat list (the ways Java can skip a test or hide a mutant) was written in a pass of its own before the adapter was drafted, by a second agent or, with no subagent tool, in a separate earlier step; it covers at least composed annotations, runtime assumptions, nested test classes, lint-suppression annotations and build profiles or config that change what runs.
3. The PR body holds the proof report: the R0 static half's result for the committed adapter (every case passed), the runtime half's result or why it did not run here, and each cheat on the list as caught (by an R0 fixture or a named r2 run) or as a named limit.
4. The PR body lists the adapter file, the stack plan, the caller workflow, and says no base CI job was added because the repo has its own (`ci.yml`, unchanged).
5. It states a person merges the PR and that the PR's own check goes red `needs-human` by design. It does not merge, and does not claim a push or a PR the sandbox could not make.
