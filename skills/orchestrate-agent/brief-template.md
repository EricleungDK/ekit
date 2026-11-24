# Subagent brief template

Fill every `<…>`; the text around them goes in as written. The agent sees nothing but this brief.

```
Repo: <absolute path of your worktree>, branch `<branch>` (HEAD <sha>, pushed: yes/no; PR #<n> if any). Enter it before your first write: EnterWorktree with `path: <absolute path of your worktree>` (without `path` it makes a new worktree on a new branch). A hook blocks writes into any other worktree.
Spec: <issue link, or "free-form task"> — checklist items this unit owns: <items>.
Unit: <name>; files you own: <paths>; do not edit: <other units' files>; depends on: <unit / interface or none>.
Read first: <AGENTS.md, repo docs index, the specific docs/reports for this area>.
Owner rules: <commit style, attribution trailer text, docs to update>. Testing standard: <link from the repo's testing doc>.
Seams: <the public interfaces this unit's tests go through, as the user saw them: function, CLI, endpoint>. Tests observe behaviour there, with expected values taken from the spec.
Skills: a TDD skill in your skill list → load it before task 1; a bug-diagnosis skill → load it when a failure's cause is unknown. Names differ per install. Where one has you ask the user, this brief is the answer. None listed → the tasks below are the whole flow.

Work: <outcome to build (behaviour, interface, acceptance) / the exact failure: assertion, CI run and job id, command that shows it / or the failing mech-review entries verbatim: id, file, line, problem, hint, forbidden>.
Scenarios: <ids this unit must keep green, or none; failing scenario id + transcript as repro on fix rounds>.
Known context: <recent commits that may be involved, suspects, what was ruled out>.
Environment: <how to run tests here: env vars, binaries, build step first>.

Tasks:
1. Build: red → green in slices: one failing test at a seam, then only the code that passes it. Each slice: typecheck and run that test file. Full suite once, at the end. R1 needs at least one new or changed test that fails on the base's code; tests that pin existing behaviour are guards and may sit beside it.
   Fix: reproduce and capture the actual error; classify it with the failure-triage skill; check new vs pre-existing on the parent commit in a temp worktree (remove it after; flaky: failure-triage's flaky protocol); fix the root cause red first (test-only fix only when the test is wrong).
2. Stay in your files; a needed change elsewhere goes in your report, not your diff.
3. Keep guards and checks at full strength. Forbidden: delete, skip or weaken a test; change an expected value to match output; suppress a lint without reason; edit protected paths; pass a test before the fix. Full table: testing standard §3. No waivers.
4. Verify: <the unit's verify command, as `<py> -I <kit>/scripts/task-verify.py --repo <checkout> run -- <command>` with `<py>` and both paths filled in; other commands, and how many runs>. Then, before the review request, R3 as CI runs it; commit first: it tests the head commit. `<py> -I <kit>/scripts/r3-local.py --repo <checkout> --base <base> --stack <stack> --test-paths <glob> --mutation-budget <mutation budget, minutes>` (one `--test-paths` per glob of the repo's mech-review caller: its default is only `tests/**`), POSIX only (WSL on Windows). It runs at the CI budget, shards in parallel; a MISSED on a changed line is fixed before review, and so is an unconfirmed survivor (`r3-local.py` exits 1 on either). <Stack without mech checks: drop this sentence.>
5. Docs: <task log entry, report section, SOP rule if reusable>.
6. Commit on <branch>. Every fix (review finding, mech entry, R1 fail) is a new commit on top; commits you reported stay as they are. A fix for a mech entry carries body line `mech: <id>` (the 3-strike stop counts per id). Commit message ends with:
   <attribution trailer>
7. Review: you cannot spawn agents, so the orchestrator runs the mech checks, then your review. Stop and send your report (task 10) as a REVIEW REQUEST. Wait; findings arrive by message. Fix the real ones red-first, each in a new commit, re-verify, then report again.
8. Push: <yes after review passes: open the PR, then turn on its CI monitor (Auto-fix), approved at plan time; a failure wakes you, and you fix it as a CI round / no>.
9. Fix rounds: 3 per source (review, taste, CI), counted apart; rounds left: <review n, taste n, CI n>. The same mech `id` or the same finding (its key: file plus a short title, as the orchestrator names it) failing a 3rd time: stop and report, whatever is left.
10. Report: load the finish skill; every report you send (review request, after a fix round, blocked) is its report, done or blocked branch, one row per checklist item you own. Add: branch, base SHA, head SHA, files changed, focus areas, commits; for a fix, the error, its cause, and new vs pre-existing. The issue and the PR stay with the orchestrator.

Do not merge. A step that spawns agents, in these tasks or in a skill you loaded: hand it to the orchestrator the same way as review.
```
