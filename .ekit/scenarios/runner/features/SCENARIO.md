# runner/features: `N of M features working` from the scenarios marked `- feature:`

- story: As a dev whose repo has seeded scenarios (each with a `- feature: <name>` line), a full `run` and a fresh `check` tell me how many of the features I asked for work; my old scenarios with no marker read exactly as before.
- covers: #60 60.3 (the line counts features from the marked scenarios, N = features whose scenarios all PASS: a feature with one failing scenario is not working, a feature's scenarios in a parent and a child share the name, case and spacing aside; printed on an unfiltered `run` and on `check` for a full fresh run, not after a filtered `run` or an edit; no line when nothing is marked; an unmarked scenario reads exactly as before)
- steps:
  1. `git clone` the kit into the temp cwd. A user repo with a small app `greet.py` (`greet.py bob` prints `hello bob`; no `--shout` yet) and two unmarked run.py scenarios: `ok` (exits 0) and `bad` (exits 1).
  2. `scenarios.py run`, `check`; drop `bad`; `run`, `check`.
  3. Add seeded scenarios: `greets` (`- feature: greeting`, runs `greet.py bob`, wants `hello bob`), `shouts` (`- feature: shouting`, runs `greet.py --shout bob`, wants `HELLO BOB`), `shouts/plain` (`- feature:   Shouting ` (case and spacing differ), runs `greet.py bob`). Commit.
  4. `run`, `check`; then `run greets`, `check`.
  5. Add `--shout` to `greet.py`; `run`, `check`.
  6. Edit `greet.py` again (a comment); `check`.
- expected: step 2: exactly `FAIL bad: exit 1`, `PASS ok`, `FAIL: 1/2 scenarios` (exit 1) and `last run FAIL` (exit 1); then exactly `PASS ok`, `PASS: 1/1 scenarios` (exit 0) and an empty `check` (exit 0): no `features working` anywhere. Step 4: `run` exit 1, `FAIL shouts`, PASS for the rest, last line `1 of 2 features working`; `check` exit 1, `last run FAIL` then `1 of 2 features working`; the filtered `run greets` and the `partial run` check print no features line. Step 5: `run` exit 0 ending `2 of 2 features working`; `check` exit 0 printing `2 of 2 features working`. Step 6: `check` exit 1 `stale`, no features line. No traceback; nothing written into the kit clone.
- children: markers
