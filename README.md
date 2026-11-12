# ekit

**Make coding agents prove their work before they say "done".**

Coding agents finish fast, and some of that speed comes from skipping a failing test, editing an expected value until it matches, or reporting "all tests pass" from memory. ekit is a plugin that closes those routes:

- **In the session**: skills and hooks that make the agent classify a red test before touching code, try the result the way a user would, and end with a report where every claim has a command and its output next to it.
- **On the pull request**: a GitHub workflow that checks the diff mechanically. Did a test get deleted or weakened? Does a new test actually fail without the fix? Would the tests notice if the changed code were wrong?

Works in Claude Code, Codex, GitHub Copilot, and any agent that reads [Agent Skills](https://skills.sh). The PR checks support Rust, Python and TypeScript/JavaScript.

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
> A person with write access can let a `fail` entry through: comment `/mech-waive <id> <reason>` on this PR, then re-run this run's failed job (`report`).

The same result is attached as JSON, which the agent reads on its next turn: each entry carries the fix that is wanted and the shortcut that is not allowed.

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

Needs `git`, `bash` and `python3` 3.9 or newer (standard library only). Runs on Linux and macOS; on Windows use WSL.

### Hooks and scripts outside Claude Code

The hooks (preflight, failure hints, finish gate) run in Claude Code. Elsewhere, skills still work: those that need the kit's scripts use `~/.ekit`, cloned once:

```bash
git clone --depth 1 https://github.com/EricleungDK/ekit ~/.ekit
```

`orchestrate-agent` and `taste-it` hand work to subagents, so they need a harness that has them (Claude Code does); the other skills are harness-neutral.

## Quick start

1. Install (above) and start a session. From now on a red test gets classified before the agent edits code.
2. Give it a task through the orchestrator: `/ekit:orchestrate-agent fix #12`. It writes an acceptance checklist, delegates, reviews, and may not stop until the finish report is given.
3. Put the checks on your PRs: `/ekit:ci-doctor`. It detects your stack, writes the workflow, and opens a PR for you to merge.

## Words used here

| Term | Meaning |
|---|---|
| **mech-review** | The mechanical PR checks. Same input, same output; no model involved. |
| **R1 red-first** | At least one new or changed test fails on the base branch's code. Proves the test can catch the change. Agent branches only. |
| **R2 test-diff guard** | No test deleted, skipped or weakened; no unreasoned lint suppression; no edit to protected paths. |
| **R3 mutation** | The changed lines are deliberately broken, one small change at a time; a test must notice each. |
| **R4 determinism** | Each new or changed test passes 5 times in a row. |
| **entry** | One finding. `fail` blocks, `confirm` asks a reviewer, `waived` was let through by a person. |
| **waiver** | A `/mech-waive <id> <reason>` PR comment from a person with write access. Agents cannot waive. |
| **scenario** | A script in `.ekit/scenarios/` that installs your deliverable and uses it like a user would. |
| **taste** | Running the scenarios through a subagent that has not seen the code. |
| **finish report** | The end-of-work table: each criterion with fresh evidence. |
| **Needs-you block** | The exact command or decision the agent is waiting on you for. |
| **verification debt** | Every check that could not run here, with where to run it. |

## Skills

| Skill | Use |
|---|---|
| [`failure-triage`](skills/failure-triage/SKILL.md) | A test, build or CI job goes red: classify it (sandbox/env, stale, flaky, unowned, real bug) before editing code. Reads mech-review JSON directly. |
| [`taste-it`](skills/taste-it/SKILL.md) | Verify a deliverable by using it: black-box taster, `.ekit/scenarios/` regression suite, fix/human verdicts. |
| [`finish`](skills/finish/SKILL.md) | End-of-work report: done (evidence per criterion) or blocked (Needs-you block). |
| [`ci-doctor`](skills/ci-doctor/SKILL.md) | Set up or repair a repo's mech-review CI; ends in a PR a person merges. |
| [`orchestrate-agent`](skills/orchestrate-agent/SKILL.md) | `/ekit:orchestrate-agent`: divide a task, delegate to subagents, verify acceptance. User-invoked only. |

## Hooks (Claude Code)

| Hook | Does |
|---|---|
| `SessionStart` | Preflight warnings (missing tools, sandbox limits) + three working rules into context; prints the scenario runner path. |
| `UserPromptSubmit` | Prompt starts with `/ekit:orchestrate-agent` → arms the finish gate for the session. |
| `PostToolUseFailure` | Known Bash failure signatures (sandbox, port in use, missing tool, red test) → one line with the check that settles it. |
| `Stop` | Orchestrate sessions only. If the files changed since the session started, the stop is blocked once per set of file contents, asking for the finish report (`## Finish: done` or `## Finish: blocked`) as the last message; in repos with `.ekit/scenarios/`, on each stop until the scenarios pass for the current files. The stop that directly follows a block is always let through, so a session cannot loop on the gate. Committing does not invalidate a pass. Subagents are not gated, and a stop while a subagent is still running is a wait for its report: it passes and asks nothing. |

Outside orchestrate sessions the gate is silent: the skills still apply, nothing blocks.

## mech-review CI

A reusable GitHub workflow. It posts one comment per PR and sets one check, `mech-review report`:

| Job | Rule |
|---|---|
| `guard` | R2: tests not weakened or deleted. Reads the diff only; runs no PR code. |
| `red-first` | R1: new tests fail before the fix. R4: results are deterministic. |
| `mutants` | R3: mutation testing on the changed lines (cargo-mutants, mutmut, Stryker). Runs only when production code changed. |

- **Stacks**: Rust, Python, TypeScript/JavaScript.
- **Agent branches**: R1 runs on branches starting with `agent/`, `claude/`, `codex/`, `copilot/` or `cursor/` (configurable; `*` for all).
- **Waivers**: a person with write access can let one entry through with `/mech-waive <id> <reason>`; it shows in the comment with their name. Nothing in the PR itself can waive.
- **Forks**: on a read-only token the result goes to the job summary and the check still passes or fails on it.

Adopt with `/ekit:ci-doctor`, or by hand: [docs/mech-review-ci.md](docs/mech-review-ci.md). The testing rules behind the checks: [docs/testing-standard.md](docs/testing-standard.md).

<details>
<summary>Scripts</summary>

| Script | Does |
|---|---|
| `scripts/mech-review.py` | Review engine: `r2`, `red`, `all`, `baseline`, `mutants`, `merge`, `plan`, `doctor`. Contract JSON; exit 0 pass / 1 fail / 2 usage. `--help` for flags. |
| `scripts/scenarios.py` | Scenario runner: `run [ID]`, `check`, `can-fail REF`, `tree-hash`. |
| `scripts/mech-comment.py` | Merges job results, applies waivers, renders and posts the PR comment. Exit 0 pass / 1 fail / 3 API error / 4 no result. |

</details>

## Development

```bash
bash tests/run.sh                          # everything
python3 -m unittest discover -s tests/py   # the python unit tests alone
```

ekit runs its own checks on its own PRs (`.github/workflows/mech-review-self.yml`, python stack): a change to `scripts/` needs a test in `tests/py` that fails without it.

Skill evals (kit dev only):

```bash
claude plugin eval . --judge-model claude-opus-5-5 --scaffold --allow-tools Bash Edit Write
```

`taste-act-*` cases grant Bash, so the eval sandbox needs `bubblewrap` + `socat` and no symlinks inside `~/.docker`. Their Bash is read-only, so graders check the commands run, not a runner PASS.

Changes per release: [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
