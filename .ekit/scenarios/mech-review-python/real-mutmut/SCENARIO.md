# mech-review-python/real-mutmut: real mutmut 3.8.1 runs the mutants of a repo whose tests read tracked docs/ and scripts/ files; MISSED and caught come out right

- story: As a Python repo owner I install pytest and mutmut in a venv as CI does and run `mech-review.py mutants --stack python` on my PR: tests that read `docs/` and load `scripts/x.py` relative to `__file__` pass in mutmut's copy, a weak change is MISSED with its file and line, and a well-tested change passes.
- covers: issue #7 criterion 1 (tests read a tracked `docs/` file and load a tracked `scripts/x.py` by path: R3 runs its mutants, no `baseline tests fail at head`); criterion 2 (the copy never overwrites the mutated sources: a well-tested change is caught in a src layout whose source dir holds a tracked data file the tests read, and in a flat layout); criterion 3 (a surviving mutant on a changed line reports MISSED with file and line; a well-tested changed line is caught, R3 pass)
- steps:
  1. Fresh venv in the temp dir: `pip install pytest==9.2.0 mutmut==3.8.1`; PATH puts the venv first (real mutmut, no stub).
  2. Repo on base: `src/calc/core.py` (`add` well tested, `is_positive` tested only with 5), `src/calc/assets/units.txt`, `docs/usage.md`, `scripts/tool.py`; tests read `docs/usage.md` and the asset, and load `scripts/tool.py` with `spec_from_file_location`, all relative to `__file__`.
  3. Head changes both functions. `mutants --stack python --test-paths 'tests/**'` (JSON, then `--format text`).
  4. From base, a head that changes `add` only. Same command.
  5. A flat-layout repo (`calc/` at the root, a test reading `docs/about.md`), head changes `add`. Same command.
- expected: step 3 exit 1, R3 fail (not the baseline), entries only on `src/calc/core.py:6` (`return 0 < n -> return 0 <= n` among them), none on line 2, summary `fail <head> (2 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)`, the text format's first line the same and naming `src/calc/core.py:6`. Steps 4 and 5 exit 0, R3 pass, no entries, summary `pass <head> (0 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)`. The caller checkout is untouched.
- children: untracked, symlinks, own-config, cap
