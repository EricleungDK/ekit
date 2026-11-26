# ekit

**Make coding agents prove their work before they say "done".**

Coding agents finish fast, and some of that speed comes from skipping a failing test, editing an expected value until it matches, or reporting "all tests pass" from memory. ekit is a plugin that closes those routes:

- **In the session**: skills and hooks that make the agent classify a red test before touching code, try the result the way a user would, and end with a report where every claim has a command and its output next to it.
- **On the pull request**: a GitHub workflow that checks the diff mechanically. Did a test get deleted or weakened? Does a new test actually fail without the fix? Would the tests notice if the changed code were wrong?

Works in Claude Code, Codex, GitHub Copilot, and any agent that reads [Agent Skills](https://skills.sh). The PR checks support any language the adapter format, or a parser command, can describe: Rust, Python and TypeScript/JavaScript are built in, and any other such language gets an adapter file that `/ekit:ci-doctor` generates and proves for your repo, with R3 where a mutation tool exists ([adding a language](docs/adding-a-language.md)).

## What it looks like

An agent "fixes" a divide-by-zero bug by returning 0, deletes the test that expected an error, and skips another. Run on that branch, the checks give this (real output of the local `mech-review.py all`, as the PR comment renders it; SHA shortened, one row left out; `all` leaves R3 to CI):

> ## mech-review
>
> **fail bc7e140 (4 fail, 1 confirm; ran: R1 R2 R4; skipped: R3)**
>
> | id | severity | file:line | problem | forbidden |
> |---|---|---|---|---|
> | R2-55dee746 | fail | tests/test_calc.py:10 | test fn `test_div_rejects_zero` removed | deleting or renaming a test to hide a failure |
> | R2-d15476fc | fail | tests/test_calc.py:11 | test `test_div_halves` marked skipped (skip or xfail) | #[ignore] / skip / xfail / only on a test |
> | R4-4547185d | fail | tests/test_calc.py:11 | test `test_div_halves` did not run at head | retrying a test until it passes |
> | R2-3c9ea7bc | confirm | tests/test_calc.py:12 | expected value changed in `test_div_halves`: was 2, now 2.5 | editing an expected value to match the code's current output |
>
> **To waive** (people with write access): copy a line, replace `<why this is OK>` with your reason, post it as a PR comment.
> ```
> /mech-waive R2-55dee746 <why this is OK>
> ```

The same result is attached as JSON, which your agent reads when it next works on the PR (in an `/ekit:orchestrate-agent` run, the orchestrator sends the fail entries straight back to it): each entry carries the fix that is wanted and the shortcut that is not allowed.

In the session, work ends with a report like this instead of "done!":

```
## Finish: done
| Criterion                         | Status          | Evidence                                             |
|-----------------------------------|-----------------|------------------------------------------------------|
| div(1, 0) raises ZeroDivisionError | ✅ verified     | `pytest tests/test_calc.py -q` → exit 0, 3 passed    |
| CLI prints the error, exits 2     | ✅ verified     | `RUN run cli-div-zero` → PASS, transcript in .git/ekit |
| Works on Windows                  | ⚠️ not verified | no Windows host here; run: `pytest -q` on Windows    |
Env: sandboxed
Verification debt: Windows run → no host → CI or user machine
```

A row without evidence cannot be marked ✅, and one ⚠️ row turns "done" into "done except".

## Install

Pick **one** route per agent; installing two gives you every skill twice.

<details open>
<summary><b>Claude Code</b> (skills + hooks)</summary>

```bash
claude plugin marketplace add EricleungDK/ekit
claude plugin install ekit@ekit --scope user
```

Update: `claude plugin update ekit@ekit`.

</details>

<details>
<summary><b>Claude Code on the web</b> (claude.ai/code)</summary>

Cloud sessions load no plugins. Add to the environment's setup script:

```bash
curl -fsSL https://raw.githubusercontent.com/EricleungDK/ekit/main/cloud/setup.sh | bash
```

It installs skills + hooks into each repo's `.claude/`, hidden from `git status` (nothing to commit), and fetches the kit again on each setup. To stay on released versions instead of `main`, pin both the script and what it fetches: `curl -fsSL https://raw.githubusercontent.com/EricleungDK/ekit/v0/cloud/setup.sh | EKIT_REF=v0 bash` (from release 0.3.0 on). No repo found at setup time: `bash ~/.ekit/cloud/install.sh <repo>`.

</details>

<details>
<summary><b>Codex</b></summary>

```bash
codex plugin marketplace add EricleungDK/ekit
codex plugin add ekit@ekit
```

Updates at startup when `version` in `plugin.json` changes.

</details>

<details>
<summary><b>GitHub Copilot</b> (CLI and VS Code)</summary>

```bash
copilot plugin marketplace add EricleungDK/ekit
copilot plugin install ekit@ekit
```

Auto-update, once, in `~/.copilot/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "ekit": { "source": { "source": "github", "repo": "EricleungDK/ekit" }, "autoUpdate": true }
  }
}
```

VS Code: **Chat: Install Plugin From Source** → `https://github.com/EricleungDK/ekit`.

</details>

<details>
<summary><b>Any other agent</b> (Cursor, Gemini CLI, OpenCode, Windsurf, Amp, …)</summary>

```bash
npx skills@latest add EricleungDK/ekit -a <agent>   # omit -a to choose
```

Copies editable skill files. Update: `npx skills@latest update`.

</details>

### Setup per OS

The plugin needs Python 3.9 or newer (standard library only) and Git, on macOS, Windows or Linux. No bash and no WSL:
each hook starts the first of `python3`, `py -3` and `python` that is 3.9+, in whichever shell Claude Code gives it,
and one message names what is missing when none is.

**macOS**

| Need | Install | Check |
|---|---|---|
| Python 3.9+ | `brew install python` (or python.org) | `python3 --version` |
| Git | `xcode-select --install` (or `brew install git`) | `git --version` |
| Hook shell | `sh`, built in | nothing to do |
| Optional tools preflight names | `brew install jq ripgrep gh` | `python3 -I <kit>/scripts/preflight.py` |

**Windows**

| Need | Install | Check |
|---|---|---|
| Python 3.9+ | `winget install Python.Python.3.13` (or python.org: it adds `py`) | `py -3 --version` |
| Git | `winget install Git.Git` (Git for Windows; its Git Bash is optional) | `git --version` |
| Hook shell | Git Bash when installed, else PowerShell: both work | nothing to do |
| Optional tools preflight names | `winget install jqlang.jq BurntSushi.ripgrep.MSVC GitHub.cli` | `py -3 -I <kit>/scripts/preflight.py` |

The Microsoft Store's `python3` stub, when it is all there is, fails the version check and the launcher moves on to
`py -3`, then `python`. WSL works too, as Linux.

**Linux** (`apt` on Debian and Ubuntu; `dnf` on Fedora and RHEL; other distributions: their package manager)

| Need | Install | Check |
|---|---|---|
| Python 3.9+ | `sudo apt install python3` / `sudo dnf install python3` | `python3 --version` |
| Git | `sudo apt install git` / `sudo dnf install git` | `git --version` |
| Hook shell | `sh`, built in | nothing to do |
| Optional tools preflight names | `sudo apt install jq ripgrep gh` / `sudo dnf install jq ripgrep gh` | `python3 -I <kit>/scripts/preflight.py` |

`<kit>` is the plugin's folder, named by the `[ekit] Scenario runner:` line at session start. Preflight prints the OS,
then one line per missing tool with this OS's install command. Scenarios written as `run.py` (taste-it's default) need only that Python; a `run.sh` needs bash
(Git Bash on Windows) and a `run.ps1` PowerShell, and reads `NOT-RUN … (env)` on a machine without it.

