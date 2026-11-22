# runner/run-py/own-session: break it, a run.py whose child starts its own session

- story: As a dev whose run.py starts a server with `subprocess.Popen(..., start_new_session=True)` (so it can stop the server's group itself), a timeout or the end of the scenario still stops that server, like any background child.
- covers: #59 59.4 a run.py timeout stops its whole process tree, a background child included, and reads FAIL (here a child in its own session, and a grandchild under it); 59.7 a background child is stopped with its scenario
- steps:
  1. `git clone` the kit into the temp cwd. A sample git repo with scenarios `hang` and `quick` (run.py each). Each starts two children that write a marker file outside the repo after 4s: one plain `Popen`, one `Popen(start_new_session=True)` that itself starts a grandchild doing the same. `hang` then sleeps 30s; `quick` exits 0 at once.
  2. `EKIT_SCENARIO_TIMEOUT=1 scenarios.py run hang`; wait 7s.
  3. `scenarios.py run quick`; wait 7s.
- expected: step 2 returns within 15s with `FAIL hang: timeout after 1s`, exit 1; step 3 `PASS quick`, exit 0; after each wait no marker file exists (plain child, own-session child and its grandchild all stopped). No traceback.
