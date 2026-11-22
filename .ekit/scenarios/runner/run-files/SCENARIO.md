# runner/run-files: misuse, a scenario folder with more than one run file

- story: As a dev who left a `run.sh` (or a `run.ps1`) beside a new `run.py`, the runner tells me every run file it found and runs none of them, whatever shells my machine has.
- covers: #59 59.5 two or more run files is an error naming them all, never a silent pick (`run`, `check`, `can-fail` ERROR exit 2, a child folder too, with and without bash on PATH); 59.2 (POSIX side) the run.py scenarios run with only Python and git on PATH
- steps:
  1. `git clone` the kit into the temp cwd. A sample git repo with scenarios `trio` (run.py, run.sh, run.ps1), `pair` (run.py, run.ps1), `ok` (run.py, exits 0) and `ok/kid` (run.py, run.sh). Every run file, if started, writes a marker file outside the repo.
  2. With PATH holding only Python and git: `scenarios.py run`; then `check`; then `can-fail HEAD`.
  3. The same `run` with the full PATH (bash present).
  4. Drop the extra files (keep each folder's run.py); `run`, `check`.
- expected: step 2 and 3: `FAIL trio: ...` naming run.py, run.sh and run.ps1, `FAIL pair: ...` naming run.py and run.ps1, `FAIL ok/kid: ...` naming run.py and run.sh, `PASS ok`, exit 1, never `NOT-RUN` for those folders, and no marker from trio, pair or ok/kid; `check` exit 1; `can-fail` `ERROR <id>` for trio, pair and ok/kid (each naming its files), exit 2. Step 4: four PASS, exit 0; `check` exit 0. No traceback; nothing written into the kit clone.
