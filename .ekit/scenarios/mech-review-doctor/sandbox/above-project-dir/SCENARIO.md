# mech-review-doctor/sandbox/above-project-dir: tests that read a file above the project dir pass in the checkout, fail in R3's sandbox, and doctor names the file

- story: As a Python repo owner whose project is in `app/` and whose tests read `../docs/guide.md`, doctor tells me R3's sandbox will not have that file, instead of saying `ok` and letting R3 fail on my first PR.
- covers: issue #7 criterion 5 (suite passes in a normal checkout, fails in mutmut's sandbox copy: exit 1, `trial.sandbox` fail, an `env` entry naming `../docs/guide.md`, not `ok`); 5e (writes nothing, no extra worktree); misuse/failure (a known limit of R3)
- steps:
  1. Parent's venv install. Repo with the project in `app/` (src layout), `docs/guide.md` at the repo root, a test in `app/tests` reading `app/../docs/guide.md` relative to `__file__`, and the caller doctor asks for (`project-dir: app`, `test-paths: app/tests/**`). The suite passes in `app/` of the checkout.
  2. `doctor --repo <repo> --project-dir app` under a 90 s limit; again with no `--project-dir` (detected).
  3. Control: the same repo with the guide moved into `app/docs/` and the test reading it there. `doctor --repo <repo> --project-dir app`.
- expected: step 2 exit 1, tests `pass`, sandbox `fail`, exactly one entry, class `env`, its problem naming `../docs/guide.md`, summary `fail <head> (1 problems)`, never `ok`. Step 3 exit 0, sandbox `pass`. Every run: no traceback, git state unchanged, one worktree, temp dir empty.
