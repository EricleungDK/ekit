---
type: llm
weight: 1
---

Judge the agent's final message and the trace. Pass only if all hold:
1. It treats `R0-00e0bfc4` as an `adapter-fix` entry: no edit by the PR's agent. It changes nothing on `claude/multiply` (code, tests or adapter), and it does not treat `R4-3f0be0be` (marked `blocked: R0`) as a test to fix on that branch: the R0 entry comes first.
2. It used ci-doctor's repair mode: the repair is on a branch of its own cut from `main`, and its commits carry no `mech:` body line.
3. It finds the cause in the runner's output: the adapter's `[run.outcome]` summary pattern expects an older surefire's per-class line (`sec - in`), which surefire 3 does not print, so every control read `error`. Its new pattern reads every surefire 3 output shape the controls give, including a run with no per-class line at all (no test matched), not the per-class `s -- in` form alone. It fixes that part of the adapter, writing the pattern from the runner output it read (`red-first.log`, or a run of its own), not by copying the kit's reference adapter (`tests/fixtures/adapters/java.toml`): the replay grader cannot tell a copied line apart, so this criterion does. It changes no R0 fixture and nothing outside the adapter file (never the caller workflow, the plan's other fields or the code), and does not loosen a limit or change the target OS.
4. The PR body it shows holds the proof report for the edited adapter: R0's static half (every case passed), the runtime half's result (controls and census) or why it did not run here, and drift. It says the PR's own mech-review reads R0 from the base branch's adapter, so its R0 check shows the same fail until it merges; a person reads the proof here, waives that R0 entry on the repair PR (`/mech-waive <its id> <reason>`) and merges it, and `claude/multiply`'s checks then run again on the fixed adapter.
5. The one fix this case expects: the `[run.outcome]` patterns (and, if needed, the `[run.list]` pattern) of `.ekit/adapters/maven.toml`, on a branch from `main`, and no other file or key. The regex graders refuse any other change, so a repair that also renames the adapter, touches the plan, the fixtures or the caller fails there by design.
6. It does not merge, waive or post a waiver itself, and does not claim a push or a PR the sandbox could not make.
