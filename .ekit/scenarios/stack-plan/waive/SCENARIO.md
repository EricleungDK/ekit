# stack-plan/waive: `/mech-waive <id>` on the drift entry lets the PR through; the waiver lapses when the set of manifests changes

- story: As a repo owner whose PR adds a project before its plan entry, I post the drift entry's ready-made `/mech-waive` line with a reason and the check passes, showing my name; if the PR then adds another unchecked manifest, my waiver no longer counts; a plan that does not read cannot be waived away.
- covers: #56 56.6 (`/mech-waive <id>` on the drift entry waives it, through the comment tool the docs describe: `mech-comment.py --envelope drift=FILE`); 56.2 (messages show as `Stack plan:` lines and never fail); misuse/failure (a waiver for the old id after the set grows; a waiver of the bad plan's `CI` entry)
- steps:
  1. Parent's install; the kit clone's fake GitHub (`tests/fixtures/mech-waive/fake_github.py`, as the mech-waive scenario uses it).
  2. Base plan `web` (ts, current), `old` (ts, retiring). PR adds `api/pyproject.toml` and `cli/Cargo.toml`: `drift` exit 1 (one `D-` entry). `mech-comment.py --pr 1 --envelope r2=... --envelope drift=...`.
  3. The owner posts the offered line with a reason; report again.
  4. The PR adds `tool/package.json`: a new drift id; report again with the old waiver still posted.
  5. A bad plan (status `done`): drift exit 2 with a `CI-` entry; the owner posts `/mech-waive CI-... reason`; report.
- expected: step 2 exit 1, headline `ran: R2 D`, the table row `| D-... | fail |` naming both manifests, the line `/mech-waive D-... <why this is OK>`, a `Stack plan:` line naming the retiring stack. Step 3 exit 0, `Waived: D-... by \`owner\`: <reason>`, `1 waived`, never `all pass`. Step 4 exit 1, a different id offered. Step 5 exit 1, nothing waived.
