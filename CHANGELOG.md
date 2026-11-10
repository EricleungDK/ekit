# Changelog

Releases are tags `vX.Y.Z` that match `version` in `.claude-plugin/plugin.json`; each one moves the floating `v0` tag that CI callers follow.

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

### Fixed

- A scenario PASS no longer goes stale when you commit: the tree hash is the files' content, not `HEAD` plus a diff.
- The scenario runner no longer crashes on a modified file that is not UTF-8.
- macOS: preflight reported `gh: not authed` and `docker: unusable` in every session (it needed `timeout`); the Playwright check only knew the Linux cache; a port-in-use failure crashed the failure hook (it needed `ss`).
- Preflight no longer warns about scenario driver tools (tmux, expect, curl, Playwright) that no scenario runs, or about a missing `.venv` when `pyproject.toml` only configures tools.
- Failure hints for sandbox/network signatures are a lead with the check that settles it, not "not a code bug".
- `taste-it` and `finish` no longer tell the agent to verify with editable or global installs.
- The python stack's R2 message for a skipped test said `#[ignore]`.
- Python R3 looked up every missed mutant of a changed file with `mutmut show`, one call each and unbounded: on a large file with little unit coverage the step ran for tens of minutes after the mutation budget. Mutants in functions the diff does not touch are now counted without a lookup.
- Python R3 ran every mutant of every changed file to judge the changed lines. It now lists mutmut's mutants first and runs only those in functions the diff touches, and reads each missed mutant's line from mutmut's files instead of one `mutmut show` call per mutant (about half a second each, over a thousand on a large diff).
- Python R3: when the tests fail before any mutant runs, the job log now shows the tail of mutmut's output (the failing test), as it already did for cargo-mutants.
- The test suites no longer run under the machine's git config (commit signing, hooks, default branch), and two tests that failed as root or in a container without an init process now say why they could not run.

## 0.2.6 and earlier

See the [commit history](https://github.com/EricleungDK/ekit/commits/v0.2.6).