### Hooks and scripts outside Claude Code

The hooks (preflight, failure hints, task verification, finish gate) run in Claude Code. Elsewhere, skills still work: those that need the kit's scripts use `~/.ekit`, cloned once:

```bash
git clone --depth 1 https://github.com/EricleungDK/ekit ~/.ekit
```

`orchestrate-agent` and `taste-it` hand work to subagents, so they need a harness that has them (Claude Code does); the other skills are harness-neutral.

## Quick start

1. Install (above) and start a session. From now on a red test gets classified before the agent edits code.
2. Give it a task through the orchestrator: `/ekit:orchestrate-agent fix #12`. It writes an acceptance checklist, delegates, reviews, and may not stop until the finish report is given.
3. Put the checks on your PRs: `/ekit:ci-doctor`. It detects your stack, writes the workflow, and opens a PR for you to merge. A language with no built-in stack gets a generated adapter file first: [adding a language](docs/adding-a-language.md).

## Words used here

| Term | Meaning |
|---|---|
| **mech-review** | The mechanical PR checks. Same input, same output; no model involved. |
| **R0 adapter proof** | The stack's adapter catches a fixed list of cheats and finds every test the runner lists. A failure goes to a repair PR, never to the PR's agent. |
| **R1 red-first** | At least one new or changed test fails on the base branch's code. Proves the test can catch the change. Agent branches only. |
| **R2 test-diff guard** | No test deleted, skipped or weakened; no unreasoned lint suppression; no edit to protected paths. |
| **R3 mutation** | The changed lines are deliberately broken, one small change at a time; a test must notice each. Needs a mutation tool: a language without one reads `n/a`. |
| **R4 determinism** | Each new or changed test passes 5 times in a row. |
| **adapter file** | `.ekit/adapters/<name>.toml`: a language described as data (tests, asserts, skips, runner, mutation tool), for a stack that is not built in. |
| **stack plan** | `.ekit/stack-plan.toml`: the repo's stacks, planned, current or retiring. A manifest no stack covers fails the PR. |
| **entry** | One finding. `fail` blocks, `confirm` asks a reviewer, `waived` was let through by a person. |
| **waiver** | A `/mech-waive <id> <reason>` PR comment from a person with write access. Agents cannot waive. |
| **scenario** | A script in `.ekit/scenarios/` that installs your deliverable and uses it like a user would. |
| **taste** | Running the scenarios through a subagent that has not seen the code. |
| **verify command** | The one command that runs a unit's lint and tests, or the full suite for the whole job. Agreed in the checklist, then declared for the session; it stays once declared. |
| **finish report** | The end-of-work table: each criterion with fresh evidence. |
| **Needs-you block** | The exact command or decision the agent is waiting on you for. |
| **verification debt** | Every check that could not run here, with where to run it. |

