# mech-waive: the comment offers the waiver line, only a real, unedited waiver counts, the comment re-runs report

- story: As a repo owner whose agent's PR is blocked on a fail entry, I copy the line the bot offers, add my reason, post it, and the check turns green with no trip to Actions.
- covers: ready-made `/mech-waive <id> <why this is OK>` line in the sticky comment; placeholder reason ignored and named; edited comment ignored and named; outsider cannot waive; a real waiver turns the check green and shows who and why; `mech-rerun.py` re-runs the finished `mech-review report` job (not another job) and leaves a running run alone
- steps:
  1. Repo whose head deletes a test; `mech-review.py r2` gives one R2 fail entry.
  2. Fake GitHub API (fixtures/fake_github.py): the PR head, its comments, one finished run with a guard and a report job.
  3. `mech-comment.py --pr 1 --head <sha> --envelope r2=...` → exit 1; the sticky comment has the line `/mech-waive <id> <why this is OK>`.
  4. Owner posts that line unchanged → exit 1, "Waiver ignored: <id> by `owner`".
  5. Owner's real waiver in an edited comment → exit 1, "edited after posting". An outsider's waiver → exit 1, nothing waived.
  6. Owner posts the copied line with a reason → exit 0, "Waived: <id> by `owner`: <reason>", no placeholder left, one sticky comment.
  7. `mech-rerun.py --pr 1` → exit 0, one call: POST .../actions/jobs/<report job>/rerun. The run in progress → exit 0, no call, says in_progress.
- expected: exit codes and comment text as above; nothing written into the kit repo.
