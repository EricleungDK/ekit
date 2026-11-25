---
name: mistake-to-check
description: Turn one agent mistake into a mechanical check, or one line saying why none. Use when an agent mistake should become a check (retro hands each one over), and to promote or remove a rule it made.
---

One **mistake** in, one result out: the **change** that makes a machine catch it next time, or one `No check:` line saying why none is made. A rule in the agent docs was written and still broken; the result here is something that runs.

`<kit>` = the `scripts/` parent named by the `[ekit] Scenario runner:` session line, else `~/.ekit` (cloned once from `https://github.com/EricleungDK/ekit`). `<py>` = the Python named by the `[ekit] Python:` session line; no such line → `python3`, else `py -3`, else `python`.

## Input

- **The mistake**, one line: what the agent did, and the rule or expectation it broke.
- **Its evidence**: the failing run (CI run, check entry, transcript) and the commit or PR that carries the mistake. Find what is missing with `git log` and `gh`; a mistake with no commit or PR to name gets `No check: <mistake>: no commit or PR to name as its incident`.

**From `retro`.** The owner's `retro` skill (outside this kit) finds a run's mistakes and hands them here one at a time, each with the mistake line, its evidence and, when it knows one, a second example. Run this skill once per mistake and give retro back that mistake's result line (step 4).

## 1. Filter

Answer each question yes, with the answer written down, or stop at the first no with `No check: <mistake>: <the question>: <why>`.

