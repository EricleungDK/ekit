# runner/seeded/misuse: `seeded` on a scenario it cannot judge says why, never SEEDED ✓

- story: As a dev who runs `seeded` on the wrong thing (a scenario with no feature line, an empty or misspelt one, a folder with two run files, a scenario that writes into my repo, an id that does not exist, no id), I get `ERROR <id>` naming what is wrong (or a usage error), exit 2, and never a `SEEDED ✓` that would pass for proof.
- covers: #60 60.4 misuse (`seeded` ERROR exit 2 for no, an empty or a bad `- feature:` line, two run files (naming both) and a write into the repo (naming the file); an unknown id and a missing id exit 2; none reads `SEEDED ✓` or `CHECKS NOTHING YET`)
- steps:
  1. `git clone` the kit into the temp cwd. A user repo with run.py scenarios that all exit 1 (as a seeded one before its feature would): `plain` (no feature line), `blank` (`- feature:` with no name), `caps` (`- Feature: export`), `both` (`- feature: both`, a run.py and a run.sh), `scribble` (`- feature: notes`, writes `notes.txt` into `$EKIT_REPO`); commit.
  2. `scenarios.py seeded <id>` on each; then `seeded nope` and `seeded` with no id.
- expected: each of the five: exit 2, an `ERROR <id>:` line; `plain` names the missing `- feature:` line, `blank` says empty, `caps` quotes `- Feature: export`, `both` names run.py and run.sh, `scribble` names `notes.txt`; no `SEEDED ✓` and no `CHECKS NOTHING YET` anywhere. `seeded nope`: exit 2 naming `nope`; `seeded`: exit 2 with the usage line. No traceback; no results.json written.
