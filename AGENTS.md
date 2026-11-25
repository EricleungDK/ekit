# AGENTS.md

ekit: a Claude Code plugin (skills, hooks) plus the mech-review engine that checks PRs mechanically. Python 3.9+, standard library only; shell tests.

## Where things are

- Engine: `scripts/mech_review/`, entry `scripts/mech-review.py`. Start at the docstring of `stack.py`: the adapter interface every stack implements.
- A stack as data (adapter files): `adapter_file.py`, `data_adapter.py`, `scan.py`, `adapters/ts.toml`. Format: `docs/mech-review-ci.md` § Adapter file.
- R2: `r2.py`. R1 and R4: `red.py`. R3 (mutation): `mutants.py`.
- Skills: `skills/<name>/SKILL.md`. Hooks: `hooks/hooks.json`, which runs `scripts/*.py`.
- Tests: `tests/*.test.sh` (the CLI on fixture repos) and `tests/py/` (unittest). Scenarios: `.ekit/scenarios/` (taste-it skill).
- Test rules and the cheats the checks catch: `docs/testing-standard.md`. CI inputs and per-stack behaviour: `docs/mech-review-ci.md`.

## Run

`README.md` § Development has the commands. On Windows run them in WSL: the suites need LF files, symlinks and `jq`.

## What no config tells you

- ekit's own PRs run mech-review with the python stack: a change under `scripts/` needs a test in `tests/py/` that fails on the base.
- Python tests of the engine call `cli.main(argv)` in-process, as `tests/py/test_adapter_cli.py` does. R3's mutmut sees only in-process calls; a subprocess-only test leaves every changed line MISSED.
- Once per change under `scripts/`, before the final review request (not after each fix round), run what CI runs (commit first; POSIX or WSL; needs `uv`): `python3 scripts/ci-local.py --base origin/main`. It runs the mech checks with this checkout's engine, the unittest suite on CI's Python 3.14, and R3 with ekit's caller inputs, and exits 0 only when all three passed. A MISSED or an unconfirmed survivor on a changed line is fixed before review; a step `not run here` is verification debt in your report.
- `.github/**` is a protected path: the owner makes that edit and waives its entry. Plan it as the owner's step.
- Which docs a change must update: the rules in `.ekit/co-change.toml` (each rule's `reason` says what). mech-review lists a broken one as an R2 entry.
