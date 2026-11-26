# Taster brief template

Fill every `<…>`; the text around them goes in as written. Black box: the brief holds no source, diff, or implementer reasoning. The taster follows the taste-it skill; this brief is its input.

```
Worktree: <absolute path of the implementer's worktree>, branch `<branch>` (HEAD <sha>). The implementer is idle while you taste; you write scenarios here. Enter it before your first write: EnterWorktree with `path: <that path>`. A hook blocks writes into any other worktree.
Read list: <user-facing docs only: README sections, CLI `--help`, every existing `.ekit/scenarios/**/SCENARIO.md`>. Nothing else in the repo.
Criteria: <acceptance criteria, id and text, as the user saw them>.
Install: <steps as a user gets them: real install from the repo into a fresh temp dir, never the source tree, never global>.
Runner: RUN = <the `[ekit] Scenario runner:` command>. `RUN run <id>` while writing, then `RUN run`, then `RUN check`.
`can-fail` baseline: <ref before this change>; `RUN can-fail <ref>` → `CAN-FAIL ✓` for every scenario covering these criteria.
Commit scope: `.ekit/scenarios/**` only, on `<branch>`; commit message <owner's commit style, attribution trailer or none>. Leave other files as they are.
Skills: load the taste-it skill before writing any scenario.
Mech check: after your commit, run `<py> -I <kit>/scripts/mech-review.py all --repo <that path> --base <the can-fail baseline ref> --head HEAD --stack <stack> --head-branch <branch>` <plus the repo's --test-paths/--protected-paths/--agent-prefix>. It judges your scenario files as tests. Before you report, its `summary` shows 0 fail (`all pass <sha>` or `pass <sha> (0 fail, …)`); fix each fail entry in your scenarios in a new commit and run it again.

Report: each finding with its scenario id and verdict (fix / human), the runner's PASS/FAIL lines, the scenarios read and the files created or edited, your commit SHA, the mech-review `summary` line of your commit, with 0 fail.
```
