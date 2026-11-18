# mech-review-python/real-mutmut/symlinks: a tracked symlink in docs/ that dangles or points at a parent dir neither crashes nor hangs R3

- story: As a Python repo owner whose `docs/` holds a tracked symlink (to a gitignored build dir, or back up to a parent dir), R3 still finishes in normal time and reports my mutants.
- covers: issue #7 criterion 2 (a tracked symlink inside a docs dir that dangles, target gitignored, or points at a parent dir does not crash or hang R3); criterion 1 (tests that load a tracked `scripts/x.py` by path run in the copy); criterion 3 (MISSED with file and line)
- steps:
  1. Parent's venv install and sample repo, tests load `scripts/tool.py` by path and do not read `docs/`.
  2. Base adds `docs/html -> ../_build/html` with `_build/` gitignored (dangling at head). Head changes `add` and `is_positive`. Run `mutants --stack python --test-paths 'tests/**'` with real mutmut under a 120 s limit; again with `_build/html/` present (untracked) in the checkout.
  3. A fresh repo whose base adds `docs/up -> ..`. Same run.
  4. A fresh repo whose base adds `docs/api/root -> ../..`. Same run.
- expected: every run ends well inside the limit with no traceback from mech-review, exit 1, R3 fail with entries only on `src/calc/core.py:6` (`return 0 < n -> return 0 <= n`), never `baseline tests fail at head`; the checkout unchanged.
