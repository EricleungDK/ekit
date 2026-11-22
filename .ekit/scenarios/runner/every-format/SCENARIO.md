# runner/every-format: what run.sh had, a run.py has too

- story: As a dev moving my scenarios from `run.sh` to `run.py`, a failed run's transcript is kept, my screenshots are listed, a stray `__pycache__` is no repo change, a write into the repo still is, and `can-fail` reads the same for either file.
- covers: #59 59.7 failed transcript kept, artifacts listed, Python bytecode a run.py leaves is not a repo change, `can-fail` reads the same for every format (run.py and run.sh here; run.ps1 needs PowerShell: not on this host); 59.1 a run.py that raises, has a syntax error, or fails an `assert` while the caller has `PYTHONOPTIMIZE` set is a FAIL as a failing run.sh is; 59.2 (POSIX side) the run.py scenarios give the same verdicts with only Python and git on PATH
- steps:
  1. `git clone` the kit into the temp cwd. A sample git repo whose first commit has `lib.py`, whose second adds `feature.txt`. Scenarios, each as `<name>-py` (run.py) and `<name>-sh` (run.sh): `shot` (saves `shot-<fmt>.png` to `$EKIT_ARTIFACT_DIR`, prints a marker, exits 1), `pyc` (imports `lib` from `$EKIT_REPO` with bytecode writing on, exits 0), `feat` (exits 0 iff `$EKIT_REPO/feature.txt` exists), `always` (exits 0). Plus run.py only: `raise-py`, `syntax-py`, `assert-py`.
  2. `PYTHONOPTIMIZE=1 scenarios.py run`.
  3. Make `shot-*` pass, `run` again.
  4. With PATH holding only Python and git: `run`.
  5. `can-fail <first commit>` (full PATH).
  6. Add `dirty-py` and `dirty-sh` (each writes `notes.txt` into `$EKIT_REPO`); `run dirty-py`, then `run dirty-sh`.
- expected: step 2 exit 1: `FAIL shot-py`, `FAIL shot-sh`, `FAIL raise-py`, `FAIL syntax-py`, `FAIL assert-py`, PASS for pyc/feat/always of both formats, no `modified the repo` line although `__pycache__/` now sits in the sample repo; results.json lists `shot-<fmt>.png` under each shot scenario's `artifacts` and the file exists; `failed/shot-py.log` and `failed/shot-sh.log` hold the marker. Step 3: shot-* PASS, both `failed/` transcripts still there. Step 4: every run.py scenario has the verdict it had with bash on PATH, the run.sh ones read `NOT-RUN ... (env)`. Step 5: `CAN-FAIL ✓ feat-py` and `CAN-FAIL ✓ feat-sh`, `CANNOT FAIL always-py` and `CANNOT FAIL always-sh` (the same words for both), exit 1. Step 6: each exits 1 with `modified the repo`. No traceback.
