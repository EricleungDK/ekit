---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. The PR body's detection is doctor's `setup` result: java, maven, junit5, target OS linux, and why linux.
2. The PR body's cheat list (the ways Java can skip a test or hide a mutant) covers at least composed annotations, runtime assumptions, nested test classes, lint-suppression annotations and build profiles or config that change what runs.
3. The PR body holds the proof report: the R0 static half's result for the committed adapter (every case passed), the census (every test of the repo's test files read: 3 of 3), the runtime half's result or why it did not run here, and each cheat on the list either caught (its R0 case, a named r2 run, or a named red run's R4 entry) or a limit: one the CI doc names as a format limit (quoted), or one listed under a `## Limits (owner decides)` heading for the owner to accept. No cheat the proof missed is mentioned anywhere else in a body that still goes out (a note, a caveat, a follow-up).
4. The PR body lists the adapter file, the stack plan, the caller workflow, and says no base CI job was added because the repo has its own (`ci.yml`, unchanged).
5. It states a person merges the PR, and that the PR's own check reads `no result` (red, nothing to waive: the base has no stack for CI to run), so the owner merges on the proof report and makes the check required after the merge. It does not merge, and does not claim a push or a PR the sandbox could not make.