## Skills

| Skill | Use |
|---|---|
| [`failure-triage`](skills/failure-triage/SKILL.md) | A test, build or CI job goes red: classify it (sandbox/env, stale, flaky, unowned, real bug) before editing code. Reads mech-review JSON directly. |
| [`taste-it`](skills/taste-it/SKILL.md) | Verify a deliverable by using it: black-box taster, `.ekit/scenarios/` regression suite, fix/human verdicts. A bug from use is checked with a scenario before any fix. A new app's features are seeded as scenarios from the user's stories before the code (only the approved wording; each must fail until its feature works). |
| [`finish`](skills/finish/SKILL.md) | End-of-work report: done (evidence per criterion) or blocked (Needs-you block). With seeded scenarios, the `N of M features working` line copied from the runner. |
| [`mistake-to-check`](skills/mistake-to-check/SKILL.md) | An agent mistake should become a check: filter it (decidable, a class, visible at check time, worth its upkeep), make it impossible where it can, else route it to a linter rule, a co-change rule, a gate or an environment fix; or one line saying why none. Also promotes and removes the rules it made. |
| [`ci-doctor`](skills/ci-doctor/SKILL.md) | Set up or repair a repo's mech-review CI; ends in a PR a person merges. |
| [`orchestrate-agent`](skills/orchestrate-agent/SKILL.md) | `/ekit:orchestrate-agent`: divide a task, delegate to subagents, verify acceptance. User-invoked only. |

## Hooks (Claude Code)

