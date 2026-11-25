# mistake-to-check: the shipped skill routes the #74–#77 run's mistakes, and the checks it routes to bite

- story: As an orchestrator handed an agent mistake (by the owner's retro, or my own), I install ekit, read the mistake-to-check skill, and the check it tells me to make works as written: the co-change rule filled from its template proves itself and flags the next PR that repeats the mistake, and the gate it names refuses a result for the wrong commit.
- covers: #87 (the skill exists under `mistake-to-check`, its description triggers on "an agent mistake should become a check"; the filter, the routing table and "make it impossible" first; the output is the change or a `No check:` line; this run's five mistakes with their results: RecursionError at deep nesting → no check (an instance), wrong commit verified → gate, forgotten module in the list → derive the list, forgotten doc update → co-change rule, macOS-only failures → environment; the finish report's rule lines)
- steps:
  1. `git clone` the kit into the temp cwd; read `skills/mistake-to-check/SKILL.md` and `skills/finish/SKILL.md` from the clone.
  2. The worked-examples table: each of the five mistakes, with its result.
  3. A sample python repo with an incident: a commit that changes `src/app.py` and leaves `CHANGELOG.md` alone. Fill the skill's co-change template (its placeholders only) with the incident's sha, under `format = 1`, commit it, and run the skill's own `r0` command line: both proof cases `pass`. `r2` over that range: no entry on the rule file.
  4. The next PR repeats the mistake (changes `src/app.py` only): `r2` gives one `confirm` entry naming the rule, exit 0. A PR that updates `CHANGELOG.md` too: no entry.
  5. Misuse: the template filled with a control that leaves out the required path: `r0` fails the rule's control case, naming it.
  6. The gate route: `verified-commit.py` with a result for the incident's commit while the worktree is at a later head: exit 1 naming both; with the head's result: exit 0.
- expected: as above; the skill's `r0` command line runs as written; no traceback; nothing written into the kit repo. That an agent given a mistake picks the right route is the eval's job (`evals/mistake-to-check-*`), not checked here.
