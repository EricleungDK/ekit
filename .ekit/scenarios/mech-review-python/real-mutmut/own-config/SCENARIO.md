# mech-review-python/real-mutmut/own-config: a repo with its own [tool.mutmut] table gets R3 n/a, untouched

- story: As a Python repo owner who already configures mutmut in `pyproject.toml`, R3 says n/a (env) and leaves my table alone rather than overriding it or pretending to pass.
- covers: issue #7 criterion 4 (a repo with its own `[tool.mutmut]` table in pyproject.toml still gets R3 `n/a`); misuse/failure (R3 says n/a for the right reason)
- steps:
  1. Parent's venv install and sample repo; base adds `[tool.mutmut]` (`source_paths`, `also_copy`) to `pyproject.toml`.
  2. Head changes `add` and `is_positive`. Run `mutants --stack python --test-paths 'tests/**'` with real mutmut on PATH.
- expected: exit 0, R3 `n/a` with a note naming `[tool.mutmut]` and `(env)`, no entries, summary `pass <head> (0 fail, 0 confirm; ran: none; skipped: R1 R2 R4; n/a: R3)`, never `all pass`; the checkout and its `pyproject.toml` unchanged.
