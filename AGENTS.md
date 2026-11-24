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
- Before a review request on a change under `scripts/`, run R3 as CI does (commit first; POSIX or WSL): `python3 scripts/r3-local.py --base origin/main --stack python --test-paths 'tests/**' --test-paths '.ekit/scenarios/**' --mutation-budget 20`. A MISSED or an unconfirmed survivor on a changed line is fixed before review (it exits 1 on either).
- CI runs a newer Python than WSL's 3.12: also run `uv run --python 3.14 python -m unittest discover -s tests/py`.
- `.github/**` is a protected path: the owner makes that edit and waives its entry. Plan it as the owner's step.
- A behaviour change updates `CHANGELOG.md` (`## Unreleased`), the status line of `docs/testing-standard.md`, and `docs/mech-review-ci.md`.
