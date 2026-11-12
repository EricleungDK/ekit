# Changelog

Releases are tags `vX.Y.Z` that match `version` in `.claude-plugin/plugin.json`; each one moves the floating `v0` tag that CI callers follow.

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
