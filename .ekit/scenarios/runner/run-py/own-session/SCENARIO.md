# runner/run-py/own-session: break it, a run.py whose child starts its own session

- story: As a dev whose run.py starts a server with `subprocess.Popen(..., start_new_session=True)` (so it can stop the server's group itself), a timeout still stops that server, like any background child.
- covers: #59 59.4 a run.py timeout stops its whole process tree, a background child included, and reads FAIL (here a plain child, a child in its own session, and a grandchild under that one)
- out of scope: a child in its own session that outlives a run.py exiting normally (an orphan POSIX cannot track); the docs sentence that promised it is corrected instead.
- steps:
  1. `git clone` the kit into the temp cwd. A sample git repo with scenario `hang` (run.py). It starts two children that write a marker file outside the repo after 4s: one plain `Popen`, one `Popen(start_new_session=True)` that itself starts a grandchild doing the same. It then sleeps 30s.
  2. `EKIT_SCENARIO_TIMEOUT=1 scenarios.py run hang`; wait 7s.
- expected: returns within 15s with `FAIL hang: timeout after 1s`, exit 1; after the wait no marker file exists (plain child, own-session child and its grandchild all stopped). No traceback.
