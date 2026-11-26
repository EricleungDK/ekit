# Mech-review entries

Entries arrive classified. Use `class`, `severity`, `hint`, `forbidden`. Don't re-derive from logs.

## Open the answer

First lines of the answer, one per `severity: fail` entry, as a plain list:

`<id> → <label>: entry <file>:<line>, <problem>`

`<label>` is one exact token from the class map: `sandbox/env`, `flaky`, `real bug`, `adapter-fix`, `Needs-you`. An entry Gate 3 holds opens with `<id> → held: blocked by <R0 id>` instead. The class-map tokens are read by the finish report, so copy them character for character; a held entry goes under its Open line, never ticked.

## Gate

1. Envelope `head` ≠ `git rev-parse HEAD` → **stale** ([stale.md](stale.md): judge only the run for your SHA). Rerun mech-review at HEAD.
2. `severity: confirm` → not red. Reviewer decides. List under Open (finish). `severity: waived` → not red: a person let it through (`waiver.by`, `waiver.reason`). Leave it; list it under Open.
3. `blocked: R0` on an `agent-fixable` entry → not yet red: its check read the code through the adapter R0 failed, so it may be a misread. No fix round; list it under Open. It is read again when the PR runs on the repaired adapter. The hold ends once a person waives the R0 entry, or the repair stops out of budget: then classify it below, so an `agent-fixable` one is a fix round of the PR's agent, otherwise it joins the Needs-you block with the R0 entry. A `needs-human` one stays the person's.
4. `severity: fail` → classify below.

## Class map

| `class` | Label (use verbatim) | Next action |
|---|---|---|
| `env` | sandbox/env | No app code or test change. Fix the environment (install the missing tool, or rerun where it failed). Protected CI config → Needs-you. Can't rerun → verification debt. |
| `agent-fixable`, check `R4` | flaky | Follow [flaky.md](flaky.md). |
| `agent-fixable`, other | real bug | Fix red→green: the entry's test or rule. |
| `adapter-fix` | adapter-fix | The checker needs the fix, not this PR: `R0` static or `R0` runtime (the adapter misreads the tests or the runner), `D` (a manifest no plan entry covers), `CI` (the adapter's parser failed, or the stack plan does not read). No edit by the PR's agent, on this branch: CI reads the adapter and the plan from the base branch, so an edit here judges nothing and is the agent tuning its own checker. Next: ci-doctor's repair mode (`/ekit:ci-doctor`, as a run of its own on its own branch) opens an adapter-fix PR; a person merges it, then this PR runs again on the fixed base. A person's `/mech-waive` on the `R0` or `D` entry is the emergency exit for an urgent PR (Needs-you block, `Decide:`); a `CI` entry has none. |
| `needs-human` | Needs-you | No edit. Needs-you block (finish shape; `Decide:` in place of `Run:`). If the answer is yes, the user posts the entry's ready-made line from the sticky comment (`/mech-waive <id> <reason>`) on the PR; the check re-runs on its own where the repo has the mech-waive caller, else they re-run the failed `report` job. You never post, edit or delete that comment. |

Each `agent-fixable` fail: open its fix plan with two lines, verbatim: `Fix: <hint>` and `Forbidden: <forbidden>`. Your steps go after them. Never take the forbidden route.

## R3 MISSED mutants

A MISSED mutant is a change to your code that no test noticed. For each one, in this order:

1. **A caller or user would see the difference** → add the assert on that output, return value, exit code or file. This is the usual case.
2. **Nothing observable changes** (an equivalent mutant: a default nobody passes, a redundant condition, a second cleanup of the same thing) → simplify the code until the variant is gone. Less code, same behaviour, no mutant.
3. **Neither is possible** → Needs-you: the owner decides, and may waive it.

Never kill a mutant by asserting an internal call (`mock.assert_called_with(...)` on your own helper), by pinning a message's wording that no user relies on, or by moving or rewriting the line so the check no longer sees it. The entry's `hint` says the same.

`N more caught only by the whole suite` in the R3 note is not a failure: those lines are tested, but only by a test that starts the program or imports it another way. Prefer adding a test that calls the function.

## Rounds

An `adapter-fix` entry counts no fix round here: its repair is commits on another branch, with no `mech:` line.

Fix rounds per id = commits on this branch whose body names it:

`git log --fixed-strings --grep="mech: <id>" --format=%h <base>..HEAD | wc -l`

`<base>` = the envelope's `base` SHA. No envelope base → merge-base of the PR base branch and HEAD.

Each fix commit for an id carries the body line `mech: <id>`.

- Count ≥ 2 and the id still fails → **3rd round**: no fix. Needs-you block: `Blocker: <id> unresolved after 2 fix rounds`, with the entry, its file, and the decision needed.
- Else → fix; commit with `mech: <id>` in the body.
