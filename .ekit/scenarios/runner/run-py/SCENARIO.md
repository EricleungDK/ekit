# runner/run-py: a scenario written as run.py

- story: As a dev on a machine with no bash, I write my scenario as `run.py` and the runner passes, fails and times it out as it does a `run.sh`.
- covers: #59 run.py passes and fails as run.sh does; run.py timeout stops its whole tree (a background child included) and is a FAIL; a folder with two run files is an error naming both
- steps:
  1. A sample git repo with scenarios `hello` (run.py, exits 0) and `bad` (run.py, exits 2).
  2. `scenarios.py run` -> PASS hello, FAIL bad: exit 2, exit 1.
  3. Add a `run.sh` beside `hello`'s run.py; `run` -> FAIL hello naming both files.
  4. Drop `bad` and the extra run.sh; `run` exit 0, `check` exit 0.
  5. `hang` (run.py): starts a background child that writes a file after 4s, then sleeps 30s; `EKIT_SCENARIO_TIMEOUT=1 run hang`.
- expected: the lines and exit codes above; the timeout run returns within 15s with `FAIL hang: timeout after 1s`, and the child's file never appears; nothing written into the kit repo.