| Hook | Does |
|---|---|
| `SessionStart` | Preflight warnings (missing tools, sandbox limits) + three working rules into context; prints the scenario runner path. In a repo with a stack plan, the drift check at HEAD (git only): each manifest no stack covers and each planned, retiring or vanished stack's message; nothing when clean. |
| `UserPromptSubmit` | Prompt starts with `/ekit:orchestrate-agent` → arms the finish gate for the session. |
| `PostToolUseFailure` | Known Bash failure signatures (sandbox, port in use, missing tool, red test) → one line with the check that settles it. |
| `TaskCreated`, `TaskCompleted` | Sessions that have a task list (Claude Code leaves the task tools out on newer models unless `CLAUDE_CODE_ENABLE_TODO_TOOLS=1`). A task whose description has a ``Verify: `<command>` `` line completes only after that command passed, through `task-verify.py run`, on the files as they are now. The hook runs nothing itself: the agent runs the command, under the session's permission rules. Tasks without the line are not gated. |
| `Stop` | Orchestrate sessions only. If the files changed since the session started, the stop is blocked once per set of file contents, asking for the finish report (`## Finish: done` or `## Finish: blocked`) as the last message; in repos with `.ekit/scenarios/`, on each stop until the scenarios pass for the current files. A `## Finish: done` report is taken only when every verify command of the session passed on the current files (declared with `task-verify.py declare`, or carried by a task), the whole job's full-suite command among them; a session that declared none is not done. `## Finish: blocked` needs neither. The stop that directly follows a block is let through, so a session cannot loop on the gate, with one exception: a `## Finish: done` report given again is checked again, and blocked while a check is red. `## Finish: blocked` always gets out. Committing does not invalidate a pass. Subagents are not gated, and a stop while a subagent is still running is a wait for its report: it passes and asks nothing. |

Outside orchestrate sessions the Stop gate is silent: the skills still apply, nothing blocks.

## mech-review CI

A reusable GitHub workflow. It posts one comment per PR and sets one check, `mech-review report`:

| Job | Rule |
|---|---|
| `guard` | R2: tests not weakened or deleted. Reads the diff only; runs no PR code. |
| `red-first` | R1: new tests fail before the fix. R4: results are deterministic. |
| `mutants` | R3: mutation testing on the changed lines (cargo-mutants, mutmut, Stryker, or the tool an adapter file declares; `n/a` with none). Runs only when production code changed. |

