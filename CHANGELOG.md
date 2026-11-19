# Changelog

Releases are tags `vX.Y.Z` that match `version` in `.claude-plugin/plugin.json`; each one moves the floating `v0` tag that CI callers follow.

## Unreleased

### Changed

- **R3 mutant cap and risk order** (`max-mutants` input, `--max-mutants`, default 40; #26): rust and python test at most `max-mutants` mutants per PR, riskiest first (branch conditions, then returns and boolean literals, then arithmetic, then the rest, string and argument mutants last; a fixed tie order, so every run picks the same set). The rest are untested and R3 reads `partial (tested/total)`, never `pass`. A rust run that tests mutants outside the pick (an `examine_re` in `.cargo/mutants.toml` is ORed with `--re`) is `n/a (env)`. ts (Stryker) does not apply it: Stryker lists no mutant before its run.
- **R3 shard count** (rust): `min(4, mutants, ceil(estimated minutes / (budget / 2)))`, estimated from the baseline's measured build and test time, so a small PR gets one shard. Past the cap the mutants are dealt round-robin in risk order. Python shards are dealt the same way (each lists every changed file); python and ts keep one shard per changed file, at most 4 (no baseline is measured for them).

### Fixed

- **R3 (python)**: a mutant the budget never reached, including one still waiting for its whole-suite retry, read MISSED, so a PR with real tests could read as many failures. It is now untested: R3 is `partial`, with no MISSED entry. A mutant that ran and survived its retry is still MISSED.
- **`--mutation-budget nan` / `inf`**: crashed `baseline` with a traceback; now a usage error (exit 2).

## 0.5.0

### Added

- **`stack: auto`** (`mech-review.yml`, `scripts/mech-review.py resolve`): the reusable workflow's `stack` input defaults to `auto`. A new `stack` job, git only, finds the one project from the tracked manifests with doctor's detection, at the PR base and head, and every later job (each toolchain `if:` included) reads the stack from its outputs through `env` or `if:`. `project-dir` left at `.` takes the dir found; a dir the caller set is never replaced. Several projects, none, or a head that finds a different project than its base: no check runs and the comment names the projects found and the inputs to set. `rust`, `python` and `ts` work as before. doctor no longer asks for `stack` or `project-dir` when `auto` finds the same.
- **Waiver re-run** (`mech-waive.yml`, `scripts/mech-rerun.py`): a second caller, on `issue_comment`, re-runs the PR head's `mech-review report` job when a person posts, edits or deletes a `/mech-waive` comment, so the check updates in about a minute with no trip to Actions. It runs only for comments from `OWNER`, `MEMBER` or `COLLABORATOR`, never for a bot or the sticky comment, and never runs PR code. ci-doctor writes the caller.
- **Ready-made waiver lines**: the sticky comment shows, under each `fail` entry, the line to post (`/mech-waive <id> <why this is OK>`), plus one block for all fail entries when there are several.

### Changed

- **`stack` default**: was `rust`. A caller that leaves `stack` out now gets the stack its repo has; a repo with several projects (or none) and no `stack` input now fails with a message instead of running as rust. Set `stack` (and `project-dir`) to keep the old behaviour.
- **Waivers**: a reason still reading `<why this is OK>` (or any reason wholly in `<…>`) does not waive, and a comment edited after posting does not waive: anyone with write access can edit another person's comment while the author shown stays the same. The sticky comment names each ignored waiver and why; post a new comment instead.

### Fixed

- **R3 (python)**: a repo whose tests read tracked files outside the sources and `tests/` (`docs/`, `config/`, `scripts/`, `README.md`) failed R3 with `baseline tests fail at head: mutants not run`, because mutmut 3.8.1 copies only the sources, `tests/` and a few root files into its `mutants/` sandbox (#7). The generated `[tool.mutmut]` now sets `also_copy` to the project dir's other git-tracked top-level entries. Source entries, `mutants/`, untracked files and mutmut's own defaults are never listed, nor is an entry holding a symlink mutmut cannot copy. Root test config (`pytest.ini`, `tox.ini`, `conftest.py`) now applies in R3 as in R1. `source_paths` and `only_mutate` stay valid TOML for names outside the BMP.
- **doctor (python)**: the trial runs the suite once more inside a copy built the way R3's mutmut sandbox is. A suite that passes in the checkout and fails there gives an `env` entry naming the paths missing from the copy, and any link that keeps a top-level entry out of it, never `ok`. A dangling or looping link under `tests/`, which stops or hangs mutmut's copy, is named without copying. The trial gains `sandbox: pass|fail|skipped`. Known limits: with `project-dir` in a subfolder, files above it are not copied; a top-level entry holding a link mutmut cannot copy is left out whole.

## 0.4.0

### Added

- **Scenario artifacts**: each scenario gets `EKIT_ARTIFACT_DIR`. Files it saves there, screenshots first, are kept beside its transcript in `<git dir>/ekit/<tree>/<id>/` and listed under `artifacts` in results.json; a scenario that saves nothing leaves no dir. taste-it's Web UI driver saves a screenshot of each asserted state, and the finish report cites the paths: in a scenario row, and in the Needs-you block of a 👤 visual check. The assertion stays on text: a screenshot is the reviewer's proof, never the pass. New eval case `finish-ui-screenshot`: the agent reports a scenario PASS with its screenshot, and hands the taste criterion to the user with that screenshot.
- **Verify commands** (`scripts/task-verify.py`): a session names the commands its work is checked with, and they stay once named. `declare -- <command>` adds one (the session is `$CLAUDE_CODE_SESSION_ID`, set by Claude Code for Bash commands). `run -- <command>` runs it and records the exit code against the tree hash, in the repo's git dir. The hooks only read those records: the commands run under the session's permission rules and sandbox, never from a hook. A sandbox that keeps the git dir read-only gets exit 3 and the same call outside the sandbox as next step.
- **Task hook** (`TaskCreated`, `TaskCompleted`), for sessions that have a task list: a task whose description carries a ``Verify: `<command>` `` line cannot be marked completed until that command passed on the files as they are now. The command is kept from the first time the task is seen. A pass in a linked worktree counts from the main checkout while that worktree's files are unchanged. Tasks without the line are not gated. In agent teams, where a teammate's turn end fires the hook, the block is given once per set of file contents.
- **orchestrate-agent**: each unit gets a verify command (lint and typecheck in front, then its tests), agreed with the checklist and declared before its agent starts. The full suite is declared for the whole job.
- **Evals**: `evals/run.sh` runs the suite, on macOS too (the `git` shim does not work inside the eval sandbox). New case `orchestrate-verify-declare`.
- **taste-it**: a bug from use (a user's report, one met while using the deliverable, or one handed over by failure-triage) becomes a scenario before any fix. A `FAIL` on the unfixed code is the proof that the bug is real; a `PASS` means not reproduced: no code changes, and the scenario is not kept. failure-triage hands a real bug over when a user would hit the symptom and no scenario covers it: the symptom only, never the cause. New eval case `taste-act-bug-report`.

### Changed

- **finish**: the report's `Env:` line is the output of `preflight.sh --env`, a probe of what the shell can do (write outside the project, bind a port). Reports said "sandboxed" in sessions that had no sandbox: the skill asked for the word and gave no way to know.
- **finish**: which report to give is decided by what is left. Work the agent can still do comes first; everything done with only the user's part left is `done except`; `blocked` is for work that cannot go on. With every command green and one item needing the owner, one run reported `blocked` and its twin `done except`.
- **Finish gate**: `## Finish: done` now needs every verify command of the session green on the current files (`task-verify.py check`). A unit's pass from before a later edit does not count, and an orchestrate session with no verify command cannot report done: the block gives the `declare` call. `## Finish: blocked` is unchanged, and no other stop is checked.
- **Finish gate**: a `## Finish: done` report repeated right after a block is checked again. The gate used to let every stop after a block through (Claude Code's `stop_hook_active`), so an agent that answered a block with the same report, having run nothing, got past red scenarios and red verify commands alike. A stop without a `done` report is still let through after a block.

## 0.3.1

### Changed

- **Finish gate**: a stop while a subagent is still running is a wait for its report, and is let through. The gate used to ask for the finish report then, when the work was not finished: the orchestrator had to refuse, or report early. It reads the Stop payload's `background_tasks`; only a running subagent counts, a background shell does not. On a Claude Code that sends no such list the gate asks as before.
- **orchestrate-agent**: the subagent brief is the whole implement flow (red to green in slices at the seams, typecheck and the test file each slice, the full suite once at the end), since an agent cannot load an implement skill reserved for the user. The checklist names a seam per outcome for the user to agree before dispatch, and the brief lets the agent load a TDD or bug-diagnosis skill its install lists.
- **orchestrate-agent**: a fix for a review finding is a new commit on top of the reviewed head. Rewriting reviewed commits (squash, amend, filter) is the user's call, pushed or not: after a rewrite the head that was reviewed is no longer the one verified.

### Fixed

- **orchestrate-agent**: the closing step now loads the finish skill and names the report's first line. It said "final report", and an orchestrator that never loaded the skill headed its report `## Final report: done`: the Stop gate did not take that for the finish report and blocked the stop.
- **orchestrate-agent**: a subagent's review request is the finish skill's report, with evidence per checklist item. The brief asked for the finish report in a closing line that orchestrators replaced with a free-form "Report:" sentence, so no subagent loaded the skill; the report is now a numbered task, and the template says its fixed text goes in as written.

## 0.3.0

First release under the name **ekit** (was `ek`). MIT licensed.

### Breaking

- **Renamed `ek` → `ekit`**: plugin `ekit@ekit`, skills `/ekit:*`, scenarios in `.ekit/scenarios/`, the kit clone used outside Claude Code in `~/.ekit`, hook state under `~/.cache/ekit` (or the plugin's data dir). Old `.ek/scenarios/` dirs, `EK_*` variables and `EricleungDK/ek/...@v0` workflow callers keep working.
- **Finish gate**: no longer fires on `SubagentStop`. It now asks for the finish report when the files differ from session start (committed work included) and the last message is not that report: once per set of file contents, where it used to ask once per set of uncommitted files. Scenarios that are not green still block every stop.
- **mech-review `agent-branch-prefix`** defaults to `agent/`, `claude/`, `codex/`, `copilot/`, `cursor/` (was `agent/`): R1 red-first now runs on branches it used to skip. Set the input to keep the old behaviour.

### Added

- **Waivers**: a person with write access lets one `fail` entry through with a `/mech-waive <id> <reason>` PR comment. The entry reads `waived` with their name and reason, and the check goes green when no unwaived fail is left. See [docs/mech-review-ci.md](docs/mech-review-ci.md#waivers).
- **Fork and Dependabot PRs**: the `report` job no longer fails because it cannot comment; the result goes to the job summary and the check follows the result.
- Install routes for Codex, GitHub Copilot and `npx skills`; `ci-doctor` skill; `mech-review.py doctor`.
- `cloud/setup.sh` takes `EKIT_REF` (pin a tag or commit) and `EKIT_REPO_URL` (a fork or mirror).
- Python unit tests in `tests/py`; ekit's own PRs now run mech-review on the python stack.

### Changed

- Python R3 no longer reports a line as untested when the only test that covers it starts the program as a subprocess or imports the file under another name. A mutant mutmut reports missed on a changed line is applied and run once against the whole suite; the note counts those (`N more caught only by the whole suite`).
- Every R3 MISSED hint now ends with what to do: assert observable behaviour, simplify away an equivalent mutant, or hand it to the owner; never pin internals. `failure-triage` has the same steps, and the CI doc records which mutations each stack's tool makes.
- `mech-review.py plan` prints `{"run": true|false}` and nothing else. Its `count` and `shards` were read by nothing: the baseline step sets the shard count. `--shards` is ignored by `plan`.

### Fixed

- A scenario PASS no longer goes stale when you commit: the tree hash is the files' content, not `HEAD` plus a diff.
- The tree hash could miss an edit that kept a file's size, made in the same second git last wrote its index: the finish gate and `scenarios.py check` then took an old PASS as fresh. It hashed from a copy of the index with a new mtime, which hid the edit from git's racy-index re-read.
- The scenario runner no longer crashes on a modified file that is not UTF-8.
- macOS: preflight reported `gh: not authed` and `docker: unusable` in every session (it needed `timeout`); the Playwright check only knew the Linux cache; a port-in-use failure crashed the failure hook (it needed `ss`).
- Preflight no longer warns about scenario driver tools (tmux, expect, curl, Playwright) that no scenario runs, or about a missing `.venv` when `pyproject.toml` only configures tools.
- Failure hints for sandbox/network signatures are a lead with the check that settles it, not "not a code bug".
- `taste-it` and `finish` no longer tell the agent to verify with editable or global installs.
- The python stack's R2 message for a skipped test said `#[ignore]`.
- Python R3 looked up every missed mutant of a changed file with `mutmut show`, one call each and unbounded: on a large file with little unit coverage the step ran for tens of minutes after the mutation budget. Mutants in functions the diff does not touch are now counted without a lookup.
- Python R3 ran every mutant of every changed file to judge the changed lines. It now lists mutmut's mutants first and runs only those in functions the diff touches, and reads each missed mutant's line from mutmut's files instead of one `mutmut show` call per mutant (about half a second each, over a thousand on a large diff).
- Python R3: when the tests fail before any mutant runs, the job log now shows the tail of mutmut's output (the failing test), as it already did for cargo-mutants.
- R1 failed every PR that added a test outside `test-paths`, such as a rust `#[cfg(test)]` unit test beside the code: the test is not on the base's code, so it read `cannot be proven red`, even next to a properly red test under `tests/`. Such tests are no longer run on the base; the R1 note counts them, and a PR with no test in a `test-paths` file gets one fail that says so.
- `mech-review.py` and `mech-comment.py` crashed on python 3.9 and 3.10 (`No module named 'tomllib'`), the python macOS ships. The engine needs 3.9 now; only a rust crate's `.cargo/mutants.toml` needs 3.11 to be read.
- Python R2 and R4 took any function named `test*` in a production file for a test: removing `test_connection()` from `src/app.py` read `test fn removed`, and changing it made R4 run it as a test. Outside `test-paths`, tests are now read only in files named `test_*.py`, `*_test.py` or `tests.py`.
- The failure hook called `grep -rn pytest docs/` a red test (any failing command that named a test runner did), and read a log line's clock time as the port in use (`port 34`).
- The scenario runner took a `run.sh` inside a scenario's `fixtures/` dir for a scenario of its own and failed it for a missing `SCENARIO.md`.
- `scenarios.py run <child>` gave the child an empty `EKIT_PARENT_DIR`, so a child that reuses its parent's fixtures passed in a full run and failed alone.
- The test suites no longer run under the machine's git config (commit signing, hooks, default branch), and two tests that failed as root or in a container without an init process now say why they could not run.

## 0.2.6 and earlier

See the [commit history](https://github.com/EricleungDK/ekit/commits/v0.2.6).