1. **Decidable**: a machine says yes or no from files, the diff or an exit code, with no judgment. "The changelog did not change" is decidable; "the test is too weak" is judgment.
2. **A class**: name a second, different example of the same mistake (another PR, another file, another run). One you cannot name makes it an **instance**: the test that fixed it already guards it.
3. **Visible at check time**: what the check reads (the diff, the repo at head, a command's exit code) shows the mistake when the check runs. A mistake that shows only on another machine (local differs from CI, an OS the local run lacks) goes on to the environment row of step 2, whose result is an environment fix.
4. **Worth its upkeep**: a repeat costs more (CI round trips, the owner's time) than the check does (its false positives, its two cases, its edits when the code moves).

## 2. Remove the possibility, then route

First make the mistake impossible, so no rule is needed: derive the list from the directory instead of keeping it by hand (`tests/mech-modules.test.sh` finds the engine modules from the package directory, #82), generate the file, give one command in place of a recipe. When that works, it is the change: route no further.

Else route by what the mistake is about:

| The mistake is about | Where the check lives |
|---|---|
| The code (a banned call, an assumption about the developer machine's OS) | The stack's own linter, as a configured rule |
| The diff (one path changed, another should have) | A co-change rule with its two proof cases |
| The process (wrong commit verified, pushed before review) | One of ekit's gates or command exit codes, with a red-first test |
| The environment (local differs from CI) | No rule: an environment fix |

### The code: a linter rule

Configure the stack's linter: ruff (`[tool.ruff.lint.flake8-tidy-imports.banned-api]`, or select the rule), ESLint (`no-restricted-syntax`, `no-restricted-imports`), clippy (`disallowed-methods` in `clippy.toml`). A comment beside the setting names the incident (commit sha or `#N`). Its two cases go in the repo's suite: a snippet the linter must flag and one it must pass. The rule starts at the linter's warning level where CI shows warnings without failing; promoted, it is an error. Every code rule goes to the linter: ekit has no pattern engine of its own.

### The diff: a co-change rule

Add one `[[rule]]` to `.ekit/co-change.toml` (`format = 1` once, at the top of a new file):

```toml
[[rule]]
id = "<what must change together>"
trigger = ["<glob of the path that changed>"]
require = ["<glob of a path that should have changed with it>"]
reason = "<the rule, as the agent docs state it>"
incident = "<the commit sha, or #N of the PR, that made the mistake>"
flagged = ["<a path the incident changed>"]
control = ["<a path the incident changed>", "<a path require matches>"]
```

Leave `severity` out: a new rule is `confirm` (listed, never blocking). Commit, then prove it (`<base>`: the commit before the rule's; `<stack>`: the repo's, `python`, `rust` or `ts`): `<py> -I <kit>/scripts/mech-review.py r0 --repo . --base <base> --head HEAD --stack <stack>` shows `<id>:flagged` and `<id>:control` as `pass` under `checks.R0["co-change"]`, and `r2` over the same range (add `--test-paths` as the repo's CI does) gives no entry on `.ekit/co-change.toml` (the incident resolves, both cases are there). A case that reads wrong is a rule that does not work: fix the globs or the case until both pass.

### The process: a gate

The check is one of ekit's gates: a hook, or a script whose exit code a skill step stops on. Wrong commit verified → `scripts/verified-commit.py` (#81) exits 1 when a mech-review result's head is not the worktree's head or the pushed tip, and the orchestrate-agent review relay runs it before the review and before a push. In ekit's own repo, build it red-first: a test in `tests/py/` that calls it in-process and fails on the base, then the code, then the skill step that runs it. In any other repo the gate belongs to ekit: the change is an issue on `EricleungDK/ekit` with the mistake, its evidence and the exit code that would have caught it.

### The environment: no rule

The failure lives in a machine, not in the diff: no rule over the diff can see it. The change is the environment fix: the one command that runs what CI runs (`scripts/ci-local.py` for ekit's own work), a setup script, a pinned tool version, or a CI job on the missing OS (ekit's `hooks-macos`). When the fix already exists, the result is `No check: <mistake>: environment: <the fix that covers it>`.

## 3. Life of a rule

The orchestrator adds, promotes and removes rules on its own: no owner approval per rule, and no cap on their number. Each one is a line in the finish report, the owner's one routine touchpoint.

- **Add**: steps 1 and 2. A new rule starts at `confirm` (or the linter's warning).
- **Promote**: when the rule has fired on real PRs and every firing was the mistake, set `severity = "fail"` (or the linter's error), naming those PRs in the commit message.
- **Remove a misfiring rule**: a misfire is an entry on a PR that did not make the mistake. A rule that keeps misfiring is removed, or its `trigger` narrowed to leave the misfired paths out, naming the misfired PRs in the commit message.
- **Neither in the PR where the rule fires.** Promotion and removal each go in a PR of their own, where the rule does not fire. The rules are read at the base, so the firing PR is judged by the rule as it was; R2 fails a weakening or removal of a rule that fires in the same range (`needs-human`). The firing PR fixes the mistake, or, for a misfire, names the removal PR; a `fail` that misfires holds it until the removal lands on the base.

## 4. Result

One result per mistake, its change committed on a branch of its own with its proof (the linter's two cases, the co-change rule's R0 and R2 runs, the gate's red-first test), and one line for the caller, retro and the finish report:

- `Rule added: <id> (<where it lives>), from <incident>`
- `Rule promoted: <id> to fail, after <the PRs it fired on>`
- `Rule removed: <id>, misfired on <the PRs>`
- `Made impossible: <mistake>: <the change>`
- `Environment fix: <mistake>: <the change>`
- `No check: <mistake>: <the question or route that stopped it>: <why>`

## Worked examples (the #74–#77 run)

| Mistake | Result |
|---|---|
| A test relied on `RecursionError` at deep nesting | `No check`: an instance; no second example, and the test that fixed it guards it |
| A report verified one commit and a later one was pushed | Process: the `verified-commit.py` gate (#81) |
| A new engine module was left out of the layering test's list | Made impossible: the list is derived from the package directory (#82) |
| A behaviour change left the changelog and the two docs alone | Diff: the co-change rules `behaviour-changelog`, `behaviour-status-line` and `behaviour-ci-doc`, one per doc (#86) |
| Tests failed on macOS only | Environment: no rule; macOS CI (`hooks-macos`) is the check |