- **Stacks**: any language the adapter format, or a parser command, can describe. Rust, Python and TypeScript/JavaScript are built in; any other language through an adapter file that ci-doctor generates and proves ([adding a language](docs/adding-a-language.md)). R3 reads `n/a` for a language whose adapter declares no mutation tool.
- **Agent branches**: R1 runs on branches starting with `agent/`, `claude/`, `codex/`, `copilot/` or `cursor/` (configurable; `*` for all).
- **Waivers**: a person with write access can let one entry through with `/mech-waive <id> <reason>`; the comment offers the line ready to copy, and the waiver shows with their name. A placeholder reason or an edited comment does not waive. With the [re-run caller](docs/mech-review-ci.md#waiver-re-run), the check updates on its own. Nothing in the PR itself can waive.
- **Forks**: on a read-only token the result goes to the job summary and the check still passes or fails on it.

Adopt with `/ekit:ci-doctor`, or by hand: [docs/mech-review-ci.md](docs/mech-review-ci.md). A language with no built-in stack: [docs/adding-a-language.md](docs/adding-a-language.md). The testing rules behind the checks: [docs/testing-standard.md](docs/testing-standard.md).

<details>
<summary>Scripts</summary>

| Script | Does |
|---|---|
| `scripts/mech-review.py` | Review engine: `r2`, `red`, `all`, `baseline`, `mutants`, `merge`, `plan`, `doctor`, `resolve`, `r0`, `drift`, `parser-install`. Contract JSON; exit 0 pass / 1 fail / 2 usage. `--help` for flags. |
| `scripts/scenarios.py` | Scenario runner: `run [ID]`, `check`, `can-fail REF`, `seeded ID`, `tree-hash`. Each scenario has one run file: `run.py` (this Python), `run.sh` (bash) or `run.ps1` (PowerShell). Files a scenario saves to `$EKIT_ARTIFACT_DIR` (screenshots) are kept beside its transcript. A `- feature: <name>` line in SCENARIO.md marks a seeded scenario: a full `run` and a fresh `check` end with `N of M features working`; `seeded ID` reads one that already passes `CHECKS NOTHING YET`. |
| `scripts/task-verify.py` | `declare -- CMD`: makes CMD a verify command of the session. `run -- CMD`: runs it and records the result for the current files. `check SESSION`: the Stop gate's question. `--hook`: the task hook. |
| `scripts/mech-comment.py` | Merges job results, applies waivers, renders and posts the PR comment. Exit 0 pass / 1 fail / 3 API error / 4 no result. |
| `scripts/r3-local.py` | The workflow's R3 jobs locally, pinned as CI: `--base REF --stack S` plus the caller's inputs. Prints the merged R3. Exit 0 / 1 fail or unconfirmed survivor / 2 setup or usage. |
| `scripts/mech-summary.py` | `<run-id \| PR>`: a mech-review run's artifacts in a few lines (checks, shard notes, fail entries by file). `--dir` for downloaded artifacts. |
| `scripts/orch-status.py` | `<worktree>...`: commits ahead of the pushed branch, dirty files, live test/mutation processes, CI counts. |
| `scripts/verified-commit.py` | `[--allow-behind] [--expect SHA] RESULT WORKTREE`: the mech-review result's head is the review request's head (`--expect`), the worktree's head and the pushed tip. Exit 0 same commit / 1 another commit (both named) / 2 no answer (reason given). |
| `scripts/mech-rerun.py` | `--pr N`: re-runs the PR head's finished `mech-review report` job, so a waiver comment takes effect (the `mech-waive` workflow). Exit 0 / 2 usage / 3 API error. |

</details>

## Development

The suites are bash (`tests/*.test.sh`) plus Python unittest (`tests/py`), so contributors also need bash and `jq`.
The same commands run on each OS:

```bash
bash tests/run.sh                          # everything
python3 -m unittest discover -s tests/py   # the python unit tests alone (Windows: py -3 -m unittest ...)
```

| OS | Setup | Notes |
|---|---|---|
| macOS | `brew install python jq` | stock bash 3.2 is enough; no `sha1sum` or `timeout` needed |
| Windows | `winget install Git.Git Python.Python.3.13 jqlang.jq`, then run the suites in Git Bash | Developer Mode (Settings → System → For developers) for the symlink tests: without it they skip, naming the refusal |
| Linux | `sudo apt install python3 jq git` (Debian, Ubuntu) / `sudo dnf install python3 jq git` (Fedora, RHEL) | nothing else |

A fresh clone has LF files on every OS (`.gitattributes`). WSL is an alternative on Windows: clone inside WSL and run
the suites there as on Linux. The Python suite runs natively on Windows too (`py -3 -m unittest discover -s tests/py`),
in PowerShell or Git Bash. `python tests/windows-smoke.py` (run by `tests/run.sh` on Windows) checks ekit in the real shells of a Windows machine
(every hook in plain PowerShell with no Git Bash on PATH, verify commands in their own shells, a scenario timeout);
the unit tests fake those shells and run on every OS.

ekit runs its own checks on its own PRs (`.github/workflows/mech-review-self.yml`, python stack): a change to `scripts/` needs a test in `tests/py` that fails without it. `python3 scripts/ci-local.py --base origin/main` runs those checks here (needs `uv`; POSIX or WSL): see [the CI doc](docs/mech-review-ci.md#developer-machine).

Skill evals (kit dev only):

```bash
evals/run.sh                     # all cases; options go to `claude plugin eval`, e.g. --case 'triage-*' -j 4
```

On Linux the eval sandbox needs `bubblewrap` + `socat` and no symlinks inside `~/.docker`. On macOS `evals/run.sh` puts the real `git` first on `PATH`: the `/usr/bin/git` shim cannot run inside the sandbox. On both, the sandbox blocks writes under `.git/worktrees`, where the scenario runner and mech-review's trial make their scratch worktrees: graders for those cases check the commands run and what the agent says about them, not a runner PASS. `.git/ekit` stays writable, so verify commands are declared and recorded as in a real session.

Changes per release: [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
