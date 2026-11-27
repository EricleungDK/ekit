# Repair mode

For an `adapter-fix` entry: the stack plan or an adapter file needs a change. The PR's own agent never makes it: an agent that can tune its checker can tune it until its own PR passes. The repair runs apart from that agent and ends in an adapter-fix PR of its own. `DOCTOR`, `<py>` and `<kit>` are SKILL.md's; `MR` = `<py> -I <kit>/scripts/mech-review.py`. Format of every file named here: `<kit>/docs/mech-review-ci.md`, sections Repair mode, Stack plan, Adapter file, R0 adapter proof (and Runtime half).

## 1. Read the entry

Take the entry from the PR's mech-review result (sticky comment or JSON) or doctor's `repair` entries; keep the PR's branch, base and head SHA for the PR body. Its key or problem names the source, and the source names the edit:

| Entry | What failed | Edit |
|---|---|---|
| `R0`, `static:<cases>` | the named cheats or controls of the static half | the adapter's tables those cases read (the categories of setup.md's Cheat list) |
| `R0`, `runtime:run:<cases>` | the census or a runner control: the adapter misreads the runner | `[run.list]` (census), `[run.outcome]` or `[run]` (controls) |
| `R0`, `runtime:r3:<cases>` | the R3 control | `[mutation.tool]` |
| `D` | manifests no plan entry covers | the plan: an entry per uncovered folder, or the folder in `ignore` |
| `CI`, the adapter's parser failed | the `[parser]` command or its install | `[parser]` |
| `CI` or doctor's, the plan or an adapter file does not read | the named entry and field | that file |
| doctor's `own-adapter` | an adapter file of the repo's finds no project | that file's `manifests`, or setup mode beside it (the owner decides: ask) |
| doctor's `adapter-file` `confirm` alone | nothing yet: doctor does not trial an adapter file | none: run step 4 on HEAD; all pass → nothing to repair, go on with SKILL.md step 2 |

## 2. Branch

`git fetch`, then a new branch from the PR's base branch (`origin/<base>`), never the PR's branch or one cut from it: `<agent prefix>adapter-fix-<entry id>`. Commits carry no `mech:` body line: failure-triage counts the coding agent's fix rounds by that line on its branch, and a repair round is none of them. Put `adapter-fix: <entry id>` in the body instead.

## 3. Edit

- **Failed R0**: regenerate only the failing part, for this repo. A runtime case: read the runner's real output for every control the entry names, `no-such-test` (a run where no test matches) included, and write the pattern for what the runner prints now. Run each control here where the toolchain is installed, else take the output the person or the hand-off gives you: CI's logs hold none of it (the entry quotes each control's first line only). With neither, stop blocked (step 4's report), naming the output you need. A static case: the repo's test files and the categories of setup.md's Cheat list. A cheat fixture changes only when it is not valid code in the language; the report says which and why.
- **Drift**: for each uncovered folder:
  - The team's code: a plan entry for its folder (its format: SKILL.md's Stack plan; its proof: step 4 here), `planned`, since its manifest arrives with the PR and is not on this branch. Its adapter is a built-in that lists the manifest, else an adapter file that setup.md's steps Detect through Prove it with R0 generate and prove (`.ekit/adapters/<name>.toml` and its fixtures). R0 compares a folder new to the plan with the defaults (linux, the default limits, no mutation tool): a built-in keeps them and needs no person; an adapter file that declares a `[mutation.tool]`, or a target OS other than linux, is a person's call at step 4's A person's call.
  - Samples, templates, vendored or generated code: the folder in `ignore`.
  - The branch adds no manifest.
- **A plan or adapter file that does not read**: fix the named entry and field.

## 4. Prove it

The proof is every part, for the edited copy, in the four stages below. Budget: 5 rounds, as setup.md's Prove it with R0 counts them (one revision and one run of the proof; a failing case of any part counts the same). A limit the CI doc names replaces no round (setup.md, Prove it with R0): draft each revision, run the proof on it, and report the cases that still fail by name; a format gap ends the rounds, as it does there.

