# runner/seeded: `seeded <id>` says whether a scenario I just seeded fails before its feature exists

- story: As a dev who has just written a seeded scenario for a feature my app lacks, `scenarios.py seeded <id>` tells me it fails on the repo as it is, with why and the transcript; one that already passes is named as checking nothing yet; my last results stay as they were.
- covers: #60 60.4 (a seeded scenario that fails on the repo as it is reads `SEEDED ✓ <id>: fails on the repo as it is: <reason>: <its last line>` (stderr, else stdout) and its kept transcript, exit 0; one that passes reads `CHECKS NOTHING YET <id>`, exit 1; on the files as they are, uncommitted ones included; a scenario's children too; no results.json written)
- steps:
  1. `git clone` the kit into the temp cwd. A user repo with `greet.py` (`greet.py bob` prints `hello bob`; no `--shout`), an unmarked `ok` scenario (exits 0); commit; `scenarios.py run` (a full green run).
  2. Write, without committing, run.py scenarios: `greets` (`- feature: greeting`, wants `hello bob`: the feature exists), `shouts` (`- feature: shouting`, runs `greet.py --shout bob`, wants `HELLO BOB`, says `wanted 'HELLO BOB', got ...` on stderr), `shouts/quiet` (`- feature: shouting`, prints `quiet mode missing` on stdout only, exits 3).
  3. `seeded shouts/quiet`, `seeded shouts`, `seeded greets`.
  4. Add `--shout` (not quiet mode) to `greet.py`; `seeded shouts`.
- expected: step 3: `SEEDED ✓ shouts/quiet: fails on the repo as it is: exit 3: quiet mode missing`, exit 0; `seeded shouts` prints a `SEEDED ✓ shouts: fails on the repo as it is: exit 1: wanted 'HELLO BOB', got 'hello --shout'` line and the same for `shouts/quiet`, each followed by a `transcript:` path that exists and holds that line, exit 0; `CHECKS NOTHING YET greets`, exit 1; `.git/ekit/results.json` byte for byte as the step-1 run left it after each, and `check` exit 1 `stale` (the new files), never a seeded run's result. Step 4: `CHECKS NOTHING YET shouts` and `SEEDED ✓ shouts/quiet`, exit 1. No traceback.
- children: misuse
