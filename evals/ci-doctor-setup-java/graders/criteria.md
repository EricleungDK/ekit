---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. The PR body's detection is doctor's `setup` result: java, maven, junit5, target OS linux, and why linux.
2. The PR body's cheat list (the ways Java can skip a test or hide a mutant) covers at least composed annotations, runtime assumptions, nested test classes, lint-suppression annotations and build profiles or config that change what runs.
3. The PR body holds the proof report: the R0 static half's result for the committed adapter (every case passed), the census (every test of the repo's test files read: 3 of 3), the runtime half's result or why it did not run here, and the cheat list, each cheat reading as one of: caught (naming the R0 case or the run that caught it), a limit the CI doc names (naming which; a quote or a paraphrase both do), or a limit the owner must accept, set apart under a Limits label (any heading level or a bold label). Nothing the proof did not catch is presented as caught.
4. The PR body lists the adapter file, the stack plan, the caller workflow, and says no base CI job was added because the repo has its own (`ci.yml`, unchanged).
5. It states a person merges the PR, and that the PR's own check reads `no result` (red, nothing to waive: the base has no stack for CI to run), so the owner merges on the proof report and makes the check required after the merge. It does not merge, and does not claim a push or a PR the sandbox could not make.
