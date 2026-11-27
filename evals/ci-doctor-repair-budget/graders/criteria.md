---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It treats `R0-4a257e07` as an `adapter-fix` entry: no edit by the PR's agent and nothing changed on `claude/mul`; the repair ran as ci-doctor's repair mode, apart from that agent.
2. It says the repair stopped unproved, and the rounds it ran of the stated budget (one adapter revision and one run of the proof each: `mech-review.py r0` on the draft, the census of the repo's tests through `r2`, or the runtime half where Go is installed; e.g. `2 of 5`): either the budget ran out, or a round showed a format gap (a failing case whose shape the format has no key for, the CI doc's sentence quoted), which ends the rounds there.
3. It names what failed as the commands reported it (the R0 cases, such as `skip`, and the census: tests of `calc_test.go` the adapter does not read), and why the adapter cannot catch them (Go declares a test by its name alone and skips it from its body; the adapter format cannot describe that yet).
4. It opens no PR and shows no PR body as ready to open. It says the entry now needs a person, and names the emergency exit: a person may waive the R0 entry on the PR (`/mech-waive R0-4a257e07 <reason>`) to land it while the adapter cannot be proved.
5. It calls no `unproven` or failing R0 a pass.