- **Working tree.** The parts of setup.md's Prove it with R0: Static half (`--adapter` the edited file), Census of the repo's own tests, Runtime half where the toolchain is installed and this machine is the target OS (`red --r0`, `mutants --r0`; else the report's "not run here: <why>", and for a runtime entry each changed pattern checked against step 3's output of every control the entry names, the one that runs no test included), and for a new adapter file The cheat list (written as setup.md's Cheat list says).
- **As CI reads it**, in a scratch clone (never a branch of the repo): commit the edit on top of `origin/<base>`, then `MR r0 --repo <scratch> --base HEAD --head HEAD --stack <name> --project-dir <folder>` (`pass`) for each adapter file the repair touched, and `MR drift --repo <scratch> --base origin/<base> --head HEAD --format text` (`pass`, no fail entry).
- **The PR on the fix**, in the same scratch clone: merge the PR's head onto that commit there; `drift --base <commit> --head <merge>` and, for an R0 repair, `r0 --base <commit> --head <merge> --stack <name> --project-dir <folder>` both pass.
- **A person's call**: `MR r0 --repo <scratch> --base origin/<base> --head <commit> --stack <name> --project-dir <folder>` (`<name>` the base plan's stack). Its `needs-human` entries are R0's editing rules: a loosened limit, a changed target OS, a folder added to `ignore`, a changed `[parser]` or `[mutation.tool]`. This run proves the base's copy: for a static R0 repair it also gives the base's `adapter-fix` entry, expected (step 5); for a runtime repair its static half passes.

Every stage passes → commit the edit on the repair branch (step 2), the commit the clone proved. A `needs-human` entry at A person's call → commit it too, then stop before the PR: a Needs-you block (finish) with `Decide:` quoting each entry, the proof, and the PR body ready to open on a yes.

Budget spent or a format gap, with a case failing, unproven or missed: stop. Commit nothing in the repo, open no PR, and report blocked via finish: the rounds run of the budget (`3 of 5`), each failed case as `r0` or `r2` names it, the gap quoted, the cheats missed, the draft's path, what would unblock it, and that the entry now needs a person. This report carries no PR body. A person's `/mech-waive` on the PR's `R0` or `D` entry is the emergency exit for an urgent PR (a `CI` entry has none).

## 5. Open the adapter-fix PR

Push and open it against the PR's base branch. Its body:

- The entry (id, problem) and the PR it came from (link, head SHA); the files changed and why.
- Proof report: as in setup.md's Open the setup PR (the static half `N of N cases`, the census `N of N tests`, the runtime half's result or not run here and why, the cheat list for a new adapter), drift, and The PR on the fix.
- How its CI judges it: the checks read the adapter and the plan from the base branch. A drift repair edits only the plan, adds no manifest, and is judged by its own plan, so `D` passes. An R0 repair's CI proves the base branch's copy, so it reads the PR's R0 fail until it merges: it needs the owner's `/mech-waive <id> <reason>` on that R0 entry here, after reading the proof above, and then the merge. Say so plainly: this deviates from #24's "needs a person only if it loosens a limit or changes a target OS", until a follow-up proves an adapter-only PR at its head (`<kit>/docs/mech-review-ci.md`, Repair mode). A new adapter file has no base copy for its CI to prove: the proof above is its proof.
- After the merge: the PR's checks run again on the fixed adapter at its next run (a push, or close and reopen it; re-running an old run keeps its old base). A drift repair's `planned` entry then gives that PR drift's note `set its status to current`, and that PR turns the entry `current`: that one-word status change is the only plan edit a coding PR makes, judged by R0's editing rules like any plan edit. Every other plan or adapter edit stays ci-doctor's.

Report the PR URL via finish. Stopped before the PR (a person's call, no remote, asked to) → the report carries the PR body.
