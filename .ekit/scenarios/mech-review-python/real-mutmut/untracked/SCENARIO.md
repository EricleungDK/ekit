# mech-review-python/real-mutmut/untracked: misuse, a test that needs an untracked file fails the baseline; tracked, it runs

- story: As a Python repo owner whose test reads a `local.cfg` I never committed, R3 tells me the baseline fails instead of quietly using my local file; once I commit it, the mutants run.
- covers: issue #7 criterion 2 (never untracked files: an untracked file the tests need stays missing and the user sees it fail; tracked top-level entries are copied); misuse/failure (`baseline tests fail at head`); criterion 3 (MISSED with file and line once it runs)
- steps:
  1. Parent's venv install and sample repo; base adds `tests/test_local.py` reading `local.cfg` next to the repo root. `local.cfg` exists in the checkout, untracked; the tests pass there.
  2. Head changes `add` and `is_positive`. Run `mutants --stack python --test-paths 'tests/**'` with real mutmut.
  3. Commit `local.cfg` and run again.
- expected: step 2 exit 1, R3 fail, note `baseline tests fail at head: mutants not run`, one agent-fixable entry with that problem, the stderr log names `test_local_cfg`; the checkout and the untracked file are unchanged. Step 3 exit 1 with R3 MISSED only on `src/calc/core.py:6`.
