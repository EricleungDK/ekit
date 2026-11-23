# stack-plan/retiring-age: a stack retiring for 30 days or more gets a reminder, counted from the plan's git history

- story: As a repo owner midway through a migration I set the old stack to `retiring`; the drift check keeps telling me it is still there, and once it has been retiring for 30 days it reminds me to finish or drop the migration, counting from the plan commit where it last became retiring on my branch.
- covers: #56 56.7 (a retiring entry 30+ days old, by the plan's git history, gets a reminder); 56.2 (a retiring stack's manifest still present → message; messages never fail)
- steps:
  1. Parent's install. Repo with `old/package.json` (ts) and `new/pyproject.toml` (python), both `current`, the plan committed 90 days ago (author and committer dates set).
  2. `old` set to `retiring` in a commit 31 days old: `drift` HEAD..HEAD. Then an unrelated plan edit 5 days old (an `ignore` line); then a PR on top, base..PR.
  3. A second repo where `old` became retiring 29 days ago.
  4. A third: retiring 60 days ago, current again 40 days ago, retiring again 10 days ago.
  5. A fourth: retiring on main 45 days ago; a side branch that sets it retiring 3 days ago merged in.
- expected: step 2 every run exit 0, no entry, the retiring message with `retiring for 31 days` and `finish the migration or drop it`. Steps 3 and 4 the retiring message with no `retiring for`. Step 5 `retiring for 45 days`. No traceback.
