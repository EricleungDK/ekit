---
name: ci-doctor
description: Set up or repair a repo's mech-review CI. Use when adopting mech-review, or when its check reports `no result`, `n/a`, or a CI entry.
---

Ends in a PR a person merges. `.github/**` is a human decision, so your last action is opening that PR.

`DOCTOR` = `<py> -I <kit>/scripts/mech-review.py doctor --repo <repo>`. `<py>` = the Python named by the `[ekit] Python:` session line (`python3`, `py -3` or `python`: the first that is 3.9+); no such line → `python3`, else `py -3`, else `python`. `<kit>` = the `scripts/` parent named by the `[ekit] Scenario runner:` session line; no such line (harness without hooks) → `~/.ekit`, cloned once with `git clone --depth 1 https://github.com/EricleungDK/ekit ~/.ekit`. Exit 0 no problems, 1 problems, 2 usage.

## 1. Diagnose

Run `DOCTOR` on the default branch, no hints. Its `mode` picks the way on:

- `ask`: several projects. Ask the user which, naming each as the entry does, then rerun with `--project-dir`, `--stack` or both (the entry's hint).
- `repair`: the repo's own adapter file or stack plan is there, unread or unproven by doctor (or R0's `adapter-fix` entry on a PR). Repair mode (#24) is not built yet: stop with a Needs-you block (finish) quoting the entries.
- `setup`: a project no adapter covers, or an empty repo (`no-project`, mode null) whose user names the stack to come: follow [setup.md](setup.md), which takes step 3's callers and step 5's PR from here.
- `adopt`: the steps below.
- null otherwise: the entries say why (no project, no TOML reader here); report them.

Keep `inputs`, `trial` and each entry's `hint`: the hint is the exact fix.

## 2. Read what doctor can't

Read `.github/workflows/*`. Anything the tests depend on that isn't in `inputs` goes into `setup-command`: env values, services, setup steps.

## 3. Write the caller

On a new branch, write or repair `.github/workflows/mech-review.yml`. Keep inputs already there; add or correct only what entries name. The repo has `.ekit/scenarios/` → `test-paths` holds `.ekit/scenarios/**` too (doctor's `inputs` says so): scenario fixtures are test support, not code for R3 to mutate.

```yaml
name: mech-review
on:
  pull_request:
permissions:
  contents: read
  pull-requests: write
jobs:
  mech-review:
    uses: EricleungDK/ekit/.github/workflows/mech-review.yml@v0
    with:
      # every key in doctor's `inputs`, `stack` too: `auto` is the default, a set stack survives a second project
      # test-paths: one glob per line; a repo with .ekit/scenarios/ gets `.ekit/scenarios/**` beside `tests/**`
      protected-paths: |
        .github/**
```

Also write `.github/workflows/mech-waive.yml`, as is: a waiver comment then re-runs `report` by itself.

```yaml
name: mech-waive
on:
  issue_comment:
    types: [created, edited, deleted]
permissions:
  actions: write
  pull-requests: read
  contents: read
jobs:
  mech-waive:
    uses: EricleungDK/ekit/.github/workflows/mech-waive.yml@v0
```

Ask the user for `protected-paths` beyond `.github/**`, and whether their agent branches use a prefix outside the default `agent-branch-prefix` list (`agent/`, `claude/`, `codex/`, `copilot/`, `cursor/`); they own both.

## 4. Iterate

Commit (doctor reads HEAD), then rerun `DOCTOR`. Done when it exits 0. An entry that survives its fix twice → stop with a Needs-you block (finish).

`env` entries on this machine may be local-only: a missing tool here says nothing about the runner, and `mutation_tool: absent` gets no entry because CI installs it. Report them as verification debt unless the workflow also lacks the input.

## 5. Open the PR

Push and open the PR. Body: doctor's `summary` at the branch head, the `trial` verdicts, each input and why. Say the PR's own mech-review check goes red `needs-human` by design (it edits `.github/**`): the owner reads the change, posts that entry's ready-made `/mech-waive <id> <reason>` line with a reason, re-runs the failed `report` job (the mech-waive caller only works once merged: GitHub runs comment workflows from the default branch), and merges on green.

Report the PR URL via finish. Stopped before the PR (blocked, no remote, asked to) → the final report itself carries the full caller YAML and PR body.

## Stack plan

`.ekit/stack-plan.toml` lists the repo's stacks; CI's drift check fails a PR whose manifest (`package.json`, `pyproject.toml`, `Cargo.toml`, ...) no entry covers. Format: `<kit>/docs/mech-review-ci.md#stack-plan`. When the repo's stacks change, edit it in the same work:

- Migration (JS to TS, say): add an entry for the new stack (`current` once its manifest is there, else `planned`) and set the old one to `retiring`. Remove the old entry only once its code is gone and the user agrees the migration is finished. One folder may hold both entries: the built-in `ts` covers JS and TS.
- A new project: an entry with its folder and an adapter that lists its manifest (`python`, `rust`, `ts`, or an adapter file's path); a folder of samples goes in `ignore`.

Commit, then run `<py> -I <kit>/scripts/mech-review.py drift --repo <repo> --base HEAD --head HEAD --format text` (it reads the committed plan). Clean: `pass` with no fail entry. Its `message:` lines are notes: a retiring stack's stays until the migration ends. The session's `[ekit] Stack plan` lines are the same check at session start.
