# taste-it/run-py: the skill a user installs writes run.py by default; old run.sh scenarios keep running

- story: As a user who installs ekit and asks for a scenario, the taste-it skill tells the agent to write `run.py` (any OS, no bash), gives a run.py driver example that is valid Python, and my existing `run.sh` scenarios keep passing and failing as before.
- covers: #59 59.6 taste-it writes run.py by default (the shipped SKILL.md layout and rule, the drivers.md example), the existing run.sh scenarios still pass (a run.sh pass and fail in a user repo, plus the kit's own full `run`)
- steps:
  1. `git clone` the kit into the temp cwd.
  2. Read the clone's `skills/taste-it/SKILL.md`: the layout block, the run-file rule. Read `skills/taste-it/drivers.md`: the python block.
  3. A sample git repo with `old-ok` (run.sh, exits 0) and `old-bad` (run.sh, exits 1), written as the old layout said; `scenarios.py run`.
- expected: the layout block names `run.py` as the run file and no `run.sh` line; SKILL.md says to write `run.py` and `run.sh`/`run.ps1` only when the user asks for that shell; drivers.md calls `run.py` the default and its python block parses (the `<cmd>` placeholder filled in). Step 3: `PASS old-ok`, `FAIL old-bad: exit 1`, exit 1. Agent behaviour itself (that an agent given the skill then writes run.py) is an eval, not checked here.
