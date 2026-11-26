# mech-review CI (adopters)

Reusable workflow: `EricleungDK/ekit/.github/workflows/mech-review.yml`. On each PR it runs up to eight jobs and merges them into one sticky comment (marker `<!-- mech-review -->`) and one check result. `guard`, `red-first`, `baseline` and `mutants` run once per stack to check (a matrix over the stack job's legs, #17): one stack is one leg, with the job and artifact names as before; a [stack plan](#stack-plan) with several stacks runs one set of checks per stack ([several stacks](#several-stacks)):

- Skipped matrix jobs: GitHub lists a skipped matrix job under its name template, the expression unexpanded. So a one-stack repo whose baseline is skipped (no production file changed) shows `mech-review baseline (R3, once)${{ matrix.label }}`, and every one-stack run shows a skipped `mech-review shards (R3, several stacks)`; a job that ran reads as before. Branch protection: a required check named after a job that can be skipped may read differently from the name you set; require `mech-review report`, which never is.
- `stack`: settles `stack` and `project-dir` once (`scripts/mech-review.py resolve`), git only. With `stack: auto` (the default) it takes the stack from the base branch's [stack plan](#stack-plan), else finds the one project from the tracked manifests (the built-ins' and the repo's [adapter files](#stack-resolution)'); a set stack is passed through as is. It also prints the stack's target OS (`target_os`: `linux`, `macos` or `windows`; #58): the base branch's [stack plan](#stack-plan) entry for it, else an adapter file's [`target-os`](#keys) (`resolve --adapter FILE`), else `linux`, as every built-in stack is. Every later job reads the result from this job's outputs: `legs`, one per stack to check (`key`, `label`, `name`, `stack`, `project-dir`, `target-os`, `drift`), is the matrix of the jobs after it. The jobs that run the user's tests (`red-first`, `baseline`, `mutants`) run on the target OS through a fixed map (`linux` → `ubuntu-latest`, `macos` → `macos-latest`, `windows` → `windows-latest`), never the raw value; `stack`, `guard`, `plan` and `report` stay on `ubuntu-latest`. On a runner that is not Linux the `extra-apt-packages` step is skipped.
- `guard`: R2 test-diff guard and the repo's [co-change rules](#co-change-rules) (`scripts/mech-review.py r2`), git diffs only, no toolchain. The [drift check](#stack-plan) (`scripts/mech-review.py drift`, check `D`) runs here too, as its own step before `R2 guard` and its own artifact (`mech-review-drift-json`). [R0's static half](#r0-adapter-proof) (`scripts/mech-review.py r0`, check `R0`) runs right after `R2 guard`, git and adapter only, in seconds; its result rides in the guard's artifact (`mech-review-r0.json` beside `mech-review.json`). For a [parser-backed](#parser) adapter file, the step before `R2 guard` installs the parser the base's copy declares.
- `red-first`: R1 red-first and R4 determinism (`scripts/mech-review.py red`). Compiles and runs the PR's new or changed tests, so it needs the stack toolchain (rust: stable; python: a venv with pytest; ts: node 22 and the repo's installed dependencies). For a [parser-backed](#parser) adapter file it installs the base's parser after `setup-command`.
- `plan`: decides whether R3 runs (a production file changed), per stack, in one job. Git only.
- `baseline`: the R3 baseline, once per PR (`scripts/mech-review.py baseline`). Rust: runs cargo-mutants 27.1.0's unmutated baseline (the tests once) and lists the mutants; sets the shard count (`min(4, mutants, ceil(estimated minutes / (budget / 2)))`, see [R3 cap, risk order and shards](#r3-cap-risk-order-and-shards)) and the per-mutant timeout the shards use. Python (#64): runs the whole suite once and mutmut's listing step, and sets the shard count by the same rule from the suite's measured time (each run within `mutation-budget`, so the step can take about twice it); a baseline that measured nothing keeps one shard per changed production file, at most 4, and says why. ts: the shard count from the changed production files, at most 4 (git only). A baseline that fails or times out is R3's result: the shards do not run. Skipped when `plan` says no production file changed.
- `shards`: several stacks only (skipped for one): each stack's shard count and per-mutant timeout, read from its baseline artifact (a matrix job's outputs are one leg's), as the `mutants` matrix. Git and JSON only.
- `mutants`: R3 mutation on the diff (`scripts/mech-review.py mutants`), one job per stack and shard (the shard count per stack as for one). Runs cargo-mutants 27.1.0 (`--in-diff`, round-robin shards, baseline skipped) on the PR's code (rust), mutmut 3.8.1 on the functions the diff touches in the changed files (python), or Stryker 10.0.0 on the changed lines (ts). Skipped when `baseline` says no shard runs.
- `report`: merges the results (the baseline's R3, or the shards' R3), per stack when there are several, edits the comment, sets the check.

Rules: [testing standard](testing-standard.md). A stack described as data, not code: [adapter file](#adapter-file).

Adopting or repairing: `/ekit:ci-doctor` runs `mech-review.py doctor` and opens the caller PR. A person merges it.

## Caller

Add to your repo. Follow the major tag `v0`: each ekit release moves it, so your repo never needs a bump PR:

```yaml
name: mech-review
on:
  pull_request:
permissions:
  contents: read
  pull-requests: write
jobs:
  mech-review:
    uses: EricleungDK/ekit/.github/workflows/mech-review.yml@v0
    with:
      stack: rust
      test-paths: |
        tests/**
        .ekit/scenarios/**
      protected-paths: |
        .github/**
```

`.ekit/scenarios/**` only when the repo has taste-it scenarios: their fixtures are test support, and outside `test-paths` R3 mutates them as production code (#39). `doctor` names the gap.

`stack` may be left out: `auto` finds a single project by itself. Setting it keeps CI running when a second project appears.

Python: the same, with `stack: python` and `test-paths: tests/**` (`tests/test_*.py` or any layout under `tests/`).

TypeScript / JavaScript: `stack: ts` with `test-paths: src/**/*.test.ts` (or `tests/**`). `.ts .tsx .js .jsx .mjs .cjs` files are this stack; the project dir needs a `package.json`.

The ekit scripts run at the ref you call (`job.workflow_sha` of the called file), not at your checkout.

Releases: the plugin version in `.claude-plugin/plugin.json` is the source of truth. Tagging `vX.Y.Z` (it must match that
version) runs `.github/workflows/release.yml`: ekit's tests, then `scripts/move-major-tag.sh` moves `vX` to the release, forward
only. A caller on `@v0` picks it up on its next PR run. To freeze a repo on one release, pin the exact tag (`@v0.2.4`)
instead; then upgrading is a bump in that repo again.

## Inputs

| Input | Default | Use |
|---|---|---|
| `stack` | `auto` | language adapter: `auto`, `rust` (cargo test, cargo-mutants), `python` (pytest, mutmut) or `ts` (vitest or jest, Stryker). Sets up the toolchain for `red-first` and `mutants`. `auto` finds the one project from the tracked manifests (`Cargo.toml`; `pyproject.toml`, `setup.py` or `setup.cfg`; `package.json`; the shallowest ones, `tests/`, fixture, vendored and build dirs skipped, as `doctor` does), at the PR base and at its head, git only. Several projects, none, or a head that finds a different one than the base: no check runs, and the comment names the projects found and asks for `stack` and `project-dir`. It never guesses. With `project-dir` set, only that dir is read. With a [stack plan](#stack-plan) on the base, the stacks come from it and nothing is detected; without one, the repo's adapter files in `.ekit/adapters/` are detected too ([stack resolution](#stack-resolution)) |
| `test-paths` | `tests/**` | test file globs, one per line; `.rs` files here count every assert; a `.rs` file outside them is production code for R1. A repo with `.ekit/scenarios/` adds `.ekit/scenarios/**` (ci-doctor writes it; `doctor` gives an `env` entry when a file of the stack there is not covered) |
| `protected-paths` | `.github/**` | globs, one per line; any change under them is a `needs-human` fail |
| `agent-branch-prefix` | `agent/`, `claude/`, `codex/`, `copilot/`, `cursor/` | prefixes, one per line: R1 runs only when the PR head branch starts with one of them (`--agent-prefix`, repeatable); other branches skip R1. `*` runs R1 on every branch. A value you set replaces the default list |
| `mutation-budget` | `10` | R3 budget in minutes, per mutants shard and for the baseline step (python: the suite run and mutmut's listing each get it, so the step can take about twice it). A budget hit is `partial` (no MISSED so far) or `fail` (a MISSED found), never a crash; a rust baseline that does not finish in it is `n/a`, a python one keeps one shard per changed file and says why. Applies to all stacks |
| `max-mutants` | `40` | R3 cap: the most mutants tested per PR, riskiest first (see [R3 cap, risk order and shards](#r3-cap-risk-order-and-shards)). The rest are untested: R3 reads `partial (tested/total)`, never `pass`. rust and python by mutant; ts by changed line, riskiest first, the mutants counted by Stryker's own instrumenter before the run (#63; without it, or with a repo Stryker config that is code, the cap is not applied and the note says so) |
| `extra-apt-packages` | `` | apt packages (space-separated) installed in `red-first`, `mutants` and (rust, python) `baseline`, before the tests run; Linux runners only (skipped on a macOS or Windows target OS) |
| `project-dir` | `.` | crate dir under the repo root (`package.json` for ts). With `stack: auto` and `project-dir` left at `.`, the dir found is used; a dir you set is never replaced (`.` set by hand reads as left at the default). R1, R4 and R3 run there; `test-paths` and `protected-paths` stay repo-root globs; a path with `..` or a leading `/` is a usage error |
| `setup-command` | `` | shell command (run with bash) in `red-first`, `mutants` and (rust, python) `baseline`, after `extra-apt-packages`, before the tests. A non-zero exit stops that job, which then reports a CI entry |
| `mutant-timeout` | `` (derived) | R3 per-mutant timeout in seconds. Empty is the timeout derived from the measured baseline: 5× its test time, at least 20 s (cargo-mutants' own rule; `timeout_multiplier` and `minimum_test_timeout` are read from the crate dir's `.cargo/mutants.toml`, not a workspace root above it). A set value is used as is. Neither caps the baseline: it runs once, in the `baseline` job, bounded by `mutation-budget`. Stryker's `timeoutMS` is 120 s when unset |
| `rust-toolchain` | `stable` | Rust toolchain for `red-first` and `mutants` (rust stack), passed to the toolchain action, e.g. `1.96.0` to pin a repo |

Globs: `**` any depth, `*` one segment.

Linked issues (#53, no input): `r2` and `all` take `--linked-issue N` (or `#N`, ASCII digits, N >= 1), repeatable, one per issue the PR closes; another subcommand given it is a usage error. A caller's workflow must pass the PR's closing issues (GitHub's `closingIssuesReferences`), e.g. `--linked-issue 53 --linked-issue 61`; until the workflow passes them, R2 keeps the `fail`. A removed test is one R2 `confirm` (problem "test `<name>` removed, spec #N reverses it", key `spec-removed:<name>`) instead of the `fail` when a line of a commit message in merge-base..head reads `spec: #N reverses <name>`: N linked, `<name>` R2's exact name for the test (`Class::test_fn` in python, the qualified name elsewhere), one line per test; several linked lines for one test use the lowest N. No linked issue, an unlinked N, another name, or one name removed from several files: the `fail` stays. The reviewer confirms only against a quoted sentence of #N that reverses the test's assertion, else the test is restored. It waives nothing ([waivers](#waivers)).

Subdirectory crate (`project-dir`): `test-paths: crates/app/tests/**`, `project-dir: crates/app`. Tests and cargo-mutants run in that dir; results name files from the repo root (`crates/app/src/x.rs`).

`setup-command` is for host setup a test needs and `extra-apt-packages` cannot do, e.g. an AppArmor sysctl for bubblewrap:

```yaml
    with:
      setup-command: sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 || true
```

Trust: `setup-command` and `project-dir` come from the caller's workflow file, which is trusted: the command runs with the job's `contents: read` token and no secrets. For `pull_request` the caller file is the PR's own, so a PR that edits it changes what the job runs. Keep that file behind review: `.github/**` in `protected-paths` reports such an edit as `needs-human`, but the job runs before a human reads it. Both inputs are passed through `env` and never interpolated into a `run:` line. The command runs at the workspace root, before the PR's tests.

Python toolchain (`stack: python`), set up in `red-first` and `mutants`:

- A venv from the runner's python (`$RUNNER_TEMP/py-venv`), so PEP 668 does not apply. `pytest` 9.2.0, and in `mutants` `mutmut` 3.8.1. Both pinned.
- The `requirements*.txt` files in the project dir (`project-dir`, default the repo root) are installed with `pip -r`. A requirements file that does not install stops the job: a missing dependency is never a silent pass. `project-dir` must stay under the repo root.
- Installing the project is left to `setup-command`, which runs after this step with the venv on PATH, e.g. `setup-command: python3 -m pip install -e caller` (the checkout is `caller/` under the workspace root; with `project-dir: pkg`, `caller/pkg`).
- An editable install imports the checkout's copy. A flat layout is safe: the runner starts in the worktree, so its package comes first on `sys.path`. A `src/` layout is not: on the base's checkout R1 would import head's code. Use pytest's `pythonpath` setting for a `src/` layout instead, and skip `setup-command` for it.
- Test runner: `python3 -m pytest` (one nodeid per test, so unittest `TestCase` methods run too). Use `--test-cmd` for another command: a command with `unittest` in it gets dotted names.
- A python project dir needs one of `pyproject.toml`, `setup.py` or `setup.cfg`. Without one R3 is `n/a` and names `project-dir`, and a test that cannot run names it in its hint. `pytest` missing is `n/a (env)`, and its note names `setup-command`.

## Result

- Jobs: `guard` (artifact `mech-review-json`), `red-first` (artifact `mech-review-red-json`), `plan`, `baseline` (artifact `mech-review-baseline-json`), `shards`, `mutants` (artifacts `mech-review-mutants-<shard>`), `report` (`needs` all of them, runs even if one fails). With several stacks each artifact name but the drift one carries the stack's key (`mech-review-json-0-api`, `mech-review-mutants-1-web-0`).
- `report` merges the results: each job owns its checks (R2 from `guard`; R1 and R4 from `red-first`; R3 from `mutants`; `D` from the drift result, `--envelope drift=FILE`). The shard results are combined by `mech-review.py merge` first. It edits the sticky comment, or creates it: a summary line, a table of entries (id, severity, file:line, problem, forbidden) and the full JSON.
- A job with no usable result (crash, no JSON, or a result for an older head) fails its own checks and adds one `CI` entry naming the job. The other job's entries still show.
- Check fails on any `fail` entry, or any check whose status is `fail` (`confirm` and `waived` entries do not fail). A job's `CI` entries (a missing or mismatched mutants shard, no baseline result) are kept in the merged result and listed in the comment.
- A `fail` entry of class `needs-human` reads `needs-human` in the comment (severity cell, and the headline when every fail entry is needs-human). The JSON keeps `severity: fail` and the summary keeps `fail`; the check stays red.
- R1 on a non-agent branch, or a PR with no production file changed, is `skipped` and named as such. A missing toolchain is `n/a` (not run, not pass). Each `n/a` note names the cause and the input to set (`setup-command` for a toolchain, the install step for cargo-mutants, `project-dir` for no manifest: `Cargo.toml` for rust, `pyproject.toml`, `setup.py` or `setup.cfg` for python), and the comment adds one line under the headline: `Did not run: R3 (no Cargo.toml in .: set project-dir)`. A missing manifest where R1 or R4 runs is a `fail` (cannot run), with `set project-dir` in its hint.
- Check `D` (the [drift check](#stack-plan)) is in the result only when the repo has a stack plan on base or head: then the summary names it (`ran: R1 R2 R4 D`), the comment adds one `Stack plan:` line per message under the headline, and `all pass` needs it to pass. A repo with no plan reads exactly as before, with no `D` anywhere; so does a run with no drift result (the drift step leaves one on every run whose refs resolve, and stops the guard job before R2 when it cannot: [guard wiring](#stack-plan)).
- Summary: `all pass <sha>` only when every check ran and passed. A run with R3 skipped (no production file changed) reads like `pass <sha> (0 fail, 1 confirm; ran: R1 R2 R4; skipped: R3)`. A budget hit reads `partial: R3 (tested/total)`, and an absent tool reads `n/a: R3`; neither is `all pass`.
- Check `R0` (the [adapter proof](#r0-adapter-proof)) is in the result when the guard ran it (`--envelope r0=FILE`, always named, so a missing one fails `R0` with a `CI` entry): the summary names it first (`ran: R0 R1 R2 R4`), the comment adds an `R0:` line with its note, and `all pass` needs it to pass. A result without it (`r2`, `red`, an older run) reads as before.
- Require the check `mech-review report` in branch protection.
- Readers trust only the bot's marker comment (`github-actions[bot]`, override `MECH_COMMENT_AUTHOR`): a `<!-- mech-review -->` comment from any other user is ignored.
- A run whose PR head has moved on leaves the comment alone; the newest push owns it.

TypeScript toolchain (`stack: ts`), set up in `red-first` and `mutants`:

- `actions/setup-node` (pinned to a full SHA, node 22). The install in `caller/<project-dir>` follows the lockfile: `npm ci` for `package-lock.json`, the repo's `pnpm` (10.34.6) or `yarn` (1.22.22, classic) for theirs, both pinned through `npx`. No lockfile is a stop: the install must be reproducible. Install scripts run, as the test code does; the job's token is read-only.
- The tests run the repo's own runner from its `node_modules/.bin`: `vitest` or `jest`, chosen from `package.json` (vitest when it lists vitest, or neither). A worktree has no `node_modules`, so the engine links the caller checkout's `node_modules` into the worktree's crate dir (never over an existing one; the caller's copy is not touched). A runner that is not installed is `n/a (env)`, named by its `node_modules/.bin` path.
- Named tests: `vitest run <file> -t '^Describe > test$'`, `jest <file> -t '^Describe test$'` (jest joins names with a space). A test name is matched anchored, so `describe("A") > works` and `describe("B") > works` are two tests. `it.each` placeholders match any value.
- Outcomes: a filter that runs nothing is `none` (never a pass, also at exit 0). A file that does not load (transform, missing import, syntax) is `build`: R1 compile-red (red) on the base's code, an R4 fail at head.
- The test command: `--test-cmd` overrides it (a vitest command gets `run` inserted; a command with `jest` in it gets jest's argv).
- Stryker is installed into the runner temp dir (`@stryker-mutator/core@10.0.0`, `@stryker-mutator/jest-runner@10.0.0`), not the repo's `node_modules`. A failed install is not a stop: R3 is `n/a (env)`.
- Test files are `.ts`/`.js` files matched by `test-paths`; a test is `it`/`test` (and `.each`, `.skip`, `.only`, `.todo`, `xit`, `fit`, `xtest`, `ftest`) inside `describe` or at top level.

## Python R3 (mutmut)

- The runner appends a `[tool.mutmut]` table (`source_paths`, `only_mutate` = the changed production files; every shard lists them all) to the worktree's `pyproject.toml`. The caller's checkout is never written. A `setup.cfg` `[mutmut]` section is ignored once the table exists.
- mutmut runs the tests inside its own copy, `<project-dir>/mutants/`, and copies there only `source_paths`, its defaults (`tests/`, `test/`, `setup.cfg`, `pyproject.toml`, the `uv`, `poetry`, `Pipfile` and `pdm` lock files, root `test*.py`) and `also_copy`. So the table also sets `also_copy`: every other git-tracked top-level entry of the project dir at head (`docs/`, `config/`, `scripts/`, `README.md`, a root `conftest.py` or `pytest.ini`). Then a test that reads `docs/x.md` or loads `scripts/x.py` relative to its own `__file__` finds it in the copy, as it does in R1 and R4. The list comes from git, so untracked files (`.venv`, caches) are never copied, and `mutants/` and the source entries are never listed (a copied source dir would overwrite the mutated files on the second `mutmut run`). An entry holding a symlink that does not reach a tracked file inside the project dir (dangling, to a dir, or through another link) is left out: mutmut's copy follows links and stops on a dangling one, or loops on a link to a parent dir. Root test config (`pytest.ini`, `tox.ini`, `conftest.py`) now applies in R3 as it does in R1: a plugin it names belongs in `setup-command`. The copy is local, twice per shard, never per mutant.
- `doctor` checks this before CI does. For python, when the suite passes in the trial worktree, it runs it once more in a fresh worktree inside a copy built the way mutmut's is (`<project-dir>/mutants/`, the sources and `source/`/`src/` first on the import path, `-p no:randomly -p no:random-order`). `trial.sandbox` is `pass`, `fail` or `skipped` (the plain run did not pass). A suite that fails only there gives one `env` entry, never `ok`. The entry names the paths missing from the copy, and any link that keeps a top-level entry out of it. A link under `tests/` that dangles, loops, or points into one of the repo's checkouts by an absolute path, which would stop or hang mutmut's copy or dangle in CI, is named without copying. Cost: one more checkout and suite run.
- mutmut has no line filter: it writes mutants for every function of the changed files. The runner therefore runs it in two steps. First `mutmut run` with a filter that matches no mutant: mutmut writes the mutants, records which tests reach which function, and runs none. The mutant names say which function each belongs to, and only the mutants of functions that hold a changed line are run in the second step (`mutmut run 'pkg.mod.x_fn__mutmut_*' ...`). Past `max-mutants`, or on a shard, the step names its own mutants one by one instead (see [R3 cap, risk order and shards](#r3-cap-risk-order-and-shards)). A large file touched in one place costs the touched functions, not the file. Both steps share one `mutation-budget`.
- Of those, only the MISSED mutants on changed lines are reported, the same promise as `--in-diff`. The line comes from mutmut's own files under `mutants/`: each mutant is a whole copy of its function, so its first changed line is an offset from the function's `def` line in the head source. `mutmut show` is asked only for a mutant those files do not explain; its diff text is then searched for in the function. A MISSED mutant on an unchanged line of a touched function is counted in the note (`N missed outside the diff`); the mutants of untouched functions are counted too (`N in functions the diff does not touch: not run`). Before any mutant runs, the same changed-line rule, read from mutmut's copies, leaves out the mutants on unchanged lines of a touched function: they could never become a finding, so they take no cap slot and do not run (`N on unchanged lines of touched functions: not run`). `tested` and `total` count the mutants on changed lines of the touched functions, plus any the copies cannot place on a line (those stay candidates, and run). So `N missed outside the diff` now counts only a mutant the copies could not place before the run and `mutmut show` placed off the diff after it.
- mutmut credits a test with a mutant only when the test calls the function inside mutmut's own process, under the module name mutmut derives from the file path. A test that starts the program as a subprocess, or imports the file under another name, is not credited: its lines read `no tests`. So each mutant still MISSED on a changed line gets one more try. `mutmut apply` writes it into the worktree, the whole suite runs once (`python3 -B -m pytest -x -q -p no:cacheprovider --ignore=mutants`), and a failing suite has caught it; the file is put back each time. The note counts them (`N more caught only by the whole suite`): a visible nudge towards a test that calls the function, not a blocker. A suite that is red without any mutant is not used (the job log says so). One suite run on a mutant may take 5× the clean run (at least 30 s); one that takes longer is counted as hung, neither caught nor missed. The whole step shares `mutation-budget`. A mutant whose retry the budget does not reach, or cuts short, is an **unconfirmed survivor** (#79): untested, so out of the tested count, and R3 reads `partial`; the note counts them (`N unconfirmed survivors (budget hit before the whole-suite retry): untested`). So is every mutant mutmut reports surviving when the budget ends mutmut's own run. Each one is an entry of its own: check R3, class `agent-fixable`, severity `confirm`, file and line, problem `R3 unconfirmed survivor <file>:<line>: <mutation>`, field `unconfirmed: true` (what `r3-local.py` and the partial entry count), and the id a MISSED entry of the same mutation has (key `missed:<file>|<mutation>`), so it is stable across heads and a waiver or a tracking line carries over between machines. A `confirm`, not a `fail`: a slow runner does not turn the check red, and among the mutants mutmut ran, the set R3 names (MISSED plus unconfirmed) is the same on every machine; only the split between the two depends on its speed. A mutant mutmut never ran, because the budget ended its run first, is not named: the partial entry counts it as untested. Read one as a MISSED mutant until a test kills it: add that test, or give R3 the budget to confirm it. A flaky test in the suite can give a false catch here; R4 is the check for flaky tests.
- A mutant of a touched function that mutmut leaves unrun without a budget hit makes R3 `partial`, never `pass`. A method is located inside its class (mutmut names it `Class` + U+01C1 + `method`), so a method name that two classes share is found in the right one. A missed mutant whose name maps to no line in the file is `unlocated`: one `confirm` entry, not a fail and not a silent pass, counted in the note (`N unlocated`) for a reader to check by hand.
- `no tests` (no test reaches the line) is a MISSED mutant: the fix is a test that calls it. Survived mutants are MISSED. `timeout`, `suspicious` and similar are neither caught nor missed, as TIMEOUT and UNVIABLE are for cargo-mutants.
- Timing is wall time only (`checks.R3.timing.wall_s`): mutmut prints no per-phase durations, so the cargo-mutants phase fields are left out, not guessed. `--mutant-timeout` does not apply: mutmut's own timeout (its `timeout_multiplier` times the test time) decides.
- A budget hit reads the results mutmut kept: `partial (tested/total)`. A mutant mutmut reports missed before the budget ended its run has had no whole-suite retry, so it is untested too.

## R3 locally

### Developer machine

mech-review's checks run on the CI runner. What runs on a developer's machine is the plugin (hooks, `scenarios.py`, `task-verify.py`, `finish-gate.py`, `preflight.py`) and `doctor` (ci-doctor): those work on macOS, Windows and Linux with Python 3.9+ and Git. Each hook starts the first of `python3`, `py -3`, `python` that is 3.9+ (`scripts/launcher.py`), in `sh`, Git Bash or PowerShell, and reads the plugin dir from the `CLAUDE_PLUGIN_ROOT` env var. The unit tests fake the shells and the process table and run on every OS; what needs a real PowerShell or Git Bash is `tests/windows-smoke.py`, run on Windows only (the `hooks-windows` job): on Linux and macOS that part is verification debt. On Windows `doctor` names paths with `/` like the CI runner does. Its sandbox trial copies the way mutmut does; mutmut runs on POSIX only, so the CI runner (Linux) stays the judge of R3. Scenarios (`scenarios.py`) take one run file each: `run.py` runs with the Python the hooks found (no shell needed), `run.sh` with bash (Git Bash on Windows, never WSL's), `run.ps1` with `pwsh`, else Windows PowerShell (its exit code is the script's own `exit N`, else 1 when an error stops it, else the last native command's exit code (0 if none ran); not bash's last-status rule, so a run.ps1 that handles a native command's failure ends with `exit 0`; a path holding `[ ]` goes to pwsh as it is and to Windows PowerShell 5.1 escaped, the 5.1 form checked by reading PowerShell's source only); a host without that shell reads the scenario `NOT-RUN <id>: <shell> is not on this machine (env)`, which `check` reports as `cannot run here` and the Stop gate takes as verification debt with `## Finish: blocked`. For every run file a timeout stops every descendant and is a FAIL (POSIX: each found by parent pid, own-session children and theirs included, then the process group; Windows: the job object, which holds every descendant), a background child is stopped with its scenario at a normal exit (on POSIX an own-session child that outlives a normal exit, an orphan, is not tracked), untracked Python bytecode is no repo change, a failed transcript is kept, and artifacts are listed. A `- feature: <name>` line in a scenario's SCENARIO.md (taste-it's seeded scenarios, #60; outside fenced blocks and HTML comments (opened where `<!--` starts a line); two, a top-level `-` field keyed `feature` in another form, a fence or comment left open above one, or an unreadable SCENARIO.md are a named FAIL; Gherkin's `Feature:` and nested bullets are text) marks its feature: an unfiltered `run`, and `check` for a full run on the files as they are, end with `N of M features working` (N: features, case and spacing aside, whose scenarios all PASS; none in a run that modified the repo; no line when none is marked), after `check`'s verdict line. `seeded <id>` runs a scenario and its children on the files as they are and writes no results.json: `SEEDED ✓` with the reason and the last line it wrote (stderr, else stdout) when it fails (transcript kept), `CHECKS NOTHING YET` when it passes (exit 1), `N/A` (env, exit 4), `ERROR` for a missing, empty or bad feature line, two run files or a write into the repo, naming what changed (exit 2); a write is found from git status and HEAD, not a tree hash per scenario. R3's runner stops an over-budget run with `SIGTERM` where the OS has no process groups. `MECH_TEST_STUB` (the test seam that replaces the toolchain) may be a `.py` file: it runs with the engine's Python.

What needs python 3.11 or newer (`tomllib`), everything else running on 3.9+: reading an adapter file (`--adapter`, a usage error that says so on older pythons), reading a crate's `.cargo/mutants.toml` (rust R3, a clear error), and reading a [stack plan](#stack-plan) (`drift`, a usage error; at session start one `[ekit] Stack plan:` line says the drift check needs 3.11+ and that CI still runs it, the other session lines unchanged). A repo with no plan needs none of it. On 3.9 and 3.10, R2's mutation-config rule for python compares the text of pyproject's `[tool.mutmut]` table (and its subtables, comments and blank lines left out) in place of its parsed value: an edit elsewhere in the file (a version bump) is no mutation-config change on any python.

`scripts/r3-local.py` runs the R3 jobs of this workflow on your machine, so a MISSED mutant shows before the review request, not after CI. POSIX only: on Windows run it in WSL (native Windows exits 2).

```bash
python3 -I scripts/r3-local.py --base origin/main --stack python --test-paths 'tests/**' --mutation-budget 20 --env-dir ~/.cache/ekit-r3env
```

- Setup: the stack's R3 tool with the workflow's pins (the adapter's `r3_tool`): python a venv with `pytest==9.2.0` and `mutmut==3.8.1`, then the project dir's `requirements*.txt`, installed from a checkout of head (`git archive`; pip runs in the project dir there, as CI does, so `-c`, `-r ../x.txt` and `-e .` resolve the same; a link in the tree that points out of the checkout is left out and named on stderr: CI keeps it and never follows it), the venv first on `PATH` (`PYTHONPATH` and `PYTEST_ADDOPTS` are dropped: CI has neither); ts `@stryker-mutator/core@10.0.0` and `jest-runner` in their own npm prefix, passed as `--mutants-cmd`; rust `cargo install cargo-mutants@27.1.0` and the workflow's cargo env. `--env-dir` keeps it and reuses it while the pins and the requirements files match; without it a temp dir is removed after the run. One run at a time holds an env dir (a `flock` on `.ekit-r3-env.lock`): a second run on it stops with exit 2 before any step, naming the first run's pid, so two runs never overwrite each other's tool or results (spec #78's run: two agents shared one env dir). The lock goes when its run ends, killed or not. `setup-command` and `extra-apt-packages` are not run: install those yourself.
- Steps: `plan`, `baseline --shards 4`, every shard at the same time (`mutants --shard K/N`, the CI budget and `max-mutants` each, `--mutant-timeout` or else the baseline's), `merge`. Defaults are the workflow's (`test-paths` `tests/**`, budget 10, `max-mutants` 40); pass your caller's inputs: `--test-paths` (repeat), `--mutation-budget`, `--max-mutants`, `--mutant-timeout`, `--project-dir`. The shards share this machine's CPUs, where CI gives each its own runner: wall times differ, and so can a mutant that hits mutmut's own timeout.
- Output: the merged summary, R3's status (`tested/total`), each shard's note and wall time, the fail entries, then each unconfirmed survivor (`unconfirmed <id> <file>:<line> <problem>`); the results are in `<env-dir>/out/` (without `--env-dir` they are removed, and the output says so). It tests the head commit: uncommitted changes are not in it.
- Exit 0 no fail entry and no unconfirmed survivor, 1 a fail entry or an unconfirmed survivor (#79: the merged result exits 0 then, the local run does not, so it cannot be read as `0 MISSED`), 2 setup failed, usage or git error, the env dir in use by another run, a step gave no usable result, or native Windows.

ekit's own development (not part of the plugin, #84): `python3 scripts/ci-local.py --base origin/main [--head-branch NAME] [--r3-env-dir DIR]` runs what CI runs on ekit's PRs, in order, with the inputs of `mech-review-self.yml`. `mech`: `mech-review.py all` with the checkout's own engine (beside the script, never an installed copy), `--stack python`, both test paths, `--protected-paths '.github/**'`, `--r0` with a fresh temp dir (R0's runtime half, as the `red-first` job runs it on a cache miss), and `--agent-prefix '*'` (a local branch is often not named as the PR's). `suite`: `python -m unittest discover -s tests/py` on CI's Python 3.14 through `uv run --no-project` (no `uv.lock` and no `.venv` in the repo; one the run leaves there fails the step). `r3`: `r3-local.py` with `--mutation-budget 20`; a fail entry or an unconfirmed survivor fails it. Each step ends as `<step>: passed|failed|not run here: <detail>`: no `uv`, no Python 3.14 for it, an `n/a` check, an engine or `r3-local.py` exit 2 are `not run here`, never a pass. Exit 0 every step passed, 1 a step failed or did not run here, 2 usage or a base that is not a commit (no step ran). It runs as root in a cloud session as is. No other OS is simulated: the macOS job stays CI's.

## Reading a run

`scripts/mech-summary.py <run-id | PR number | #N | PR URL> [--repo OWNER/NAME]` downloads a run's artifacts (`gh run download`; a PR resolves to the run of its newest `mech-review report` check) and prints the summary line, each check's status and note, each shard's note, and the fail entries grouped by file, merged as the report job merges them. Waivers are not applied. `--dir DIR` reads artifacts already downloaded. Artifacts: `mech-review-json` (R2), `mech-review-red-json` (R1, R4), `mech-review-baseline-json`, `mech-review-mutants-K` (one per shard); a `mech-review-mutants-merged-json` (the merged R3) is used when the run has one. A run still in progress is a note (exit 2), not a result. The job list (`gh run view`) tells a baseline job that was skipped (the plan found no production change: R3 skipped) from one that ran and left no JSON (R3 fails, as in the comment).

`scripts/verified-commit.py [--allow-behind] [--expect SHA] RESULT WORKTREE` (#81) checks that a result describes the commit you act on: its `head` must be the worktree's HEAD and, when the branch is pushed, the branch's tip on its remote (its upstream, else `origin/<branch>`, asked with `git ls-remote`: a remote-tracking ref may be stale). `RESULT` is the envelope `mech-review.py` prints (`-` reads stdin). A detached HEAD, a missing remote or a branch the remote lacks is not pushed. `--allow-behind` also accepts a remote tip that is an ancestor of the result's head (verified fixes not pushed yet); a tip this clone lacks is refused (fetch, then rerun); it is deliberate: the relay verifies fixes before they are pushed (#81). `--expect SHA` (#78 §4): the head the review request names (full or short, resolved in the worktree) must be the result's head too; another commit is refused, both named, and a SHA that names no commit there is no answer. Exit 0 the same commit; 1 another commit, both named; 2 no answer, with its reason: a result that cannot be read or has no commit SHA `head`, a path that is not a git worktree, an `--expect` that names no commit, a remote that cannot be asked. The orchestrate-agent skill runs it before the review (with `--expect` the review request's head) and before a push.

The merged R3 artifact comes from this step in the `report` job, right after `merge mutants (R3, baseline and shards)` (#38). It uploads the single-stack `mutants-merged.json`; a run with several stacks writes one `mutants-merged<key>.json` per stack, which it leaves out:

```yaml
      - name: upload merged mutants result
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: mech-review-mutants-merged-json
          path: mutants-merged.json
          if-no-files-found: ignore
          overwrite: true
```

## R3 timing and partial

`checks.R3.timing` (JSON, additive) says where the R3 time went. Per shard it comes from cargo-mutants' own `outcomes.json` phase durations (`Build`, `Test`, in seconds) and the runner's clock:

- `wall_s`: wall time of the cargo-mutants run on this shard.
- `baseline_build_s`, `baseline_test_s`: the unmutated baseline, measured once by the `baseline` job (rust) and added to the merged result once. A shard does not repeat it.
- `mutant_build_s`, `mutant_test_s`: summed over the tested mutants. A mutant that fails to build has no `Test` phase and adds 0 to it.
- `avg_s_per_mutant`: (`mutant_build_s` + `mutant_test_s`) / tested.
- `slowest`: the five slowest tested mutants, `{name, s}` (`s` = its build plus test seconds).

Merged (`merge`): `wall_s` is the slowest shard, since shards run in parallel. Sums and the average are kept only when every shard reported them; a shard that tested nothing counts as zero, so it does not drop them. A shard that crashed does drop them. `shards` lists each shard's `wall_s`, so an uneven shard shows. `slowest` is the top five across shards. A field that is missing or not a number is left out, never guessed. A budget-killed run reports what finished. Entries are one per id across shards: an identical repeat collapses; a different entry that shares an id keeps both, the later one under a new id, so no fail is lost.

The comment prints one line under the headline when R3 ran, e.g. `R3 timing: 6/15 mutants, 3.07s wall, avg 0.25s per mutant (build 1.21s, test 0.3s), baseline (build 2s, test 90s)`; the baseline part is left out when the baseline did not measure it. When nothing was tested the count is left out and the line is wall time only, e.g. `R3 timing: 1.2s wall`. When R3 is partial it adds `R3 slowest:` with the five slowest. Mutant names come from the PR's code, so they pass through the comment's cell rules (pipes escaped, backticks replaced).

Baseline (rust, #46): the `baseline` job runs cargo-mutants' unmutated baseline once, before the shards. The shards run with `--baseline skip` and an explicit `--timeout` (cargo-mutants' `--baseline skip` takes no timeout of its own: without `--timeout` it falls back to 300 s with a warning). The baseline's tests are bounded by `mutation-budget` only. A baseline that does not finish in the budget is `n/a` (timed out; no shard runs; raise `mutation-budget`). A baseline test failure is `fail` (agent-fixable), with the log tail in the job log. The baseline's build and test seconds appear once in `checks.R3.timing` and in the comment line, not per shard.

To measure the baseline alone, `baseline` lists the mutants (`--list --json`) and runs one of them with `--build-timeout 0`, so its build is killed at once and only the baseline runs. Within `max-mutants`, shards are cargo-mutants' round-robin (`--sharding round-robin`) over its own list, so their mutants are spread and no shard is empty; past it, see [R3 cap, risk order and shards](#r3-cap-risk-order-and-shards).

On any non-pass R3 (rust) the job log gets the last 40 lines of cargo-mutants' `log/baseline.log` on stderr, so the cause shows without downloading the artifact. stdout stays the JSON.

A partial R3 adds one `confirm` entry: class `agent-fixable`, id `R3-…` (stable across heads, counts and causes), problem `R3 partial: <untested>/<total> mutants untested: <causes>` (or `total unknown` when the mutant list was never written). The causes, in this order, as many as apply (#79): `past the cap` (`max-mutants` left mutants out; hint: shrink the diff, or raise `max-mutants` for a deliberate deep run), `budget hit` (hint: the timing steps below, ending with raising `mutation-budget`), `N unconfirmed survivors` (hint: kill each one with a test); with none of these, `left unrun by the mutation tool` (its note and log say why). The hint to raise the budget comes only with `budget hit`. One entry per run, however many shards are partial; the merged entry names every shard's causes. The check stays green and the exit code stays 0: partial never fails.

What to do with the numbers, in this order:

1. Smaller diff. `untested × avg_s_per_mutant` estimates the extra seconds the shard needs. If that is far above the budget, the diff covers too much for one run: split the change.
2. Narrower tests. If a few mutants dominate `slowest`, their tests are slow for each mutant. Make those tests faster or narrower; the slow test runs once per mutant.
3. Raise `mutation-budget` last. If `baseline_build_s` and `baseline_test_s` are large against `wall_s`, the fixed per-shard cost is the problem: a bigger budget only buys more mutants.

## Waivers

Some `fail` entries are a person's call: a protected-path change in a PR that is meant to change CI, a test the owner wants gone, an equivalent mutant. A person with write access lets one entry through with a PR comment:

```
/mech-waive R3-1a2b3c4d: equivalent mutant, the branch is unreachable
```

- Ready-made lines: the sticky comment shows, under each `fail` entry, the line to post (`/mech-waive <id> <why this is OK>`), plus one block with every fail entry when there are several. Copy it, replace `<why this is OK>` with the reason, post it.
- One line per entry id, at the start of a line, with a reason. A waiver with no reason, or with the placeholder left in its angle brackets (`<why this is OK>`, `<reason>`, `<…>` or `<>`, whatever the case, spacing, doubled brackets or zero-width characters), is ignored, and the sticky comment says so, naming the angle brackets. A reason left inside the brackets (`<the test moved to e2e>`) counts, brackets stripped (#40). Several lines may share one comment.
- Who: comments whose author is `OWNER`, `MEMBER` or `COLLABORATOR` of the repo, and not a bot. These are GitHub's author associations, not permission levels: `COLLABORATOR` includes an outside collaborator with read or triage access, and `MEMBER` any member of the owning org. The PR's own content (body, commits, files) can never waive: that is what the checks judge. A `spec: #N reverses <test>` commit line ([linked issues](#inputs), #53) is no waiver: it turns a removal into a `confirm` a reviewer decides against #N. The sticky comment itself (`<!-- mech-review -->`) is never read for waivers, whoever posts it.
- Edited comments do not waive. Anyone with write access can edit anyone's comment while the author shown stays the same, so a comment edited after posting (`updated_at` ≠ `created_at`) is ignored, and the sticky comment says so. To change a waiver, post a new comment. The stamps have one-second resolution: an edit within the same second as the post is not seen.
- When: the `report` job reads the PR's comments each time it runs. With the [waiver re-run caller](#waiver-re-run) set up, posting, editing or deleting a `/mech-waive` comment re-runs `report` on its own. Without it, re-run the run's failed job (`report`, the only one that fails on entries), or push: the next run picks the waiver up.
- Effect: the entry's `severity` becomes `waived` and it gains `waiver: {by, reason, url}`; a check whose fail entries are all waived reads `waived`; the summary counts it (`0 fail, 0 confirm, 1 waived`); the comment says who waived what and why. A waived entry does not fail the check. `all pass` is never printed over a waiver.
- Scope: a waiver is for one entry id. Ids are stable across pushes (rule + file + test name), so it holds while that same thing stays broken and falls away when the id does. To withdraw one, delete the comment and re-run.
- Ids: `R1-…` to `R4-…`, and `D-…` for the drift check's entry ([stack plan](#stack-plan)): its id holds the uncovered manifests, so a waiver holds while the same ones stay uncovered and falls away when the set changes, grown or shrunk. A waiver is per PR: once a waived drift entry merges, every later PR fails `D` until the plan covers the manifest.
- Not waivable: `CI` entries (a job with no result). Fix the run instead.
- Agents do not waive. The skills hand a `needs-human` entry to the user as a Needs-you block; the command above is what the user posts if the answer is yes.

Trust: GitHub attributes a comment to the account that posted it, so an agent that holds your token can post as you. Give agents a token of their own (a bot or app account is never a waiving author), and the waiver stays a person's act. Every waiver is visible in the PR comment with its author.

### Waiver re-run

A second caller makes a waiver comment re-run `report` by itself (reusable workflow `mech-waive.yml`, script `scripts/mech-rerun.py`):

```yaml
name: mech-waive
on:
  issue_comment:
    types: [created, edited, deleted]
permissions:
  actions: write
  pull-requests: read
  contents: read
jobs:
  mech-waive:
    uses: EricleungDK/ekit/.github/workflows/mech-waive.yml@v0
```

- It runs only for a PR comment that contains `/mech-waive`, from an `OWNER`, `MEMBER` or `COLLABORATOR`, not from a bot, and not the sticky comment itself (its ready-made lines never trigger a loop).
- It finds the newest `pull_request` run for the PR head with a `mech-review report` job. A finished run: that job is re-run. A run still going: nothing to do, its `report` reads the comments when it gets there. No run for the head: a notice, nothing else.
- It never checks out or runs PR code: the ekit scripts only, at the ref you call. Its token can re-run jobs (`actions: write`) and read the PR, nothing else.
- GitHub runs `issue_comment` workflows from the default branch only: the caller works once it is merged there.
- A comment posted while a re-run of `report` is already in progress may be read too late by it. If the check does not change, re-run `report` by hand.

## TypeScript R3 (Stryker)

- Stryker 10.0.0 runs on the changed lines only: each changed run of lines is a `--mutate file:start-end` range. Stryker mutates the mutants fully inside a range, so the MISSED list is already the diff; a mutant outside it is counted in the note, not a fail. Class methods are mutated like any other lines.
- vitest, with no repo Stryker config: a temp `stryker.conf.json` is written into the worktree (the caller's checkout is never written) that runs `npx --no-install vitest run` per mutant with `coverageAnalysis: off`. Stryker's own vitest plugin (`@stryker-mutator/vitest-runner` 10.0.0) completes no test for a test nested in `describe` on vitest 5.0.5 (checked: the mutants read as survived with 0 tests run); vitest 4.1.12 with the same Stryker kills them. The command runner is correct on vitest 5, at the cost of running the whole suite per mutant.
- jest, with no repo config: `--testRunner jest` (the jest plugin, per-test coverage; checked on nested describes).
- A repo with its own Stryker config (`stryker.conf.*`, `stryker.config.*`) keeps it: Stryker reads it, and `mutate`, the reporter and the timeout are set on the command line, which wins over the file. The test runner comes from the repo's config. The JSON report is read from Stryker's default `reports/mutation/mutation.json`; a repo that moves `jsonReporter.fileName` gets `n/a (env)`.
- A covered mutant with no test completed (`coveredBy` set, `testsCompleted` 0, `Survived`) means the runner did not run the tests: R3 is `n/a (env)` for the whole check, not a MISSED. This is the guard for the vitest-plugin case above.
- Results: `Killed` is caught; `Survived` and `NoCoverage` (no test reaches the mutant) are MISSED; `Timeout`, `CompileError`, `RuntimeError`, `Ignored` and `Pending` are neither. A report that is missing or unreadable is `n/a (env)`.
- Budget: Stryker writes its report at the end of a run, so a budget hit before that is `partial` with the mutant count from its log (`tested` unknown). A partial is not blocking.
- Timing is wall time only (`checks.R3.timing.wall_s`): Stryker's JSON has no per-phase durations.
- `mutant-timeout` sets Stryker's `timeoutMS`; under auto it stays at 120 s, as before.

## R3 cap, risk order and shards

Evidence (#26): one PR made 505 mutants; its largest shard took 20 min against the 10-min budget, and the mutants it never reached were left MISSED.

- **Cap.** At most `max-mutants` (default 40) mutants are tested per PR. Past it, the riskiest are picked and the rest are untested: R3 reads `partial (tested/total)`, never `pass`, and the note says `N past the cap (max-mutants M): untested` (ts: by changed lines, see below).
- **Risk order.** Branch conditions first, then returns and boolean literals, then arithmetic, then the rest; string and argument mutants last. Ties: file, then position (rust) or function and mutant number (python), then name. So every run picks the same set, whatever order the tool lists them in.
  - rust, from `cargo mutants --list --json`: `MatchArmGuard`, and a binary or unary operator `==` `!=` `<` `>` `<=` `>=` `&&` `||` `!`, are branch conditions; `FnValue` (a replaced return value, `true`/`false` included) is a return; `+` `-` `*` `/` `%` `&` `|` `^` `<<` `>>` (and their `=` forms) are arithmetic; `MatchArm` and the rest come after.
  - python, from each mutant's edit in mutmut's own copies under `mutants/` (written by step 1, before any mutant runs): an edit inside a branch condition (from an `if`/`elif`/`while`/`assert` line to the end of its test, a match subject, pattern or guard, a comprehension's `if`, a conditional expression's test: found with `ast` on the function's copy, so a continuation line of a multi-line `if (...)` counts), on an `if`/`elif`/`while`/`assert`/`match`/`case` line, or of a comparison or `and`/`or`/`not`/`is`/`in`, is a branch condition; a string literal, or an argument dropped or set to `None` (`return f(a, b)` -> `return f(a)` included), comes last; `True`/`False`, or the whole returned value replaced by `None`, is a return; any other whole value replaced by `None` (an assignment's, `total = n * 2 + 1` -> `total = None`) is the rest, behind arithmetic, whatever operators the old value held; an arithmetic operator or a number is arithmetic; any other edit of a `return` line is a return. An edit those copies do not explain is ranked with the rest.
- **Where the cap applies.** Each shard lists the PR's mutants itself (rust: `--list --json --in-diff`; python: step 1 over every changed file, then only the mutants whose edit is on a line the PR changed, or that mutmut's copies cannot place, see [Python R3](#python-r3-mutmut)), sorts them by risk, caps the list and deals it round-robin over the shards. Shard `k` runs its own share: rust names each with an anchored `--re` (no `--shard`; `--in-diff` as before), python with `mutmut run <name> ...`. Shard 0 also reports the mutants past the cap as untested, so the merged `tested/total` counts each mutant once. A shard whose share is empty (fewer mutants than shards) reads `0 mutants in this shard`, `pass` with 0/0, and adds nothing to the merge. Within the cap: rust keeps cargo-mutants' own round-robin (`--shard k/n`), so its argv is as before; an unsharded python run keeps the touched functions' filters when every candidate is on a changed line, while a python shard still lists every changed file and names its share mutant by mutant.
- **A run that leaves the pick** (rust): cargo-mutants ORs `--re` with an `examine_re` in the crate's `.cargo/mutants.toml`, so such a config runs mutants past the cap. A capped shard whose run holds a mutant outside its pick is `n/a (env)` and names `examine_re`; it never reads `pass`. A capped note's `tested/total` is the check's.
- **A listing the budget cut** (python): a shard dealt from a step 1 the budget ended may hold a list the other shards do not, so its `total` is unknown (`tested/?`), never a dealt count.
- **Unreached is untested.** A mutant the budget never reached is untested (`partial`), with no MISSED entry. A mutant that really ran and survived is still MISSED. For python, a mutant mutmut reports missed is final only after its whole-suite retry, so one still waiting for that retry (or whose retry the budget cut short) is untested too.
- **Shard count** (`baseline` job) = `min(4, mutants, ceil(estimated minutes / (budget / 2)))`, at least 1: each shard aims at half its budget, so a small PR gets one shard, a large one at most 4, and none is empty.
  - rust: `mutants` is the listed count capped at `max-mutants`; the estimate is that count times the baseline's measured build plus test seconds (the clean build over-estimates an incremental mutant build).
  - python (#64): the `baseline` job runs the whole suite once at head (`python3 -B -m pytest -x -q -p no:cacheprovider --ignore=mutants --junit-xml=<temp file>`) and takes the session time pytest writes in that JUnit XML (the `testsuite` element's `time`) as the measured test time (`checks.R3.timing.baseline_test_s`). The XML is read, not the terminal summary, which a repo's own options (`-q` in `addopts`, colour) can drop or change. mutmut's listing step (step 1, as each shard runs it; one mutmut stops early, because no test reaches a mutated function, is read as a listing too) gives the mutants on changed lines (`mutants` in the baseline JSON). `mutants` is that count capped at `max-mutants`; the estimate is that count times the suite's test time. It counts the mutants' runs only: each shard's own listing (about two suite runs: mutmut's statistics and its clean run) is not in it, and mutmut runs only the tests that reach a mutant, so the whole suite over-estimates a mutant. The suite and the listing each run within `mutation-budget`, so the step can take about twice it. The per-mutant timeout stays mutmut's own (`timeout` is null). No mutant on a changed line: `run` false, 0 shards, R3 `pass` (`0 mutants on changed lines`), as for rust. Every shard lists every changed file itself and runs its round-robin share of the capped, risk-ordered list.
  - python, a baseline that measured nothing (mutmut not runnable, a suite that is red, does not finish within the budget or writes no session time in its JUnit XML (`-p no:junitxml` in `addopts`), a listing that stopped or did not finish, unreadable results, a repo that configures `[tool.mutmut]` itself, no manifest in project-dir): the count stays one shard per changed production file, at most 4, and the note says why: `... in N shard(s); test time not measured (<why>): one shard per changed file`. The shards then report what they find.
  - ts: the `baseline` job measures nothing: one shard per changed production file, at most 4.
  - A python shard whose share of the capped list is empty (fewer mutants than shards) reads `0 mutants in this shard` and still pays one listing run.
- **ts (Stryker), by changed lines (#63).** Stryker selects no mutant by name (`--mutate` takes line ranges, and makes a mutant only when every line it spans is in a range), so the cap works on the changed lines, with the mutants counted before the run: `@stryker-mutator/instrumenter`, loaded under `node` from the Stryker install the command names, lists the mutants in the changed files (mutator, lines), twice, at Stryker's default parser options: with the mutators the repo's Stryker config excludes off (`mutator.excludedMutations`; none with no config) and a mutant a `// Stryker disable` comment turns off left out, which is what the run makes; and with every mutator counted as excluded, so no mutant is dropped for another, the upper bound of any run (Stryker 10.0.0 keeps a call statement's `CallExpression` mutant, `console.log("x");` -> `;`, only while no other mutant there is left, so a repo's `mutator.excludedMutations` or an ignorer makes the real run hold it). The under-cap decision, the pick and `total` come from the first list; the second only bounds what a run may make (the n/a guard below). The repo's Stryker config is read as data, never run: the file Stryker finds first (`stryker.conf.json`, then `.js`, `.mjs`, `.cjs`; then `stryker.config.*`, `.stryker.conf.*`, `.stryker.config.*`), when it is JSON. A config that cannot be read that way gets no cap: every changed line runs, the mutation budget the only stop, and the note says `max-mutants not applied: <why>`. That is a config that is code (`.js`, `.mjs`, `.cjs`: reading it would run repo code), one that is not a JSON object or whose `mutator.excludedMutations` is not a list of names, and one that sets `ignorers` or `ignoreStatic` (the run then ignores mutants no listing can name). A mutant the report shows `Ignored` (excluded by the repo's config or a comment) counts in neither `tested` nor `total`. With a config read that way the listing holds what the run makes, so the count past the cap is the run's own, in the note and the partial entry alike (no `up to`). It runs in a temp dir of its own, with absolute paths, and runs no repo code. A mutant's risk class comes from its mutator, in #26's order: `ConditionalExpression`, `EqualityOperator`, `LogicalOperator` and `BooleanLiteral` dropping a `!` are branch conditions; `BooleanLiteral` flipping `true`/`false` and `ArrowFunction` are returns; `ArithmeticOperator`, `AssignmentOperator`, `UpdateOperator` and `UnaryOperator` are arithmetic; `StringLiteral` comes last; the rest (`BlockStatement`, `CallExpression`, `ArrayDeclaration`, `ObjectLiteral`, `MethodExpression`, `OptionalChaining`, `Regex`) in between. Type-only code (type aliases, interfaces, import and export lists) makes no mutant, so it never takes the cap. When every mutant a default run makes on the changed lines fits under `max-mutants`, every changed line runs, as before. Past it, mutants go riskiest first (ties: file, first line, last line), each bringing every line it spans (so a mutant over several lines keeps its place in the order); the pick counts every listed mutant its lines complete and is kept while that stays within `max-mutants`. The first mutant that would pass it ends the pick, so a cap below the riskiest mutant's own lines' count tests none and reads `partial 0/N`; one big branch mutant over many lines (a TSX `{open && (...)}` block) can take most of the cap, or all of it, that way. The mutants left are untested: the note says `N past the cap (max-mutants M): untested` and R3 reads `partial (tested/total)`, never `pass`. Shards stay one per changed file: the pick is made over every changed file, a shard runs the picked lines of its own files, and shard 0 reports the mutants past the cap. A run that makes more mutants than the upper bound on its picked lines is `n/a (env)`: the cap was not kept; the listing parses at Stryker's defaults, so a repo config that changes how files parse (`mutator.plugins`, a babel config) can do this. No listing: the cap is not applied, every changed line runs, and the note says `max-mutants not applied: Stryker's instrumenter listed no mutant (<why>)`; the mutation budget is then the only stop. That happens with no `node`; a `mutants-cmd` that is not a path to the Stryker binary (`npx stryker`, `pnpm exec stryker`); a pnpm or Yarn PnP install (a shell shim in `.bin`, the instrumenter not hoisted beside `@stryker-mutator/core`); a `.js` file that needs a parser preset from the repo's babel config; or output that is not the listing (the note names the bad row, the list that is missing, `no ekit-stryker-upper list in its output`, or the list line that is not a JSON list, quoted). The workflow's own install (`npm install --prefix $RUNNER_TEMP/stryker`, its absolute binary path) gets a listing. A budget hit before Stryker's report is `partial` with the listed count as `total` (tested unknown) and no MISSED; with a report, a mutant still `Pending` is untested, never MISSED, and the run is never `pass`.

## What each stack mutates

The three tools do not make the same mutants, so R3 is not equally strict across stacks. This is a property of the tools, written down here so it is not a surprise:

| | cargo-mutants (rust) | Stryker (ts) | mutmut (python) | a declared tool (adapter file, #19) |
|---|---|---|---|---|
| Operators, conditions, return values | yes | yes | yes | the tool's own (PIT, Stryker.NET, mull, ...) |
| String literals | no | replaced by `""` only | wrapped (`"XXtextXX"`) and case-changed | the tool's own |
| Arguments removed or set to `None` | no | no | yes | the tool's own |
| Module-level code | n/a | yes | no (functions only) | the tool's own |
| A repo can switch a mutator off | config (an R2 `needs-human` change) | `excludedMutations` in the repo's Stryker config (same) | no: there is no such option | the tool's config, when the adapter file lists it in `config_files` (same) |
| `max-mutants` cap and risk order | yes, from `--list --json` before the run | by changed lines, counted from Stryker's own instrumenter before the run (#63) | yes, from mutmut's copies after its listing step | no: the tool lists no mutant before its run (the note says so) |
| Shard count | cost-based, from the measured baseline | one per changed file (no baseline measured) | cost-based, from the suite's measured test time (#64); one per changed file when nothing was measured | one per changed file (no baseline measured) |
| No tool | | | | R3 `n/a`, named in the summary (tier 3; ekit's own lexical mutator, tier 2, is a later round) |

In ekit's own code, most python string and argument mutants that survived were real gaps (a dictionary key, a git flag, an environment variable name), so they block like any other. The ones that are not gaps are equivalent mutants: see the R3 row of the [forbidden cheats](testing-standard.md#3-forbidden-cheats) for what to do with one.

## Stack plan

`.ekit/stack-plan.toml` lists the repo's stacks: what is planned, what is current and what is retiring, where each lives and which adapter checks it. The drift check compares it with the tracked manifests on every PR, git only (no test runner, no network):

```
python3 -I scripts/mech-review.py drift --repo . --base main --head HEAD --format json
```

```toml
ignore = ["examples/demo", "templates"]   # folders whose manifests are not projects

[[stack]]
name = "web"                # letters, digits, _ or -; unique
folder = "web"              # under the repo root; "." for the root
adapter = "ts"              # a built-in (python, rust, ts) or an adapter file's repo path, e.g. ".ekit/adapters/kotlin.toml"
status = "current"          # planned | current | retiring
target-os = "linux"         # optional: linux | macos | windows; the adapter's when left out
```

- **Manifests**: the file names the built-ins list (`Cargo.toml`; `pyproject.toml`, `setup.py`, `setup.cfg`; `package.json`) and the ones the adapter files of the base branch's plan and of the PR's plan list (`manifests`, required for an adapter file in the plan), whichever plan judges: a PR cannot hide a manifest by adding or dropping the adapter that lists it. A base plan that does not read still lends the names its entries' adapter files list, each one that loads there, so the PR that fixes it is held to the names a good base would hold it to (a plan that is not TOML names no file). A manifest counts anywhere in the tracked tree except under fixture, vendor and build folders (`node_modules`, `vendor`, `target`, `tests`, `test`, `fixtures`, `testdata`, `examples`, `third_party`, `dist`, `build`) and the `ignore` folders.
- **Covered**: a plan entry's folder holds the manifest, at any depth, and the entry's adapter lists its name. An entry's folder may not be under an `ignore` folder or a fixture, vendor or build folder (a usage error): no manifest there would ever count.
- **Adapter**: a `current` or `retiring` entry's adapter must be a built-in or an adapter file that reads at the plan's ref, or an adapter file that went with every manifest it listed: the file is not there, its last version in the first-parent history listed manifests, and none of them is left in the entry's folder (outside `ignore` and fixture folders). That entry is vanished, as a built-in stack whose manifests are gone (the message naming the entry to remove, on that PR and every later one). An adapter file that is gone while one of its manifests is left, one that was never there, and one that is there and does not read stay usage errors. A `planned` entry may name an adapter file that is not there, or does not read, yet [owner's decision; the spec leaves it open], by its path (a value with a `/` or ending in `.toml`; any other value must be a built-in, so a typo such as `typescript` for `ts` is named as on a `current` entry): until it reads the adapter is not proven, the entry covers nothing and starts no check, so a manifest in its folder that another adapter lists is uncovered (the `adapter-fix` entry), and one only the unwritten adapter would list is not seen yet.
- **Result**:

  | Repo state (head tree) | Result |
  |---|---|
  | A manifest no entry covers | One `fail` entry for the PR (check `D`, class `adapter-fix`, file `.ekit/stack-plan.toml`) naming every uncovered manifest. A person may waive it ([waivers](#waivers)) |
  | A `planned` entry's manifest is there and its adapter is proven (a built-in, or an adapter file that reads at the plan's ref) | Message: its checks start; set its status to `current` |
  | A `retiring` entry's manifest is still there | Message: finish the migration, then remove the entry |
  | A `current` or `retiring` entry's folder holds none of its adapter's manifests (also when its adapter file went with them) | Message naming the entry to remove |
  | A `retiring` entry, retiring for 30 days or more [spec default] | Its message adds a reminder to finish or drop the migration. The 30 days count from the plan commit where the entry last became `retiring`, in the branch's first-parent history (`git log --first-parent` on the plan), so a merged side branch does not reset them |

  Messages never fail the check. They are in `checks.D.messages` and on `Stack plan:` lines in the comment.
- **Which plan judges**: the base branch's plan. A PR that edits the plan or one of its adapter files and adds no manifest is judged by its own plan, so the setup PR that adds the plan (with the workflow caller, say) passes. A PR that adds a manifest and its entry together stays blocked until the plan lands first, or a person waives the entry. With a plan on head but none on base, the base judges with nothing covered.
- **Waiving it**: the entry's id holds the uncovered manifests, so a waiver lapses when that set changes either way: a new uncovered manifest, or one of two waived ones fixed, needs a new waiver. A waiver is per PR: once a waived PR merges, the manifest is uncovered on the base, and every later PR fails `D` until the plan covers it (or each is waived).
- **Loosening the plan**: a PR that edits only the plan is judged by its own plan for drift, so it can add a folder to `ignore` (or drop an entry and ignore its folder) and pass `D`. ADR 0001 makes loosening the ignore list a person's call: R0's [editing rules](#r0-adapter-proof) give a folder added to `ignore` (and a changed `target-os`) one `needs-human` entry (#20).
- **No plan** on base or head: no check `D`, no entry, no message; `stack: auto` and every summary are as before.
- **Target OS**: `resolve` reads the base branch's plan. The entry for the settled stack and project dir (its adapter's name, its folder; `current` before `retiring` before `planned`) gives the target OS: its own `target-os`, else its adapter's. With no entry, the `--adapter` file's, else `linux`. A base plan that does not read never stops `resolve` (that PR's drift check fails `D` already, and a failed stack job would skip every job after it): it follows the rule for which plan judges, so the PR that fixes it (it edits the plan or an adapter file, adds no manifest, and its own plan reads) gets its own plan's entry, and any other PR no entry (the adapter's target OS); stderr names the plan's error and which applied, so a bad plan never moves a runner silently. Two entries for one stack, folder and status are a usage error (the stack is the adapter's name, so two adapter files that declare one name, or one path spelled two ways, are one stack; an adapter file not proven yet counts as its path; a `retiring` and a `current` entry for one stack and folder are a migration, and allowed). An explicit stack where `--repo` is no git repo reads no plan, as before; in a git repo a missing `--base` ref is a git error (exit 2). The workflow's stack job checks the caller out for every stack, so a plan's target OS reaches an explicit-stack caller too.
- **A bad plan** is a usage error (exit 2), never clean. The error goes to stderr, and stdout still holds a result whose `D` fails with one `CI` entry (class `adapter-fix`, not waivable) naming it, so a reader of the result never takes it for a repo with no plan. A git error (no result) prints nothing on stdout. Example: `.ekit/stack-plan.toml at 1a2b3c4d5e6f: stack[1] `web`, field status: `done`: want planned, current or retiring`. Unknown keys, a missing field, a duplicate name, a duplicate stack, folder and status, a folder outside the repo or under an ignored or fixture folder, an adapter that is neither a built-in nor a file at that ref (except a planned entry's, above), a bad adapter file, a bad `target-os`, and `ignore = ["."]` are all named. Reading a plan needs python 3.11 or newer (`tomllib`); without it a plan is that usage error, and a repo with no plan needs nothing.
- Exit: 0 clean or messages only, 1 the `fail` entry, 2 a bad plan (with its failing result), usage or git error.
- **At session start** (#57) the hook runs `stack_plan.drift_at(repo, "HEAD")`, the same findings for the committed tree with no base, git only, and adds them to the session context: an `[ekit] Stack plan drift at HEAD` line, then one line per uncovered manifest and per message, at most 20 (then a count and the `drift` command that lists the rest). Paths and plan values print with their control characters escaped (`\n`), so a committed name cannot start a session line of its own; a value over 500 characters is cut. A clean repo or one with no plan adds nothing; a commit-less repo or a folder outside git (where git itself finds no repo: symlinks, `GIT_DIR` and ceilings count as git reads them) too. Each of these is one `[ekit] Stack plan:` line, never clean and never a failed hook: a plan that does not read (naming the problem), a plan in HEAD's tree whose content cannot be read, any git failure inside a repo (dubious ownership, a bad config, a bare repo), no git on PATH, a drift check past its 3 s deadline, and a partial clone (a promisor remote git reads as true, or `extensions.partialClone`), where the check is skipped (git would fetch the objects it lacks; git also runs with `GIT_NO_LAZY_FETCH=1`). In a shallow clone a retiring stack's line says its day count covers only the history there. An uncommitted plan edit shows at the next session after its commit.
- **Guard wiring**: the drift check is its own step in the `guard` job, right after the two checkouts and before `R2 guard`, with its own artifact. It leaves a result on every run whose refs resolve, with no plan too (a result with no `D`), and keeps the failing result of a bad plan. When it leaves none (a git error, a crash) it stops the job, so `R2 guard` does not run and R2 has no result either: the report fails on R2's `CI` entry. So a missing drift result never hides a plan, and readers take one for no `D`, as before: the `report` job passes `--envelope drift=FILE` only when the file is there, and `mech-summary.py` reads it the same way, whatever the guard job's conclusion (a guard job that failed on R2 is no sign of a plan). A drift result that is there and does not read fails `D`. The step, in `guard` after the two checkouts:

```yaml
      - name: drift check (stack plan, D)
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          set -uo pipefail
          rc=0
          python3 -I "$GITHUB_WORKSPACE/ekit/scripts/mech-review.py" drift --repo "$GITHUB_WORKSPACE/caller" \
            --base "$BASE_SHA" --head "$HEAD_SHA" > mech-review-drift.json 2> mech-review-drift.err || rc=$?
          cat mech-review-drift.err >&2
          # exit 0 clean, messages only or no plan (no D in it), 1 the fail entry, 2 with a result (a bad plan: D fails
          # with a CI entry): kept. Nothing on stdout (a git error, a crash): no result, and the job stops here, before
          # R2, so the report fails on R2's missing result
          [ -s mech-review-drift.json ] || rm -f mech-review-drift.json
          if [ ! -f mech-review-drift.json ]; then
            echo "::error::mech-review drift exit $rc: no result"
            exit "$(( rc > 0 ? rc : 2 ))"
          fi
          if [ "$rc" -gt 1 ]; then
            echo "::error::the stack plan does not read: D fails (the error is above)"
          fi
      - name: upload drift result
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: mech-review-drift-json
          path: mech-review-drift.json
          if-no-files-found: ignore
          overwrite: true
```

In `report`, the `fetch drift result` step (`actions/download-artifact@v4`, `continue-on-error: true`, name `mech-review-drift-json`, path `drift-result`) before the comment step, and in the comment step, before `mech-comment.py`: `if [ -f drift-result/mech-review-drift.json ]; then extra+=(--envelope drift=drift-result/mech-review-drift.json); fi`.

## Stack resolution

`resolve` (the `stack` job) settles which stacks run and with which adapter, git only, from the PR's base: the plan and the adapter files are read at the base, so a PR cannot change which adapter judges it (a PR that adds or edits them is judged by the base's; the next PR by its own).

- **With a stack plan** on the base (`.ekit/stack-plan.toml`) that reads: `auto` takes the stacks from the plan, each with the adapter the plan names, and does not detect. An entry runs when its adapter is proven and a manifest it covers is in the base or the head tree: `current` and `retiring` stacks run, a `planned` stack starts once its manifest is there (a planned stack whose manifest is missing is not run), and deleting a stack's manifest in a PR does not stop its checks. One entry per stack and folder (`current`, then `retiring`, then `planned`). A set `project-dir` keeps the entry for that folder. No entry to run is an error naming it (exit 1).
- **A base plan that does not read** picks no stack: `auto` detects on the base tree (and at head, as below) with the base's adapter files, as with no plan. The PR's own plan never picks the stack or the adapter, also in the PR that fixes the plan; that PR's plan only sets `target_os`, by the rule for [which plan judges](#stack-plan) (#56), and stderr names the plan's error. So a PR cannot rewrite a bad plan to move its stack to another adapter, or to an adapter file it adds.
- **Without a plan**, `auto` detects as before, over the built-ins and the repo's adapter files: every `.ekit/adapters/<name>.toml` (directly in that folder; the file name is the stack's `name`, the same name the plan's example uses: letters, digits, `_` or `-`, so `a.b.toml` or `.toml` is an error naming the file). A repo with only a `pom.xml` and `.ekit/adapters/maven.toml` listing `manifests = ["pom.xml"]` resolves to `maven`. A file named like a built-in (`ts.toml`) takes the built-in's place: its `manifests` and `target-os` replace the built-in's. Several projects or none fail naming the projects found and the inputs to set, never a guess; an adapter file there that does not read, or whose `name` is not its file name, is an error naming it (exit 1, no stack).
- **An explicit `stack`** may name a stack the repo defines: the base plan's entry for that stack and `project-dir` when it names an adapter file, else `.ekit/adapters/<name>.toml`, else the built-in of that name. A plan entry that names a built-in keeps the built-in. Its `target-os` applies (a plan entry's own first). An unknown name lists the names known (`stack gradle: want auto, maven, python, rust or ts`).
- **Output**: one stack prints `{stack, project_dir, error, target_os}` as before. Several stacks from a plan print `stack: null`, `target_os: null`, `error: null` and a `stacks` list, one `{name, stack, project_dir, adapter, target_os}` per stack (`adapter`: the plan's value, a built-in or a repo path), exit 0. The stack job turns either into its `legs` output, and the workflow runs one set of checks per leg ([several stacks](#several-stacks)).
- **Other checks**: `r2 --stack <name>` with no `--adapter` takes the repo's adapter file for that name the same way (at `--base`; an adapter file that does not read is a usage error, exit 2). `--adapter FILE` still wins. [`r0 --stack <name>`](#r0-adapter-proof) with no `--adapter` proves that file as it is at `--base`, with its fixtures there (`<name>.r0/` beside it); its messages and R0's editing rules name the file by its repo path, so a PR that loosens a limit or changes its `target-os` is the `needs-human` entry. Both take `--project-dir` for the plan entry (its stack and folder); the guard job passes them the stack job's `project-dir`, so an entry in a folder other than `.` judges and is proved with the adapter file the plan names. `all` on a stack only the repo defines leaves R0 to `r0`. The run side of an adapter file is R1 and R4 through [`[run]`](#run-side-r1-and-r4) (#18) and R3 through [`[mutation.tool]`](#r3-side-mutation-tool) (#19), so:
  - **An override** (a repo file named like a built-in: `python`, `rust` or `ts`) judges R2 and resolution, and, when it has a [`[run]`](#run-side-r1-and-r4) table, R1 and R4 too (#18): `red` and `all` run them through the file. Without `[run]`, R1 and R4 run the built-in. R3 (`mutants`, `baseline`, `plan`) runs through the file when it declares `[mutation.tool]` (#19), else the built-in's: a file without them gives the built-in's verdict, as with no override, so adding the file turns no check off. `all` (one adapter for R1, R2 and R4) on an override without `[run]` is a usage error: run `r2` and `red` apart.
  - **A stack only the repo defines** (by name, or the plan's entry naming an adapter file: `maven`) has no built-in to run. With `[run]` (#18), `red` runs R1 and R4 through the file, and `all` runs R2, R1 and R4 through it (R0 is `r0`'s: `not run by all on the repo's adapter file`). Without `[run]`, `red` reports R1 and R4 `n/a` (``stack `maven` is the repo's adapter file, which has no [run] table: R1 runs through [run] (#18)``), and `all` runs R2 through the file and reports R1 and R4 `n/a`. With `[mutation.tool]` (#19), `plan`, `baseline` and `mutants` run R3 through the file's declared tool (`plan` and `baseline` read the file's production files: one shard per changed file, at most `--shards`), and `merge` (the report job, no checkout: it takes any stack name, R3 comes from the results) combines the shards as for a built-in. Without it, `mutants` and `baseline` report R3 `n/a` (baseline runs no shard) with ``stack `maven`: the adapter file declares no mutation tool ([mutation.tool]): R3 not run``; `plan` says run on a production change, so the baseline step reports R3's `n/a`, and `merge` carries that `n/a` through. Never a usage error. An explicit name that is no stack name (`a.b`) is unknown (`stack a.b: want auto, python, rust or ts`).

### Several stacks

When the base branch's plan gives several stacks to run (#17), the workflow runs one set of checks per stack and reports them as one:

- **Legs**: the `stack` job's `legs` output, one per stack, in the plan's order: `key` `-<i>-<name>` (in each artifact name), `label` ` [<name>]` (after each job name: `mech-review guard (R2) [api]`), `name`, `stack`, `project-dir`, `target-os`, and `drift` (true on the first leg only). One stack is one leg with an empty key and label, so a single-stack repo sees the job names, artifact names and comment it saw before. The stack job's `stack` output is empty with several stacks; the jobs that differ (`shards`, the report's steps) read that.
- **Per stack**: `guard` (R2 and R0, with the stack's `project-dir`; the drift check, the repo's, in the first leg only), `red-first` (R1, R4) on the stack's target OS, `plan` (one job, one answer per stack: `runs`; `legs`: the stacks whose R3 runs), `baseline` on the stack's target OS for each of those, then `shards` reads each stack's baseline artifact and gives `mutants` one job per stack and shard (the shard count per stack as for one stack). A crash in one stack's job never cancels another's (`fail-fast: false`).
- **Report**: `report` downloads every artifact, merges each stack's mutants shards (`mech-review.py merge`, as for one stack), and writes `stacks.json` (one `{name, stack, project_dir, envelopes}` per stack) for `mech-comment.py --stacks stacks.json` (`--envelope drift=FILE` for the repo's drift result). Each stack's job results merge apart, as for one stack (a job with no result fails its checks with a `CI` entry in that stack); a stack with no result at all fails every check with one `CI` entry naming it, never a silent pass.
- **One comment, one check**: the headline is the whole result; under it a table has a row per stack (stack name, adapter, project dir, its own summary); each stack's `Did not run`, `R0` and `R3 timing` lines are named by stack (`web: Did not run: R1 (...)`); the entries table gains a `stack` column. Each check reads the worst of the stacks' (`fail`, then `n/a`, `unproven`, `partial`, `waived`, `pass`, `skipped`), its note naming each stack's; the result's `stacks` list keeps each stack's own checks and summary. The check fails when any stack fails.
- **Entry ids**: an entry's id is derived from its own id and its stack's adapter and project dir (`<check>-<sha1(stack|project_dir|id)[:8]>`, the entry's own check as the prefix: `R2-…`, `CI-…`), so the same rule broken in two stacks (a protected path both guards report) is two entries with two ids, each stable across pushes. A waiver names one id, so it lets one stack's entry through; each stack's own checks read it. One stack keeps the ids it had. So a repo that goes from one stack to several (a second stack in its plan) gets a new id for every entry: the waivers posted before stop matching, and each must be posted again with the entry's new id from the comment.
- **Missing results**: with several stacks the plan exists, so a drift result is always due: none, or one for another head, fails `D` with a `CI` entry. A stack whose plan fails (`plan` exit 2) reads `null` in `runs`: its R3 fails with a `CI` entry, the other stacks keep theirs; an answer that is missing or does not read fails R3 the same way. A stacks file that does not read, or lists a stack twice, posts the crash comment naming it.
- **Not yet**: `mech-summary.py` reads one stack's artifacts (the names with no key).

## Adapter file

An adapter file is a TOML file that describes one stack to R2 as data: which files are this stack's, how tests are written and named, what an assert looks like, how a lint is silenced and with what reason, and what hides code from R3. Its run side tells R1 and R4 how to run one test by name and read the result, and names the stack's install, build, lint and test commands. ekit's own scanner reads the source with it (comments and strings masked, brackets matched, arguments split), so the file holds tables and words, never a regex over the file.

```
python3 -I scripts/mech-review.py r2 --repo . --base main --head HEAD --stack ts \
  --adapter scripts/mech_review/adapters/ts.toml --test-paths 'tests/**'
```

- `--adapter FILE` takes the stack from the file in place of the built-in of that name. `--stack` must equal the file's `name`; a name that is not built in is allowed only with `--adapter`. Without `--adapter`, `rust`, `python` and `ts` run as before.
- `r2`, `red` and `all` (#18): `red` and `all` run R1 and R4 through the file's [`[run]`](#run-side-r1-and-r4) and [`[commands]`](#run-side-r1-and-r4) tables; a file without `[run]` is R2 only, and `red` or `all` with it is a usage error that names the table. `mutants`, `baseline` and `plan` (#19) run R3 through the file's [`[mutation.tool]`](#r3-side-mutation-tool); with none, R3 is `n/a`, named in the summary. `merge` takes no `--adapter` (it reads no tree). [`r0`](#r0-adapter-proof) takes `--adapter` too (it proves the file). `resolve --adapter FILE` reads the file's `target-os` only (#58). The workflow does not pass `--adapter`; `r2`, `red` and `r0 --stack <name>` find the repo's own adapter file at the base ([stack resolution](#stack-resolution)).
- Reading the file needs python 3.11 or newer (`tomllib`); on an older python `--adapter` is a usage error that says so, and the built-in stacks keep working.
- A file that is unreadable, not TOML, or invalid is a usage error (exit 2, nothing on stdout) that names the field: `adapter file x.toml: tests.cases: want at least one entry`. An unknown key is an error too, so a misspelt key never passes silently.
- A source file whose masked text does not balance (a bracket never closed, an unterminated block comment or multiline string) is an R2 `fail` of class `needs-human`: the cause may be the file's lexer table, not the PR. The built-in stacks keep `agent-fixable`.
- Reference: [`scripts/mech_review/adapters/ts.toml`](../scripts/mech_review/adapters/ts.toml) describes TypeScript/JavaScript and gives the same R2 entries and R1/R4 results as the built-in `ts` adapter (`tests/mech-adapter.test.sh` runs the TS suites through it, `mech-ts-red` included).

### Keys

Top level (required unless marked). `[lexer]`, `[tests]` and `[asserts]` are required too, except in a file with [`[parser]`](#parser), which has none of the pattern tables.

| Key | Value |
|---|---|
| `format` | `1` |
| `name` | the stack name (`--stack`): letters, digits, `_`, `-`; not `auto` (the stack input that means "find it") |
| `extensions` | file extensions of this stack, e.g. `[".ts", ".js"]`. A file of the stack is test code when it matches a `--test-paths` glob, production code otherwise |
| `manifests` | optional: files that mark a project dir of this stack, e.g. `["package.json"]` |
| `target-os` | optional, default `linux`: the OS the stack's tests run on, `linux`, `macos` or `windows` (exactly; any other value is a usage error naming `target-os`). `resolve --adapter FILE` prints it as `target_os`. It reads the file it is given as is: the workflow must pass the base branch's copy, since a PR's checks read adapter files from the base (ADR 0001), or a PR could pick its own runner OS. Changing it needs a person: R0's [editing rules](#r0-adapter-proof) give it a `needs-human` entry (#20) |

`[lexer]`: how source is masked.

| Key | Value |
|---|---|
| `block_style` | `braces` (blocks are bracketed). `indent` and `keywords` are reserved, not supported yet: an error |
| `brackets` | bracket pairs, e.g. `["()", "[]", "{}"]`. Each character may appear in one pair only. `()` is required (a call is `name(...)`), and so is `{}` (blocks, `block_style = "braces"`) |
| `ident_chars` | optional: characters that are part of a word beside letters, digits and `_` (ts: `"$"`) |
| `member` | optional, default `"."`: the member-access character. A word right after it (`a.it(`) is a member, not a call |
| `line_comments` | optional: openers of comments that run to the line end, e.g. `["//"]` |
| `unicode_escapes` | optional, default `false` (#22, Java): `\uXXXX` escapes (one or more `u`, after an odd run of backslashes) are decoded before the text is read, as javac does (JLS 3.3), so `\u0040Disabled` is `@Disabled`. An escape that decodes to a line break (`\u000a`, `\u000d`) would move every later line away from the diff's lines, which R2's rules compare with, so such a file is unparseable: R2's `needs-human` fail (`a unicode escape decodes to a line break: the file's lines are not the compiler's`), never read one line off |
| `block_comments` | optional: `[open, close]` pairs, e.g. `[["/*", "*/"]]`. Not nested; an unterminated one is a parse error |
| `[[lexer.strings]]` | optional, one table per string form: `quote` (the delimiter), `escape` (one character, optional), `multiline` (default `false`: the string ends at its closing quote or the line end, with no error), `interpolation` (`[open, close]`, multiline only: a closing quote inside does not end the string), `name` (for the error, e.g. `template literal`: an unterminated multiline string is a parse error) |
| `[lexer.regex]` | optional: a regex literal form. `delimiter` (one character), `after` (characters after which it starts a literal, not a division), `after_words` (words after which it does). Also at the start of the file |

`[tests]`: test cases are calls (`style = "calls"`), or marked declarations (`style = "declared"`, [below](#declared-tests)).

| Key | Value |
|---|---|
| `style` | `calls`: a test is a call `case("name", fn)`, grouped by calls `group("name", fn)`; `declared`: a test is a marked function ([declared tests](#declared-tests)) |
| `cases` | names of the calls that declare a test |
| `groups` | optional: names of the calls that group tests. A test's name is its groups' names and its own, joined by `separator` |
| `separator` | optional, default `" > "` |
| `skip` / `only` | optional: call names that skip or focus (`xit`, `fit`). A skip on a group skips the tests in it |
| `skip_modifiers` / `only_modifiers` | optional: `name.modifier(` words that skip or focus (`it.skip(`, `it.only(`) |
| `table_modifiers` | optional: `name.modifier(table)(name, fn)`: the call after the table is the test (`it.each`) |
| `min_args` | optional, default `0`: a case with fewer arguments is skipped (ts: `it.todo("x")` has no function) |
| `not_after` | optional: a name right after one of these (whitespace ignored) declares, not calls: `function it(` |
| `skipped_text` | optional: the R2 problem for a newly skipped test, `{name}` is the test |

The first argument names the test: a string literal's value, or the argument's text. The test's body, which R2 reads to pair a renamed test, is the block of its callback: the first later argument that ends in a `{...}` block right after `=>` or a `function (...)` head (`() => {`, `async function () {`), or a lone later argument that is a block (`case("name", { ... })`). A table before the call or an options object is never the body; with no such block the test has no body and its rename stays a removed-test `fail`.

Declared tests with a marker before them are described by `style = "declared"` (below). Tests declared by their name alone (Go `func TestX(t *testing.T)`) or with a bracketed attribute (C# `[Fact]`, rust `#[test] fn x()`) cannot be described yet. Not supported either: a test whose body is a trailing block after the call (`test("keeps") { ... }` in Kotest or Kotlin, Swift trailing closures). The body must be an argument inside the call's parentheses (`case("name", fn)`). With a trailing block, the test is named without its group, its asserts count as outside test fns, and a skip on a trailing-block group (`xcontext("Calc") { ... }`) gives no entry: that skip is not caught.

#### Declared tests

`style = "declared"` (#22): a test is a named function, a [`[functions]`](#keys) shape (required with this style), with a case marker right before it: JUnit's `@Test void adds() {`. Its keys:

| Key | Value |
|---|---|
| `prefix` | what starts a marker (`"@"`): punctuation, no word character, bracket or member character (required) |
| `cases` | marker words that make the function a test (`["Test", "ParameterizedTest"]`) |
| `groups` | optional: words that declare a group, `<word> NAME ...{...}` (`["class"]`): the group's name is the word after it, its tests those inside its block, nested groups joined |
| `skip` / `only` | optional: marker words that skip or focus (`["Disabled"]`); on a group, every test in it |
| `separator`, `skipped_text` | as for calls (`"."` names `CalcTest.adds`) |

A marker is the prefix, a word (dotted or not: `@org.junit.jupiter.api.Test` counts as `Test`) and optionally a bracket group (`@Disabled("why")`, `@Disabled()`, `@ValueSource(ints = {1, 2})`). Whitespace, line breaks and comments may sit after the prefix and around each member character, as javac allows (`@ Disabled`, `@/**/Disabled`, `@org . junit . Disabled`). A declaration's markers are those right before its first word, with plain words between them (modifiers: `public static`); any other code ends them. The test's line is its declaration's first word, its body the lines inside the function's closing block, and a skipped test keeps its body (R1 and R4 compare it). The call-only keys (`skip_modifiers`, `only_modifiers`, `table_modifiers`, `min_args`, `not_after`) are an error with it. Read from the masked text, so a marker in a comment or a string never counts. Reference: [`tests/fixtures/adapters/java.toml`](#java-reference-adapter).

`[functions]` (optional): named functions own the asserts inside them, so an assert moved from a test into a helper it calls is not a drop. `shapes` is a list of shape strings; each element is separated by spaces, whitespace may sit between elements, and `?` after an element makes it optional:

| Element | Matches |
|---|---|
| `word`, `a\|b` | that word (one of them) |
| `NAME` | a word: the function's name (exactly one per shape) |
| `ID` | any word |
| punctuation, e.g. `=`, `=>`, `*` | that text |
| `:...` | that text, then the rest of the line up to the next element's literal (a type annotation) |
| `(...)` | a bracket group starting here (any pair from `brackets`) |
| `...{...}` | skip to the next `{`, then its block (return types may come between) |
| `BODY` | a `{}` block, or an expression up to `;`, the line end or a closing bracket |

A shape starts with a word and ends with a group, block or `BODY`; the function spans from its first word to that end. A function only owns its asserts for the drop count: an assert in a helper is still outside test fns, and an R2 message about it names `<module>`, not the helper (as the built-in ts adapter does).

`[asserts]`: at least one shape.

| Key | Value |
|---|---|
| `[[asserts.chain]]` | `start(actual).matcher(expected)`: `start` (the word, required), `eq` (required, at least one: matchers that compare equal: kind `eq`, operands `actual` and `expected`), `negate` (members that flip eq to `ne`, e.g. `not`), `pass_through` (members skipped, e.g. `resolves`). Any other matcher is kind `other` |
| `[[asserts.call]]` | `name(a, b)`: `names`, `kind` (`eq`, `ne` or `other`), `operands` (`[left, right]` argument indexes, required for `eq`/`ne`) |

A word starts one assert shape only: a second chain with the same `start`, or a call name listed twice, is an error.

R2 compares eq/ne asserts by their operands (a changed expected value is a `confirm`) and other asserts by their text.

`operands = [left, right]`: which argument is the expected value does not matter. R2 reports a change when one operand stays and the other changes, and the message names the one that changed (`was 3, now 4`). So `assertEquals(expected, actual)` takes `[0, 1]` and `assertThat(actual, expected)` takes `[0, 1]` too. An index past the call's arguments is not an error: such a call reads as kind `other`, and a changed value in it reads as `assertion replaced` (also a confirm), a weaker message. Check the indexes against the assert's real signature.

`[[suppressions]]` (optional): one table per family of lint directives, read in comments only.

| Key | Value |
|---|---|
| `directives` | comment bodies that start with one of these (longest first, ending at a character that is not a letter, digit, `_` or `-`) |
| `covers` | for each directive: `line`, `next-line` or `file`: the lines it silences (an added line among them counts) |
| `lints` | optional, default `directive`: the entry names the directive; `rules`: the directive and the words after it |
| `reason_after` | optional: the reason is the text after this mark (`-- why`) |
| `reason_strip` | optional, without `reason_after`: the reason is the text after the directive, with these characters stripped from its start, set by set (`[":", "-–— "]`) |
| `problem` / `hint` | optional: the R2 text; `{lints}` is the directive and its rules |

`[limits]` (optional, #20): the stack's check limits, whole numbers. Nothing reads them for a run yet (later tickets do); R0's [editing rules](#r0-adapter-proof) need a person for a looser one.

| Key | Value |
|---|---|
| `max-mutants` | >= 1, default 40: the R3 cap (lower is looser) |
| `mutation-budget` | >= 1, default 10: R3 minutes (lower is looser) |
| `census` | 0 to 100, default 100: the share of the runner's tests the scanner must find (lower is looser) |
| `assert-density` | 0 to 100, default 10: the share of tests with no recognised assert allowed (higher is looser) |

Any other key, or a value that is not a whole number in range, is an error naming it: `limits.max-mutants: want a whole number >= 1`.

`[mutation]` (optional): what hides code from R3 (an R2 `needs-human` fail).

| Key | Value |
|---|---|
| `skip_comments` | comment bodies that start with these words (whitespace between words free): a mutation skip marker |
| `skip_annotations` | with [`style = "declared"`](#declared-tests) only (#22): marker words that hide code from the tool (`["DoNotMutate", "Generated", "CoverageIgnore"]`, the names PIT skips). A marker in code (never in a comment or string), spelled as any marker may be, whose last word **ends with** one of them is a mutation skip marker on its line: PIT's own rule (its ExcludedAnnotationInterceptor avoids an annotation whose name ends with a configured one), so `@MyGenerated` and `@NoCoverageIgnore` count and `@GeneratedX` does not |
| `config_files` | the mutation tool's config files, in any dir: a name (`pom.xml`) matches a file's last part, a path (`.mvn/maven.config`, #22) its last parts. Each is a path under the project dir (no `..`, not absolute) |
| `config_name` | the tool config's name in the entry, required with `config_files` |
| `tool` | the R3 tool: [R3 side](#r3-side-mutation-tool) |

### R3 side (mutation tool)

`[mutation.tool]` (optional, #19): the mutation tool R3 runs, the report it writes and that report's format. The core reads report formats, not tools: it has no code for the tool. With no `[mutation.tool]`, R3 is `n/a` (``stack `<name>`: the adapter file declares no mutation tool ([mutation.tool]): R3 not run``), named in every summary, never a pass. A parser-backed file ([`[parser]`](#parser)) declares it the same way: R3 reads the tool's report, not source. Every key is validated at load; a bad one is a load error naming the field (`mutation.tool.os[0]: `Linux`: want linux, macos or windows`).

| Key | Value |
|---|---|
| `name` | the tool's name in notes (`stryker not installed (env)`): letters, digits, `_`, `-`, `.` (required) |
| `command` | the tool's program and fixed words, split as the engine splits it (unbalanced quotes are a load error); `--mutants-cmd` replaces it (required). The program is a bare name, found on `PATH` when R3 runs (its absolute entries only), or an absolute path outside the project dir: a relative path (`tools/mut`, `./mvnw`, `node_modules/.bin/stryker`) is a load error, since it names a file the PR under review can change (`` mutation.tool.command: `tools/mut` is a path in the project dir, which the PR under review can change: ... ``); install the tool with `setup-command` (outside the checkout) or pass `mutants-cmd`. A program that `PATH` finds in the reviewed checkout (or the caller's), by its path or by where a link there points, is not run: one `fail` entry, class `needs-human`. The program may not be an interpreter, shell or launcher ([`[parser]`](#parser)'s list: `python3`, `node`, `sh`, `env`, `npx`, `java`, ...; any case, `.exe`/`.cmd` or not), as the first word (a load error) or as what `PATH` or `--mutants-cmd` resolves to, by name or by where a link points (a `needs-human` fail, not run): such a program runs what it is given, which can be a file the PR changes. A later word may name a repo file (the tool's own config) |
| `args` | words after the command; placeholders `{mutate}` (the changed line ranges), `{timeout_ms}`, `{timeout_s}` (the per-mutant timeout: `mutant-timeout`, else `timeout`) and `{report}` |
| `mutate` | one range of changed lines: `{file}` (project-dir relative), `{module}` or `{package}` (one of them required), `{first}`, `{last}`; required when an arg has `{mutate}`, an error when none does. Ranges that render the same are passed once. Without it the tool picks its own scope and ekit's changed-line filter keeps the MISSED on changed lines |
| `module_roots` | with `{module}` or `{package}` only, required there (#22): dirs under the project dir (`["src/main/java"]`). `{module}` is a changed file's path under the first root that holds it, its extension dropped and `/` as `.` (`src/main/java/com/x/Calc.java` is `com.x.Calc`, PIT's class name); `{package}` its dotted dir with a trailing `.` (`com.x.`), so `{package}*` reaches every class the file holds; for a file directly under a root (the default package) it is the file's own module (`Top`), so `{package}*` is `Top*`, never a bare `*` (PIT refuses one). A changed production file under no root is not mutated (the build compiles none there, Maven's `src/main/java`): the note names it (`; not mutated: tools/Stray.java (under none of mutation.tool.module_roots: src/main/java)`), the other files are mutated and keep their MISSED, and with no other file R3 is `pass` 0/0 |
| `mutate_join` | what joins the ranges, default `,`; a changed file whose name holds it is `n/a (env)` |
| `version`, `version_pattern` | words that print the tool's version, and a pattern its output must match (needs output, as `[run.outcome]`'s): a probe that fails is `n/a (env)` before the run |
| `report` | the report file, project-dir relative (no `..`, not absolute, no empty or `.` part) (required) |
| `format` | `mutation-testing-elements`, `pit-xml` or `lines` (required) |
| `pattern`, `status` | format `lines` only (required there): a python regex (multiline) with named groups `file`, `line` and `status` (`desc` optional: the mutant's description; without it the matched text, so the entry id moves with the line); `status.missed` and `status.caught` (required), `status.timeout`, `status.unviable`: the status words of each, a word in one list only. A pattern that matches empty text is a load error; a zero-width match never counts |
| `os` | the OSes the tool runs on, each `linux`, `macos` or `windows`, once (required). The stack's target OS, as `resolve` settles it (the [stack plan](#stack-plan) entry's `target-os` first, else the adapter file's [`target-os`](#keys), else `linux`), not in it: R3 `n/a (env)` naming the OS (`mut does not run on windows (env): mutation.tool.os lists linux, macos; the stack's target-os is windows`) |
| `timeout` | per-mutant seconds when `mutant-timeout` is auto, a whole number >= 1, default 120 |
| `baseline_failed` | a pattern in the tool's output when no report was written: the baseline tests fail at head (an R3 `fail`, agent-fixable, as for the built-ins) |
| `runners.<name>` | per [`[[run.runner]]`](#run-side-r1-and-r4) (needs `[run]`; the runner the crate's test command picks): `needs` (a file the tool needs in the project dir, such as the runner's binary: missing is `n/a (env)` naming the runner), and, only when the project has none of `[mutation].config_files`, `args` (added after `args`) and `config_file` + `config` (a JSON object, written to that file in the worktree; the file must be one of `config_files`, so a repo config is never overwritten) |

How a run goes (`mutation_tool.DeclaredTool`, its own module beside `mutants.py`: mutmut mutates a changed file whole and copies each function per mutant, so keeping it apart and in short functions keeps a PR here from regenerating all of `mutants.py`, which python 3.14 parses superlinearly): in a worktree at head, in the project dir. The shard's changed production files (round robin, as Stryker's) give the `{mutate}` ranges; no changed file in the shard is `pass` 0/0 with no run. The report path is cleared first without following a link: a link or a file where a dir goes, or a report (or dir) the checkout holds at `report`, is removed from the worktree, so a committed report is never read as the run's and nothing outside the worktree is touched (the built-in ts still removes a committed `reports/mutation/mutation.json` as before, following a link there: a follow-up in `mutants.py`); a path that cannot be cleared is an R3 `fail` (agent-fixable), never `n/a`. A report the run leaves as a link out of the project dir is not read: an R3 `fail` (agent-fixable). A command that is missing or fails its version probe is `n/a (env)` naming the key: `` mut not installed (env): `mut` not runnable (mutation.tool.command); install it (setup-command) or set mutants-cmd ``. The workflow installs nothing for a declared tool: `setup-command` (or the stack's own toolchain step) does; for a `ts` override, the mutants job passes its own Stryker binary as `--mutants-cmd`, which replaces `command`. No report: `partial` when the budget stopped the run (tested and total unknown), a `fail` when `baseline_failed` matched, else a `fail` with one `agent-fixable` entry (``mut ran and wrote no report (out/report.json): mutants not read: <first line>``, #22), or a `CI` entry (check `CI`, class `env`, as a job with no result) when the output shows a dependency fetch failed (`Could not resolve`, `Could not transfer artifact`, `Unknown host`: the runner, not the PR): the tool is installed and ran, so it is no toolchain absence, and the cause is usually the code at head (it does not build under the tool) or the tool's setup; never `n/a (env)` and never a pass. The built-in ts still reads a Stryker run with no report as `n/a (env)` (a follow-up: an edit to `mutants.py` makes every later R3 regenerate all of it). A report that is not its format's (not JSON or XML, an unknown status, a mutant that is not an object, nesting too deep, more than 64 MiB, not UTF-8, an XML encoding declared other than UTF-8, a line number that is not ASCII digits) is `n/a (env)` naming the file: `mut report out/report.json is malformed (env): <why>`, never a pass. The readers catch every error their parsers raise on such input (each case has a test); the lines reader is linear in the report's size, but a declared `pattern` that backtracks badly is not time-bounded while the report is read.

Report formats, and what each status means:

| | MISSED | caught | timeout | unviable | not counted | untested |
|---|---|---|---|---|---|---|
| `mutation-testing-elements` (Stryker, Stryker.NET, mull: `files.<path>.mutants[]`) | `Survived`, `NoCoverage` | `Killed` | `Timeout` | `CompileError`, `RuntimeError` | `Ignored` | `Pending` |
| `pit-xml` (PIT's `mutations.xml`) | `SURVIVED`, `NO_COVERAGE` | `KILLED` | `TIMED_OUT` | `NON_VIABLE`, `MEMORY_ERROR`, `RUN_ERROR` | | `STARTED`, `NOT_STARTED` |
| `lines` | `status.missed` | `status.caught` | `status.timeout` | `status.unviable` | | |

- **Elements JSON**: a file key relative to the project dir, or absolute under it; one outside it (`..`, another absolute path) is outside the diff. The line is `location.start.line`; a mutant without one is unlocated. A `Survived` mutant a test covers that completed no test (`coveredBy` set, `testsCompleted` 0) means the runner never ran it: R3 `n/a (env)`, as for the built-in ts. The description is `Mutator `original` -> `replacement`` (no line in it).
- **PIT XML**: read with the stdlib parser after a refusal of any DTD or entity declaration (`<!DOCTYPE`, `<!ENTITY`: no external entity, no expansion), of a wide or non-UTF-8 encoding (a NUL byte, or an `encoding=` other than UTF-8: UTF-7 or UTF-16 would hide a declaration from that check), and of a `lineNumber` that is not ASCII digits (unlocated). PIT names a file by package and file name (`com.example.Calc`, `Calc.java`): the path is `com/example/Calc.java`, matched to the one tracked file under the project dir that ends with it; several such files are unlocated, none is outside the diff. The description is `Mutator in method: description`.
- **Lines**: the pattern runs over the report's text; each match is one mutant. A status word in no list, a `line` that is not a whole number from 1, or a match in which `file`, `line` or `status` took no part refuses the report.
- A `Survived` mutant whose tests never completed makes this shard's R3 `n/a (env)` only when it is this shard's (its file's shard).
- MISSED on a changed line of this shard's files is a `fail` entry (agent-fixable; `NoCoverage`/`NO_COVERAGE`: the hint says no test reaches the line); MISSED on another line is counted `outside the diff` in the note; unlocated MISSED mutants are one `confirm` entry. Each mutant is one shard's: its file's, or shard 0's for a file no shard holds, so a tool that mutates more than `{mutate}` asks counts each once in the merge. The note: `tested/total tested: N missed in the diff, N missed outside the diff, N unlocated, N caught, N timeout, N unviable`.
- **What this does not stop.** The mutants job is not a sandbox: it runs the PR's code (the tests the tool runs, and the tool reads the PR's tree). A tool such as `mvn` or `gradle` reads the PR's own build file, and PR code that runs earlier in the job (a dependency's install script, or `setup-command` reading the checkout) can change `PATH`. The program rule above keeps the base's declared tool from being a file the PR supplies; it does not make the run trusted. A project-local tool dir on `PATH` (`.venv/bin` or `node_modules/.bin` under the checkout) gives the `tool-in-checkout` fail by design: install the tool outside the checkout.
- **Editing the tool needs a person.** R0's [editing rules](#r0-adapter-proof) give the one `needs-human` entry for a PR that adds, removes or changes an adapter file's `[mutation.tool]` (any value: after the merge every later PR's R3 runs the new tool, or none), as for a loosened limit or a changed target OS: `[mutation.tool] of the stack in folder `lib` changed (build/m.toml)`.
- Budget, partial and shards as for Stryker ([R3 cap](#r3-cap-risk-order-and-shards)): the `baseline` job counts one shard per changed production file, at most 4 (git only); a budget hit after the report keeps its MISSED; a `Pending` mutant is untested, never a pass. The tool lists no mutant before its run, so `max-mutants` is not applied and the note says so (`max-mutants not applied: <name> makes its own mutants (no listing before its run): every changed line runs, the budget the only stop`). `scripts/r3-local.py` runs the built-in stacks only.

TS ships its R3 in `ts.toml`: Stryker 10.0.0 through `[mutation.tool]` (program `stryker` on `PATH`, never the checkout's `node_modules/.bin`: CI passes its own pinned install as `--mutants-cmd`; locally put `stryker` on `PATH` or pass `--mutants-cmd`; format `mutation-testing-elements`, `--mutate file:a-b` ranges, the vitest temp config and jest's `--testRunner jest` as `runners`), and passes `tests/mech-ts-mutants.test.sh` unchanged with the same R3 entries as the built-in (`tests/py/test_adapter_mutation_ts.py`). The one difference: the built-in counts Stryker's mutants first with its instrumenter, so it applies `max-mutants` by changed lines (#63); through the file it is not applied.

### Run side (R1 and R4)

`[commands]` (required with `[run]`): the stack's commands, each a shell command string. Every key is required; `""` says the stack has none (a missing key is a load error that names it: `commands.build: missing: want the command that builds the project, or "" when the stack has none`).

| Key | Value |
|---|---|
| `install` | installs the project's dependencies (`npm ci`). A missing runner's `n/a (env)` note names it as the fix |
| `build` | builds the project (`""`: no build step before the tests) |
| `lint` | lints the project |
| `test` | runs the whole test suite. R1 and R4 start every one-test run from it (`--test-cmd` replaces it); with `[run]` it may not be `""` |

R1 and R4 use `test` only. `install`, `build` and `lint` are for ci-doctor (the base CI jobs it writes) and the session's default verify commands; the engine never runs them. Each command is split as the engine splits it (shell words), so unbalanced quotes are a load error that names the field. A declared-none `install` or `build` is named in the result of `red` and `all` with `--adapter` (`r2` through a file prints exactly what the built-in prints): the JSON envelope's `notes` list (`adapter file declares no build command (commands.build = "")`; `[]` when the file names both) and a `note:` line under the summary in text format.

`[run]` (optional; without it the file is R2 only): how one named test runs and how its result reads.

| Key | Value |
|---|---|
| `test` | words put after the test command's words to run one test: `["{path}", "-t", "^{name}$"]`. `{path}` is the test's file (project-dir relative), `{name}` the runner's name for the test; at least one word has `{name}`. Plain placeholders only, as in the R2 templates |
| `links` | optional: directories (project-dir relative) linked from the caller's checkout into each R1/R4 worktree, when the caller has them as directories and the commit does not (an install git ignores: `["node_modules"]`). The caller's copy is never changed |
| `[run.name]` | optional: how a name part becomes the runner's text. `escape`: characters that get a backslash before them (a regex filter: `'\^$.|?*+()[]{}/'`); `placeholders`: a regex for parts of a name that stand for any value (`it.each`'s `%s`), no capturing group; `any`: what a placeholder becomes (`.*`). Without it the name is passed as it is |
| `[[run.runner]]` | optional, one table per runner of the stack (vitest, jest). `name`; `match`: text in one of the command's words that makes the command this runner's (one without `match` takes any command, so it comes last); `command` and `when`, together (one without the other is a load error: it would never be used): the command for a checkout where `when` holds (not blank); `subcommand`: `{ word, after }`, a word put in after the first command word holding `after` (else at the end) when the command lacks it (vitest's `run`); `separator`: how the runner joins group and test names (default `tests.separator`) |
| `[run.outcome]` | how a run's output reads (below) |
| `[run.list]` | optional (#21): how the runner lists every test it collects, for [R0's census](#runtime-half). `command`: the whole listing command (`node_modules/.bin/vitest list`); `pattern`: a regex over its output with a named group `name` (the runner's full name of a test) and optionally `file` (its file, project-dir relative), only those groups; `separator`: how the listing joins group and test names (default the runner's `separator`, else `tests.separator`); `runner`: the `[[run.runner]]` it lists for (a checkout that picks another runner has no census). A listing that exits non-zero or matches `build` failed |

The test's qualified name is split at `tests.separator`, each part quoted by `[run.name]`, and the parts joined by the runner's `separator`. The runner for the argv is the first `[[run.runner]]` whose `match` is in a word of the command; the command for a checkout is the first runner whose `when` holds in the project dir, else `commands.test`. `when` is `{ file }` (the file is there; a name with an empty or `.` part, such as `./`, is a load error) or `{ file, tables, has, lacks }`: the file is JSON, and its `tables` (`["dependencies", "devDependencies"]`) hold every `has` name and no `lacks` name. A file that is missing or not JSON never holds.

`[run.outcome]`: python regexes over the runner's output (multiline: `^` and `$` match at line ends), compiled at load, so a bad one is a load error that names it. So is a pattern with a zero-width match (`x?`, `a*`, `^`, `\b`): it would match a run with no output to speak of, and read a test that never ran as `build` (red on the base) or every run as `env`. The same holds for `[run.name] placeholders`. The load check probes a few short texts, so a lookaround can still load (`(?<=[a-w])`); at run time only a match that holds text counts, for every outcome pattern and for placeholders, so such a pattern matches nothing and never reads a run as `build`, `env`, `none` or a count.

| Key | Value |
|---|---|
| `passed` / `failed` | the passed and failed counts: one capturing group, the number (`'(\d+) passed\b'`). Every match is added up |
| `summary` | optional: the counts are read from the last line it matches (its capturing group, when it has one: `'^\s*Tests\b:?(.*)$'`); without it, from the whole output |
| `skipped` | optional: a skipped count, read like `passed` |
| `build` | optional: the code did not build or load (`Cannot find module`) |
| `no_test` | optional: the runner found no test of that name; R1's and R4's entries quote the line it matched |
| `env` | optional: the runner started but its toolchain is missing; the run is `n/a (env)` and its note quotes the line the pattern matched. It reads only when no count was read (#22): output that holds a summary or a count is the tests', so anchor it to the toolchain's own lines |

The verdict of one run, in this order: no executable is `env` (the note names the executable and the install command); a timeout is `timeout`; `env` matches, when no count was read (no summary line, or no count pattern matched: #22, so a test that prints the toolchain's message is judged by its counts), is `env`; a failed count is `fail`; a passed count is `pass` at exit 0, `fail` at any other exit; `build` matches is `build` (on the base's code: compile-red, which counts as red); `no_test` matches is `none`; no count read at all (no summary line, or no count pattern matched) is `error`; a skipped count is `none`; counts that are all 0 are `none` at exit 0, `error` otherwise. So `pass` needs a counted passed test: a test that did not run reads `none`, never `pass`. R1 and R4 read these verdicts exactly as they read the built-ins'.

The TS run side, from `ts.toml`:

```toml
[commands]
install = "npm ci"
build = ""
lint = ""
test = "node_modules/.bin/vitest run"

[run]
test = ["{path}", "-t", "^{name}$"]
links = ["node_modules"]

[run.name]
escape = '\^$.|?*+()[]{}/'
placeholders = '%[sdifjoOp#%]|\$\w+'
any = ".*"

[[run.runner]]
name = "jest"
match = "jest"
command = "node_modules/.bin/jest"
when = { file = "package.json", tables = ["dependencies", "devDependencies"], has = ["jest"], lacks = ["vitest"] }
separator = " "

[[run.runner]]
name = "vitest"
subcommand = { word = "run", after = "vitest" }
separator = " "

[run.outcome]
summary = '^\s*Tests\b:?(.*)$'
passed = '(\d+) passed\b'
failed = '(\d+) failed\b'
build = 'Transform failed|Failed to load url|...|Failed Suites'
```

Trust: R1 and R4 run the file's commands in `red-first` only, the job that already runs PR code with a `contents: read` token and no secrets; `guard` runs none of them. The workflow passes no adapter file yet; when it does, adapter values reach `run:` steps only through `env`, as `setup-command` does (`tests/mech-review-workflow.test.sh` holds both rules).

### Parser

For a language the lexer table cannot describe (Ruby, Elixir, indentation- or DSL-heavy test styles), an adapter file declares one parser command in place of the patterns (#27). Such a file has `format`, `name`, `extensions`, optionally `manifests`, `target-os`, `[limits]`, `[mutation]` (`config_files`, `config_name`) and the run side, `[commands]` and [`[run]`](#run-side-r1-and-r4) (#18: it reads the runner's output, not source, so it is the same beside a parser), and `[parser]`. The pattern tables `[lexer]`, `[tests]`, `[functions]`, `[asserts]`, `[[suppressions]]` and `mutation.skip_comments` are an error beside it (`lexer: not with [parser]`): the facts come from the command alone, never from both, and a failed parser never falls back to patterns.

`[parser]`:

| Key | Value |
|---|---|
| `command` | the parser program and its options, as one string split into words as a shell would (quotes group; no shell runs it). An allowlist, so anything else is an error naming the word: the first word is one bare program name, `[A-Za-z0-9][A-Za-z0-9._-]*` (no `/`, no `\`, no path), that the package installs (`rb-test-facts`); it is no interpreter or shell (`python*`, `pypy*`, `node`, `nodejs`, `deno`, `bun`, `ruby`, `irb`, `perl*`, `php*`, `lua*`, `Rscript`, `R`, `java`, `jshell`, `kotlin`, `scala`, `groovy`, `tclsh`, `osascript`, `env`, `busybox`, `awk`, `sed`, `xargs`, `nohup`, `timeout`, `nice`, `time`, `sudo`, `doas`, `su`, `exec`, `sh`, `bash`, `zsh`, `dash`, `ksh`, `csh`, `tcsh`, `fish`, `pwsh`, `powershell`, `cmd`, and the REPLs, script runners and package managers `ipython`, `ptpython`, `bpython`, `ts-node`, `tsx`, `py`, `npx`, `pnpx`, `bunx`, `yarn`, `pnpm`, `npm`, `uvx`, `pipx`, `pdm`, `poetry`, `hatch`, `rye`, `cargo`, `go`, `gem`, `bundle`, `rake`, `mix`, `elixir`, `iex`, `erl`, `escript`, `julia`, `swift`, `dotnet`, `mono`, `ghci`, `runghc`, `clojure`, `clj`, `sbcl`, `guile`, `racket`, `node-repl`; any case, `.exe` or not). A package whose program evaluates its input (a REPL, a script runner or a package manager) is never a parser. Every later word is a long option, `--name` or `--name=value`: name `[a-z][a-z0-9-]*`, value `[A-Za-z0-9._:/@+-]+`, not starting with `/`, `~` or `-`, with no `..` segment. No short option, no bare word, no `-` (stdin as a program). At run time the program is resolved only in the package's install dir (below), never from PATH, and a word holding a path inside the reviewed checkout (each `/` starts one, as written or resolved; a sibling `/repo2` is not inside `/repo`), the resolved program path included, is refused before anything runs (the one `CI` entry below), in R2 and in R0's own runs |
| `installer` | how the parser is installed: `pip`, `npm`, `cargo`, `gem` or `go` (nothing else). The core builds the install steps into a prefix of its own, `<home>/<installer>/<package>/<version>` (`parser_cmd.install_steps`, which the workflow's install step runs: [below](#parser)), and runs the program from that prefix only (`parser_cmd.program_path`): pip `python3 -m venv <prefix>`, then `<prefix>/bin/python -m pip install <package>==<version>`, program `<prefix>/bin/<name>`; npm `npm install --no-save --prefix <prefix> <package>@<version>`, program `<prefix>/node_modules/.bin/<name>`; cargo `cargo install <package> --version <version> --locked --root <prefix>`, program `<prefix>/bin/<name>`; gem `gem install <package> -v <version> --install-dir <prefix> --bindir <prefix>/bin`, program `<prefix>/bin/<name>`, run with `GEM_HOME` and `GEM_PATH` set to the prefix; go `env GOBIN=<prefix>/bin go install <package>@v<version>`, program `<prefix>/bin/<name>`. Only the parser package itself is pinned: its dependencies resolve at install time (pip installs them; no `--no-deps`). `<home>` is `$EKIT_PARSER_HOME`, else `~/.cache/ekit/parsers`: set by the workflow's install step and by ekit's tests, never read from a PR. A program the declared package did not install there (missing or not executable) is the one `CI` entry: ``parser `<name>` … not installed by the declared package`` |
| `package` | the package name, as the installer names it, and nothing else: pip `[A-Za-z0-9]` then letters, digits, `.`, `_`, `-` (ending in a letter or digit); npm lower case, optionally scoped (`@scope/name`); cargo a letter then letters, digits, `_`, `-` (64 at most); gem letters, digits, `.`, `_`, `-`; go a module path with a dotted host (`example.com/x/cmd/facts`, no `.` or `..` segment). A URL, space, option, `@`, `=`, `;` or version in it is an error |
| `version` | one release, exactly: pip `1.4.2`, `2.1rc1`, `1.0.post1`, `1.0.dev2` (no epoch or local part); npm and cargo semver `1.4.2`, `1.0.0-beta.1`; gem `1.4.2`, `1.4.2.pre`; go semver with or without a leading `v`. A range (`>=1.0`, `~=1.0`, `^1.0.0`, `1.0.*`), `latest` or two versions is an error |
| `timeout` | optional, default `30`: seconds per file, 1 to 600 |
| `skipped_text` | optional: the R2 problem for a newly skipped test, `{name}` is the test (as `tests.skipped_text`) |

How it runs: once per source file side R2 reads (base and head), with the file's text on stdin and its path (at head, or at base for a deleted file) as the last argument: `argv = [<prefix>/…/<program>, *options, path]`, the program resolved in its package's prefix. Its cwd and `HOME` are a fresh empty temp dir (no checkout, no project config), its environment is `PATH`, `HOME`, `TMPDIR`, `LANG` and `LC_ALL` only (no token, no secret), and it is stopped (its whole process group) at the timeout. R2 reads the adapter file it is given; in CI that is the base branch's copy (ADR 0001), so a PR never runs a parser command or install step of its own. R0, which proves the PR's copy, runs its parser only when that copy's `[parser]` `command`, `installer`, `package` and `version` equal the base branch's (see [R0](#r0-adapter-proof)). For a file renamed in the PR, the base text goes with its base path and the head text with its head path. `r2` and `r0 --stack <name>` with the repo's adapter file for that name at the base ([stack resolution](#stack-resolution), #17) take this path too: R2 runs the base copy's parser, and R0 proves the base copy, so a parser the PR wrote or changed never runs. The workflow installs the parser (the step `install the declared parser`) in each job whose engine call reads source with the adapter: `guard` (R2, and R0's runs of the base's parser) and `red-first` (R1 and R4 name the changed tests from the facts), before the engine steps. `plan`, `baseline` and `mutants` read no source with the adapter (changed paths, the mutation tool's report), so they install nothing. The step runs `mech-review.py parser-install --base <base sha> --stack <leg's stack> --project-dir <leg's dir> --home <dir>`, which reads the adapter file r2 reads, at the base, by the same lookup (the plan entry's file for that folder, else `.ekit/adapters/<stack>.toml`), never the head's, so what it prints is the base's whatever the PR edits in `[parser]`. In `guard`, which runs no PR code, that holds for what is installed too: a PR cannot change it. In `red-first` it does not: the step runs after PR code (`setup-command`, the TS dependencies' install scripts, the python stack's requirements venv, first on `PATH`), and that code can steer the install, through what it writes to `GITHUB_ENV` (`PIP_INDEX_URL`, `NPM_CONFIG_REGISTRY`), a fake `npm`, `cargo` or `env` it puts on `GITHUB_PATH`, or a prefix it plants under the home (pip reads a planted package as already installed, and the planted program runs). There the parser, and so R1 and R4's reading of the changed tests, is only as trustworthy as the PR code the job runs, as for the [mutation tool](#r3-side-mutation-tool) in `mutants`; `guard` keeps the guarantee. It prints `{stack, adapter, steps, program}`: `steps` the `install_steps` argv lists (empty for a built-in, a stack with no adapter file, or a file without `[parser]`), `program` where the parser is after them (`program_path`, else null); exit 2 with a message (never a traceback) for a bad ref, a `--project-dir` outside the repo, a relative `--home` or a base adapter file that does not read. The step runs each list as argv in order, never through a shell, in a fresh empty dir under the runner's temp dir (never the checkout: `python -m pip` imports from its cwd), with `EKIT_PARSER_HOME` set to `$RUNNER_TEMP/ekit-parsers` (empty when the job starts), which it also writes to `GITHUB_ENV` for the job's later engine steps. Its values reach it through `env` only. The installer (`python3`, `npm`, `cargo`, `gem`, `go`) is the runner's: `guard` has no toolchain or `setup-command` step, so its parser installs with what `ubuntu-latest` ships; `red-first` installs after `setup-command` and before R0's runtime cache steps (#21), so the cache dir is cleared after the install: nothing a steered install plants there reads as a pass. A failed install (an installer missing on the runner, a step that exits non-zero, no program at `program` afterwards, an engine error) fails the step with an `::error::` naming it, and the job goes on (`continue-on-error`, as for cargo-mutants): R2 then gives the one `CI` entry `not installed by the declared package`, so a failed install is never a pass. In `red-first` the same failure makes `red` (and `all`) exit 2 with `mech-review: the adapter's parser failed: parser `<name>` … not installed by the declared package`, never a traceback: the step goes red with that line, and the report fails R1 and R4 with a `CI` entry for the job's missing result.

What ekit does not do: it does not sandbox the parser. The base branch's `[parser]` is configuration the repo's owner trusts, like a CI step. ekit allows only an installed program with long options, resolves it in the declared package's own prefix, refuses a checkout path in any word and, in R0, a `[parser]` the PR changed; it runs the program with no checkout as its cwd and no secret in its environment, and stops it at the timeout. A program that opens the checkout by itself (it is on the same machine and can find it) is not stopped. So the program must be an installed tool, installed by `installer`, that reads only its stdin and the path argument (which names the file, never to be opened). The install is not sandboxed either: the workflow's install step runs the declared package's install and build code (pip's build backend, npm install scripts, a cargo build script) and that of its dependencies, which are not pinned (they resolve at install time), in `guard` before R2, with `GITHUB_ENV` and `GITHUB_PATH` writable. That is the same owner trust (ADR 0001): the base branch's adapter file names the package, as a CI step would.

A command that cannot run, exits non-zero, times out, prints more than 16 MiB, or prints what the schema below refuses gives one R2 entry for the whole run: check `CI`, class `adapter-fix`, `fail`, on the first file it failed on (``the adapter's parser failed: parser `rb-test-facts` on spec/calc_spec.rb: printed invalid JSON: …``). It is not `n/a`: R2 is the hard guard, so it fails until the parser or its install step is fixed in a PR of its own. The path rules (protected paths, mutation config) still give their entries; no file gives any other.

Facts: one JSON object on stdout, the adapter interface (`scripts/mech_review/stack.py`) serialized. Every key is required and no other key is allowed, at any level; a key given twice, `NaN` or `Infinity`, output that is not UTF-8, a string longer than 65536 characters, a list longer than 100000 entries, and arrays or objects nested more than 32 deep (the facts nest 4 deep; ekit counts it itself, so the limit is the same on every Python) are refused. Every string has something besides whitespace in it and holds no lone surrogate (it has no UTF-8 form) and no control character (C0, DEL, C1); an assert's `left`, `right` and `text` and a parse error's `message` may hold tabs and line ends (a formatter wraps long asserts; operands are compared with whitespace removed), names stay on one line, and a raw ESC or other control character in an operand is refused, so a source line that holds one cannot be read by a parser. An assert with a `test` sits within that test's lines (`line` to `end_line`, of one test of that name).

| Key | Value |
|---|---|
| `format` | `1` |
| `parse_error` | `null`, or `{"line", "message"}`: the file does not parse (an R2 `needs-human` fail, as with the lexer); the lists are then not read |
| `tests` | `[{"name", "line", "end_line", "markers", "body", "calls"}]`: `name` the test's full name (groups included); `line` where it starts, `end_line` where it ends; `markers` a list of `ignore` (skipped), `only`, `should_panic`, each at most once; `body` `null` or `[first, last]`, the lines R2 compares to pair a renamed test (inside `line`..`end_line`); `calls` the names the test calls (an assert moved into a helper it calls is no drop) |
| `asserts` | `[{"line", "test", "owner", "kind", "left", "right", "text"}]`: `test` the name of the test it is in (one of `tests`), or `null` outside tests; `owner` the innermost test or function holding it, or `null`; `kind` `eq`, `ne` or `other`; `left`, `right` the operands as strings for `eq`/`ne` (compared with whitespace removed), `null` for `other`; `text` the assert as written (for messages, and compared for `other`) |
| `suppressions` | `[{"line", "end_line", "kind", "lints", "reason"}]`: the lines it silences; `kind` the directive; `lints` the name the entry gives (`lint-off unused`); `reason` `true` when it gives one |
| `mutation_skips` | `[{"line", "end_line", "marker"}]`: a marker that hides production code from R3 |

A line is a whole number (`true` and `1.0` are not) from 1 to the file's line count (its newlines plus one), and an end is never before its start. Example, for `test("adds", {\n  assertEquals(3, add(1, 2))\n})\n`:

```json
{"format": 1, "parse_error": null,
 "tests": [{"name": "adds", "line": 1, "end_line": 3, "markers": [], "body": [2, 2], "calls": ["add", "assertEquals"]}],
 "asserts": [{"line": 2, "test": "adds", "owner": "adds", "kind": "eq", "left": "3", "right": "add(1,2)",
              "text": "assertEquals(3, add(1, 2))"}],
 "suppressions": [], "mutation_skips": []}
```

R0 proves a parser-backed file as it proves a pattern one: the same cases on the same fixtures (`<adapter>.r0/`, each fixture given to the parser at its own path, `.ekit/scenarios/r0/<case><ext>`), and the malformed-table cases, which add a pattern table, fail to load cleanly. It runs the parser only when the file's `[parser]` `command`, `installer`, `package` and `version` equal those of the same file on the base branch. When they differ, the base branch has no `[parser]` there, or the file is outside the repo, the command never runs: every case that reads source is `unproven`, the malformed-table cases still run (they only load the file), and one `needs-human` entry (check `R0`) says `parser command changed: a person reviews it before it runs (…)`. It blocks nothing; R2 still reads the base branch's adapter. `tests/fixtures/parser/canned_facts.py` prints facts written by hand per text, with no ekit import. `tests/fixtures/parser/mini_facts.py` is a stub parser for the worked example's language; `tests/py/test_parser_cli.py` checks that it gives the same R2 entries as `mini.toml` and that R0 passes it.

### Fixed, not configurable

`block_style = "braces"` fixes these, and an adapter file cannot change them. A language that differs here cannot be described yet. Even a brace language needs call-style or marker-declared tests, as above, so Go and C# test files cannot be described today (Java/JUnit can, #22). The fixed rules:

- a call opens with `(`;
- a block (`{...}`, `...{...}`, `BODY`) opens with `{`, and a `BODY` expression ends at `;`, a line end or a closing bracket;
- inside a regex literal, `\` escapes, `[...]` is a class (the delimiter does not end it there), and flags after it are letters, digits and `_`;
- a regex literal must close on its own line; otherwise its delimiter is read as division;
- a suppression directive ends at a character that is not a letter, digit, `_` or `-`;
- a `skip_comments` phrase ends at a character that is not a letter, digit or `_` (`Stryker disabled` is not `Stryker disable`);
- a template (`skipped_text`, `problem`, `hint`) takes plain `{field}` placeholders and `{{` / `}}` only: a `!` conversion or `:` spec is an error;
- `ident_chars` may not hold whitespace, a bracket, a string quote, a comment opener or the `member` character, and `member` may not be a word character, whitespace or a bracket.

### Worked example

A made-up language where tests read `suite("Calc", { test("adds", { assertEquals(3, add(1, 2)) }) })`, comments start with `#`, and `# lint-off rule -- why` silences a lint on the next line:

```toml
format = 1
name = "mini"
extensions = [".mini"]

[lexer]
block_style = "braces"
brackets = ["()", "[]", "{}"]
line_comments = ["#"]

[[lexer.strings]]
quote = '"'
escape = '\'

[tests]
style = "calls"
groups = ["suite"]
cases = ["test", "xtest"]
skip = ["xtest"]
separator = " / "
skipped_text = "test `{name}` marked xtest"

[[asserts.call]]
names = ["assertEquals"]
kind = "eq"
operands = [0, 1]

[[suppressions]]
directives = ["lint-off"]
covers = { "lint-off" = "next-line" }
lints = "rules"
reason_after = "--"
```

With it, R2 reports ``test fn `Calc / adds` removed`` for a deleted test, ``test `Calc / adds` marked xtest`` for a newly skipped one, ``expected value changed in `Calc / adds`: was 3, now 4`` (confirm) for `assertEquals(4, ...)`, and `` `lint-off unused` added without a reason `` for a bare `# lint-off unused`. `tests/fixtures/adapters/mini.toml` is this file plus a manifest and an `other` assert, used by `tests/py/test_adapter_cli.py`.

## Java reference adapter

`tests/fixtures/adapters/java.toml` (#22) is a **test fixture, not a supported built-in**: a hand-written adapter for Maven, JUnit 5 and PIT that proves the format and the engine can express Java before an agent is asked to generate an adapter (#23). When a generated adapter fails, comparing it with this one shows whether the engine or the agent is at fault; #25 deletes it once the generated adapter holds up. Nothing offers it: `resolve`, `auto` and `--stack` see the built-ins and a repo's `.ekit/adapters/<name>.toml` only, so it runs only when named with `--adapter`.

```
python3 -I scripts/mech-review.py all --repo . --base main --head HEAD --stack java \
  --adapter tests/fixtures/adapters/java.toml --test-paths 'src/test/**' --head-branch claude/x
```

- **Tests**: `style = "declared"` (`@Test`, `@ParameterizedTest`, `@RepeatedTest`, `@TestTemplate` in `class` groups; `@Disabled` and each of JUnit's conditions, `@DisabledOnOs`, `@EnabledOnOs`, `@EnabledIf`, ..., skip, since any can stop the test from running; a generic method's `<T ...>` is read past), named `CalcTest.adds`; JUnit `Assertions` statically imported (`Assertions.assertEquals(` is a member call, not read) and AssertJ's `assertThat(x).isEqualTo(y)`; `// NOPMD - why` as the suppression. `@SuppressWarnings` is an annotation, not a comment: not read.
- **Run side**: `mvn -B -ntp test -Dtest=CalcTest#adds` (`[[run.runner]]` joins class and method with `#`), read from surefire's last `Tests run: N, Failures: F, Errors: E, Skipped: S` line (passed is N when F, E and S are 0); `COMPILATION ERROR` is build; a missing JDK is env, anchored to mvn's own lines (`^The JAVA_HOME environment variable is not defined correctly`, `^\[ERROR\] .*No compiler is provided`) and read only when no count was, so `n/a (env)`, as is `mvn` missing; a failing test that prints either line is still `fail`. `target-os = "linux"`; `[commands]`: install `mvn -B -ntp dependency:go-offline`, build `mvn -B -ntp test-compile`, lint the same with `-Dmaven.compiler.failOnWarning=true` (javac's warnings: the project's `-Xlint`), test `mvn -B -ntp test`.
- **Census**: JUnit Platform's dry run (`-Djunit.platform.execution.dryRun.enabled=true`, JUnit 5.10 or newer) through surefire with its plain report on the console: the runner discovers every test as a run does and executes none, printing `com.example.CalcTest.adds skipped` per test. The package-qualified name matches the scanner's `CalcTest.adds` by its tail. Chosen over the Console Launcher's `discover`, which needs the test classpath assembled and runs under `java` (a launcher R0 does not probe) or needs a plugin in the project's pom. The census cannot see what the dry run does not list, which it allows (only listed tests must be found): `@ParameterizedTest`, `@RepeatedTest` and `@TestTemplate` methods (templates: their invocations are made at run time; R4 still runs them), and a test in an inner class without `@Nested`, which the scanner finds and JUnit never runs (R4 reads it as did not run). `@TestFactory` is no case: its method returns the tests, and no void shape matches it.
- **R3**: PIT through `[mutation.tool]`, pinned in the adapter: `org.pitest:pitest-maven:1.17.4:mutationCoverage`. The PR's pom still gives the plugin's configuration and its dependencies (`pitest-junit5-plugin`), so `[mutation] config_files = ["pom.xml"]`: any pom edit is R2's `needs-human` entry `PIT config (pom.xml)`, as `[tool.mutmut]` is for python, and `skip_annotations` names PIT's own skips (`@DoNotMutate`, `@Generated`, `@CoverageIgnore`). `-DtargetClasses={mutate}` with `mutate = "{package}*"` (every class in each changed file's package, a second top-level class too; `Top*` for a file in the default package), then ekit's changed-line filter on `target/pit-reports/mutations.xml` (`pit-xml`); a changed `.java` file outside `src/main/java` is not mutated and is named. **Cost**: PIT's `*` crosses dots, so `com.example.*` mutates `com.example.sub.Deep` too, and every class of the package is mutated and its tests run, though only the changed lines' MISSED count. The result stays right, but on a large package the budget can end the run first and R3 reads `partial` (never `pass`); narrowing the glob would lose a second top-level class, so it is kept. **What else sets PIT or surefire options for a PR**, each checked: any `pom.xml` (a module's or a parent's in the repo; a parent from a repository changes only through the pom's version) and `.mvn/maven.config`, `.mvn/jvm.config`, `.mvn/extensions.xml` are `config_files`, so an edit is R2's `needs-human` entry; a `settings.xml` in the repo is read only when named (`-s`, which only `maven.config` can add); `MAVEN_OPTS` and `~/.mavenrc` / `/etc/mavenrc` are the runner's, not the checkout's (PR code that runs earlier in the job could still set them: the [trust note](#r3-side-mutation-tool)); PIT reads no properties file of its own. Not caught: a profile in the base's pom activated by a file the PR adds (`<activation><file><exists>`): the activation is the base's own config, so a repo that has one should not; and an annotation that is itself meta-annotated (`@MySkip` declared `@Disabled`), which JUnit honours and R2 does not read. The program is `mvn` on PATH: not a launcher in [`[parser]`](#parser)'s list, and never `./mvnw` (a path in the checkout). `mvn` reads the PR's pom, as the [trust note](#r3-side-mutation-tool) says.
- **R0**: its fixtures sit beside it (`java.r0/`: the static cases, and `runtime/` with `test-paths = ["src/test/**"]`); `r0 --adapter` and `all --adapter` both prove the file with them (`all` used to look for the built-in's of its name: #22). Static half 17 of 17; runtime half on linux with the real toolchain: census 4/4 on the fixture repo and on the fixture project, the five controls, the R3 control.
- **Not expressible yet** (found on the way, left for #23/#25): `@Nested` classes (surefire names them `Outer$Inner#test`; `[run]` joins every name part with one separator, and the listing prints `Outer$Inner.test`), annotation suppressions (`@SuppressWarnings`), composed annotations (a `@MyTest` or `@MySkip` that is meta-annotated `@Test` or `@Disabled`: the census sees a composed test, as listed and not found; a composed skip is not caught), an assumption that stops a test from its body (`assumeTrue(false)`: R2 gives no entry; R4 reads the test as did not run), and the JDK's version in the fingerprint (the probe keeps `mvn --version`'s first line only).
- `tests/py/test_java_reference.py` runs it on `tests/fixtures/java/` (`base/`, and the heads `r2`, `red`, `weak`, `broken`), with the real toolchain where it is installed and `n/a (env)` where it is not; `tests/py/test_adapter_declared.py` and `tests/py/test_adapter_module.py` test the format additions without one.

## R0 adapter proof

R0 proves that the stack's adapter reads tests the way the checks need. It is deterministic, its inputs are frozen files, and no model is involved. The **static half** (#20): git and the adapter only, no test runner, in seconds, in the guard job. The [runtime half](#runtime-half) (#21) measures the adapter against the test runner, in `red-first` and `mutants`, only when its fingerprint changes.

```
python3 -I scripts/mech-review.py r0 --repo . --base main --head HEAD --stack python --test-paths 'tests/**'
python3 -I scripts/mech-review.py r0 --repo . --base main --head HEAD --stack mini --adapter .ekit/adapters/mini.toml
```

- **Cases.** Each runs as one PR in a throwaway git repo (new files at `.ekit/scenarios/r0/<case><ext>`, never patches against real files): the seed on base, the case on head.

  | Case | Kind | Must give |
  |---|---|---|
  | `delete`, `comment-out` (the core makes them from the seed) | cheat | R2 `fail`: test removed |
  | `rename` (the core: renamed and an assert dropped) | cheat | R2 `fail`: test removed |
  | `skip` | cheat | R2 `fail`: test marked ignored or skipped |
  | `expected-value` | cheat | R2 `confirm`: expected value changed |
  | `weaken-assert` | cheat | R2 `confirm`: assertion replaced |
  | `suppression` (no reason) | cheat | R2 `fail`: suppression without a reason |
  | `rename-same-asserts`, `reorder-asserts` (the core) | control | no entry |
  | `helper-asserts` (asserts moved into a helper the test calls) | control | no entry |
  | `empty-diff` (R2 on an empty diff of every fixture file) | control | no entry |
  | `source-ident-chars` (a test renamed with characters outside the identifier set, its assert gone) | malformed source | any R2 `fail`: a parse error or the removal |
  | `source-empty-asserts` (a test whose asserts are all gone) | malformed source | R2 `fail`: fewer asserts |
  | `source-unbalanced-brackets` | malformed source | R2 `fail`: the file does not parse |
  | `ident-chars`, `empty-asserts`, `unbalanced-brackets` (an adapter file with a bad `lexer.ident_chars`, no assert shape, a one-character bracket pair) | malformed table | a clean load error naming the field: never a crash, never a load. A built-in has no table: skipped |

- **Fixtures.** A dir of `<case><ext>.r0` files (the `.r0` suffix keeps them out of the repo's own checks): `seed<ext>.r0` and one head file per fixture case (`skip`, `expected-value`, `weaken-assert`, `suppression`, `helper-asserts` and the three `source-` cases), each the seed with one change. A seed or fixture the adapter cannot parse (the `source-` cases aside), or an adapter that crashes on one, fails that case and names the file and the error: a fixture dir from a PR never crashes R0. Any other error in `r0` exits 2 with no result. The seed's first line is a line comment (its first word is the opener `comment-out` uses); each test in it is a run of non-blank lines, and one test has two asserts, each on a line of its own. The built-ins' fixtures ship with ekit (`scripts/mech_review/r0_fixtures/<stack>/`); an adapter file's sit beside it (`.ekit/adapters/mini.toml` → `.ekit/adapters/mini.r0/`), or `--fixtures DIR`. `tests/fixtures/adapters/mini.r0/` is an example.
- **Unproven.** A cheat or control with no fixture reads `unproven`: R0's status is `unproven`, the summary says `unproven: R0`, and it never reads `all pass`. Not a fail: exit 0.
- **A failed case** is one `fail` entry (check `R0`, class `adapter-fix`, not `agent-fixable`) naming every failed case, e.g. ``R0 static half failed for the `mini` adapter: cheat `skip` gave no R2 fail: … entry``; its file is the adapter file, else the fixture dir (`ekit:scripts/mech_review/r0_fixtures/<stack>` for a built-in). The checks that read tests through the adapter (`R1`, `R2`, `R4`), each one that ran, are then `n/a` with the note `blocked: R0 failed (<cause>)` (their own result under `before`), in `all` and in the merged result alike. Their entries are kept, marked `blocked: R0` (the comment's severity cell reads e.g. `fail (R2 blocked by R0)`), and still count: a protected-path or other `needs-human` entry never hides behind a failed proof. The fix is a repair of the adapter in a PR of its own (ci-doctor's repair mode), never by the PR under review. A person may [waive](#waivers) the R0 entry (`/mech-waive R0-…`) to land an urgent PR while the repair is pending; each `fail` entry of a blocked check still needs its own waiver, so waiving R0 alone never turns the run `pass`.
- **The PR's version.** `r0` proves the adapter file it is given as checked out, so in CI the PR's version; R1-R4 read the adapter and the plan from the base branch. A [parser-backed](#parser) file is the exception: R0 never runs a parser command the PR wrote or changed (its `[parser]` must equal the base branch's, else `unproven` and one `needs-human` entry), so the guard job runs no code from the PR. The workflow does not pass `--adapter` yet: the guard proves the built-in stack only, until #17 wires a repo's adapter files into the workflow.
- **Editing rules.** Editing an adapter file or the stack plan needs no person: R0 judges the adapter and the drift check the plan. Only these do, as one `fail` entry of class `needs-human` (check `R0`) naming each, e.g. ``a person decides: `ignore` gains `src` in .ekit/stack-plan.toml; `limits.max-mutants` 40 -> 20 for the stack in folder `m` (.ekit/adapters/mini.toml)``:
  - a looser limit: an adapter file's [`[limits]`](#keys) `max-mutants`, `mutation-budget` or `census` lower, `assert-density` higher; or a caller workflow's `max-mutants` or `mutation-budget` input lower, per caller job. Only workflow files under `.github/workflows/` that differ between base and head and mention `mech-review.yml` (any `uses:` form) are read, so an unchanged one never gives an entry; each caller job's block-style `with:` is read line by line (keys bare or quoted). It fails closed: when a changed file holds what the reader cannot read with certainty (flow style, an anchor, alias or merge key, a block scalar, a changed value that is not a whole number such as an expression), or its files or caller jobs do not pair up one-to-one (a rename, an added or removed caller job) while a limit is set, the entry says `workflow limits changed and could not be compared: <file>` and a person compares them. A missing limit reads its default (40, 10, 100, 10);
  - a folder added to the plan's `ignore` list;
  - a changed target OS: a plan entry's `target-os`, or its adapter file's;
  - a test accepted with no recognised assert (#21): a name added to `.ekit/r0-accepted.json` ([assert density](#runtime-half)), or a list there that no longer reads;
  - a changed mutation tool (#19): an adapter file's [`[mutation.tool]`](#r3-side-mutation-tool) added, removed or with any value changed (`[mutation.tool] of the stack in folder `lib` changed (build/m.toml)`).

  Stacks are matched by folder (normalised as the plan reads it: `./svc`, `svc/` and `svc` are one), and each side's adapter is read through that side's plan: pointing a stack at a new adapter file, or renaming the stack, is still compared (a file missing on one side reads the defaults). A head stack in a folder the base has no stack for compares with the defaults (linux and the default limits). A side with no plan reads its adapter files at the other side's plan paths, so deleting the plan never hides an adapter edit. An adapter file that does not load at head is named too. A tighter limit, a removed `ignore` folder, and a removed stack give none. The entry fails `R0` but blocks nothing. On python < 3.11 (no TOML reader) a changed plan or adapter file is the entry: it cannot be read, so it never passes silently.
- **Co-change rules** (#85). The static half also runs each [co-change rule](#co-change-rules)'s two proof cases, at the head: a rule that lacks one, or whose case reads wrong, is one `fail` entry of class `agent-fixable` that blocks nothing; a rule file at the head that does not read leaves R0 `unproven`. In `all`, R2's status counts R2's own entries only, so an R0 entry never turns R2 red.
- **Test paths.** `.ekit/scenarios/**` is a test path for every stack, added by the core beside `test-paths`.
- Exit: 0 pass or unproven, 1 a fail entry, 2 usage (an adapter file that does not load, a fixture dir with mixed extensions) or git error.

### Runtime half

```
python3 -I scripts/mech-review.py red --repo . --base main --head HEAD --stack python --test-paths 'tests/**' --r0 ~/.cache/ekit-r0
python3 -I scripts/mech-review.py mutants --repo . --base main --head HEAD --stack python --r0 ~/.cache/ekit-r0
python3 -I scripts/mech-review.py r0 --repo . --base main --head HEAD --stack python --fingerprint run
```

`red`, `all` and `mutants` take `--r0 DIR`; without it they report no R0, as before. The half has two parts, each proved where its tool is installed:

| Part | Where | Cases |
|---|---|---|
| `run` | `red` (the red-first job), `all` | `census-repo`: every test the runner lists at head (the adapter's listing) is found by the scanner, `found/listed` with the misses named; at least `[limits] census` percent (default 100). `census-fixtures`: the same on the fixture project. Assert density (below). `control-pass`, `control-fail`, `control-skipped`, `control-build`, `control-no-such-test`: each fixture test, run by name as R1 and R4 run one, reads `pass`, `fail`, `none`, `build` and `none`. `skip-idiom`: the skipped control carries the adapter's skip marker |
| `r3` | `mutants`, shard 0 (or no `--shard`) | `r3-weak`: R3 on the weak-assert fixture PR gives a MISSED mutant; `r3-strong`: the strong one gives none |

- **The listing.** The built-ins list with `cargo test -- --list`, `pytest --collect-only -q -o addopts=` (the project's `addopts` cleared, so an `addopts = "-q"` cannot turn it into the per-file form; a parametrized test once) and `vitest list` (it.each's `%s` matches any value; skipped tests are not listed, which the census allows: only listed tests must be found). rust lists no file: each scanner test matches one listed test, by the name libtest gives it (its module path from its file: `src/foo.rs`'s `tests::x` is `foo::tests::x`; `src/lib.rs`, `src/main.rs`, `tests/*.rs` add none), exact matches first, then by suffix. A runner with no listing reads the census `n/a` with the reason, never a fail: jest (`--listTests` lists files), a unittest command, an adapter file without [`[run.list]`](#run-side-r1-and-r4). A listing that exits non-zero fails the census. An empty listing while the scanner finds tests is a fail naming that (`the runner listed no test, the adapter finds 4`), never a `0/0` pass, for every census.
- **Assert density.** The repo's tests at head (not skipped ones) with no recognised assert, their own or one in a helper they call by name, are listed (`checks.R0.density`: `tests`, `no_assert`, `accepted`, `limit`, `percent`). It is measured on every run, a cache hit or not (the scanner only). Above `[limits] assert-density` percent (default 10) of the tests, R0 fails with one `needs-human` entry naming them, which blocks no other check: the cause is either an assert the adapter does not know (an adapter-fix PR, ci-doctor's repair mode) or tests meant to have none. **A person accepts the list** by adding each name (`path::test`, as the entry names it) to `.ekit/r0-accepted.json`, `{"assert-density": {"<stack>": ["tests/test_smoke.py::test_starts"]}}`, in a PR of its own: that PR is a `needs-human` entry of R0's editing rules (`` `assert-density.python` accepts `tests/test_smoke.py::test_starts` ``), so a person approves it, and the list counts once it is on the base branch (the list is read at the base; a name the PR itself adds counts for nothing). Accepted names do not count towards the limit. Removing a name needs no one. A list that does not read accepts nothing, and a PR that leaves it so is named.
- **Fixtures.** `runtime/` in the fixture dir (the built-ins': `scripts/mech_review/r0_fixtures/<stack>/runtime/`; an adapter file's: `<adapter>.r0/runtime/`, read at the base for the repo's own adapter file): `controls.json` (`{"pass": {"file": "tests/ctl.py", "name": "test_passes"}, "fail": …, "skipped": …, "build": …, "no-such-test": …}`, the names as the adapter names tests), `project/` (a runnable project, every file `<name>.r0`, written without the suffix into a throwaway git repo), `build/` (laid over the project for the build control only), `r3/base/` (a project whose suite passes) and `r3/weak/`, `r3/strong/` (each laid over `r3/base/` as one PR: a production file and its test). The project's tests sit under `tests/`, or where `controls.json`'s `"test-paths"` (a list of globs, #22: `["src/test/**"]` for Maven) says; anything else there is a fixture error. A fixture dir may hold a variant per runner, `runtime-<runner>/`, used when the reviewed checkout picks that runner (the ts built-in ships `runtime-jest/` beside the vitest `runtime/`; checked against real jest 29.7.0 and vitest 2.1.9 and 3.2.7). The reviewed project's installs reach the fixture repos as they reach a worktree (`worktree_setup`: ts links `node_modules`). `tests/fixtures/adapters/minirun.r0/` is an example.
- **The fingerprint.** A part's runner-dependent cases run only when `DIR` holds no pass for its fingerprint: a hash of the part, the stack's name and project dir (two stacks of one repo never share a key), the adapter (an adapter file's bytes, a built-in's name), the fixture dir, the ekit version (the plugin version and the engine's own source), the stack's target OS, the commands the part runs, the accepted list (`run`), and the version lines of the toolchain programs the adapter names. **What a hit skips:** for `run`, the repo census, the fixture census and the runner controls (assert density still runs, and so does the census of the PR's changed test files: one listing at head, `census-pr`, at `[limits] census`; a miss is the `adapter-fix` entry; rust's listing names no file, so there the whole listing is counted and the note says so); for `r3`, the R3 control. The hit is read before any PR code runs (before R1, R4 or R3, and before the part's own census and controls), and the dir is emptied at once; when the run ends, the engine rewrites the dir with only the verdicts that run decided (the hit it read, or the pass it proved, written only when every runner-dependent case passed: a density fail does not stop it, since density is re-measured on every run), so a file planted during the run does not outlive it. This is not a sandbox: `red-first` and `mutants` run PR code, which can forge that job's results anyway. The cache is per PR (below), so a forged pass reaches only that PR's own later runs, and a PR process left running after the engine exits could still write the dir before the cache is saved: that residue is the limit. Nor does it stop code that runs at interpreter start: a `.pth` file in the venv's site-packages (which an install of the PR's requirements can add) runs under `python3 -I` too, so the engine's own process is not out of the PR's reach in these jobs (`-I -S` on the workflow's engine calls would close that: an owner's call). `r0 --fingerprint run|r3` prints `{part, fingerprint, key, probes}` (`key`: the workflow's cache key) with the same inputs as `red` and `mutants` (it also takes `--test-cmd` and `--mutants-cmd`).
- **Version probes.** Probing runs programs, so it keeps #19's program rules: a program on `PATH`'s absolute entries or an absolute path, never one in the reviewed checkout, and for an adapter file's programs never an interpreter, shell or launcher. What is probed: for an adapter file, `<program> --version` for the first word of the test command the checkout picks (a `[[run.runner]]` command when its `when` holds, else `commands.test`, or `--test-cmd`) and of `[run.list].command`; for `r3`, `[mutation.tool].command` (or `--mutants-cmd`) with its `version` args; the built-ins name fixed argv (rust: `cargo --version`, `rustc --version`, `cargo mutants --version`, whose `cargo-mutants` binary keeps the same rules; python: `python3 --version`, `python3 -m pytest --version`, `python3 -m pip show mutmut`; ts: `node --version`). Each runs in an empty temp dir with a minimal environment; the line kept is the first that starts with `version`, else the first. A program the rules refuse is named in the part's `probes` (`node_modules/.bin/vitest --version: not probed (a path in the project dir, which the PR under review can change)`), never run: so a ts toolchain bump inside `node_modules` does not change the fingerprint (the node version does), and a probe run in the empty dir does not read the project's `rust-toolchain.toml`.
- **The R3 control's tool.** It runs in a throwaway repo, but its program keeps R3's rules against the reviewed checkout too: a tool that resolves on PATH into it is refused there as R3 refuses it.
- **Target OS.** A part runs only on the stack's target OS (the plan entry's `target-os`, else the adapter's): elsewhere it is `n/a`, named.
- **Results.** The part's check is `checks.R0` in `red`'s and `mutants`' result (`half: runtime`, `part`, `ran`, `fingerprint`, `probes`, `cases`, `census`, `density`), with a note of numbers, e.g. `runtime half (run): fingerprint 1a2b3c4d5e6f (ran); census: 12/12 listed tests found; fixtures census: 6/6; assert density: 1 of 12 tests with no recognised assert, 8% (limit 10%); controls: 5 of 5 read right`. A failed case is one `fail` entry of class `adapter-fix` naming each cause (``census `census-fixtures`: 2/3 found; missed: `tests/ctl.mini :: also passes` ``, ``control `pass` read error: 1 passed (want pass)``, ``skip idiom: `skipped` runs as skipped (none), but the adapter sees no skip marker on it``, ``R3 control `r3-weak` gave R3 n/a, 0 MISSED: … (want a MISSED mutant)``); the checks the part proves are then `n/a` (blocked): `run` blocks R1, R2 and R4, `r3` blocks R3. A missing toolchain is `n/a`, a case with no fixture `unproven`: neither is remembered. The report job's merge combines the guard's static half and both parts into one R0 (the worst status; each part kept under `checks.R0.parts`).
- **In the workflow.** `red-first` and `mutants` (shard 0) each compute the part's fingerprint (`r0 --fingerprint`, its stack and project dir from the same expressions as the run step's: the workflow test checks it), remove `~/.cache/ekit-r0`, restore it from `actions/cache` under `ekit-r0-<part>-<fingerprint>`, and pass it as `--r0`; the cache action saves the dir at the end of the job only when the key had no hit and the dir exists. A cache miss only means the part runs again. Cache scope (accepted for now): GitHub scopes a cache written by a `pull_request` run to that PR, and mech-review runs on `pull_request` only, so a cache hit needs the same PR re-running at the same fingerprint, and each new PR runs the runtime half once. Warming the cache from the default branch (a cache there reaches every PR) would need a push-triggered run of the proof: a follow-up.

## Co-change rules

A co-change rule says "when these paths change, at least one of those must change too" (a behaviour change updates the changelog; a new module goes in a list). A linter reads code, not diffs, so it cannot see such a rule; R2 can. The `mistake-to-check` skill (#87) is how a rule usually starts: it turns an agent mistake that passes its filter into a rule with its two cases, and says when to promote or remove one. The rules live in `.ekit/co-change.toml`, read from the **base** branch (as the repo's adapter file is): a PR is judged by the rules it starts from, never by rules it writes, and a rule a PR adds judges the PRs after it.

```toml
format = 1

[[rule]]
id = "behaviour-docs"
trigger = ["scripts/mech_review/**"]
require = ["CHANGELOG.md", "docs/mech-review-ci.md"]
reason = "a behaviour change updates the changelog's Unreleased section and the CI doc"
incident = "#76"
flagged = ["scripts/mech_review/r2.py"]                   # a PR the rule must flag
control = ["scripts/mech_review/r2.py", "CHANGELOG.md"]   # a PR it must leave alone
# severity = "confirm"   # the default; "fail" once promoted
```

Keys (top level: `format`, required, `1`; `rule`, an array of tables, may be empty or absent). Per `[[rule]]`:

- `id` (required): the rule's name, letters, digits, `_`, `-` or `.`, unique in the file.
- `trigger` (required): globs, at least one; a change to a matching path triggers the rule.
- `require` (required): globs, at least one; the rule holds when any changed path matches one.
- `reason` (required): why the rule exists; the entry quotes it.
- `incident` (required): the commit or PR of the mistake the rule came from: a commit's sha (7 to 40 hex digits), or `#N` for a PR.
- `severity`: `confirm` (default: listed, never blocking) or `fail` (a promoted rule: the check fails).
- `flagged`, `control` (#85): the rule's two proof cases, each the paths one PR changes (at least one; repo paths, `/`-separated): `flagged` is a PR the rule must flag, `control` one it must leave alone. Neither is required by the format: [R0](#r0-adapter-proof) fails a rule that lacks one, and R2 fails a new rule that lacks one (below).

Globs are repo-root paths (`**` any depth, `*` one segment, `?` one character), as for `protected-paths`. A changed path is either side of a change over `merge-base..head`: a renamed file counts under its old and its new path, a deleted one under its old.

Each broken rule (a changed path matches `trigger`, none matches `require`) is one R2 entry: class `agent-fixable`, the rule's severity, file `.ekit/co-change.toml`, line 0, problem ``co-change rule `behaviour-docs`: `scripts/mech_review/r2.py` and 2 more changed, and none of `CHANGELOG.md`, `docs/mech-review-ci.md` did: <reason>``; the hint names the required paths and the incident. The id comes from the rule id, so it stays the same across heads whichever trigger paths changed (a waiver keeps applying). A `confirm` rule never makes the summary `fail`.

- A repo without the file runs exactly as before; the file is read only when it exists, so `tomllib` is needed only then.
- A file that is unreadable, not TOML or invalid is a usage error (exit 2, nothing on stdout) that names the field, as for an adapter file: ``co-change rule file .ekit/co-change.toml at 1a2b3c4d5e6f: rule[1].trigger[0]: want a glob, a non-empty string``. An unknown key, a missing required key, a glob that is not text, an empty list and a duplicate `id` are each such an error. Reading it needs python 3.11 or newer (`tomllib`); on an older python a repo with the file gets that usage error, named.
- `r2` and `all` run the rules (the `guard` job).
- ekit's own rule file (#86) is [`.ekit/co-change.toml`](../.ekit/co-change.toml): three rules at `confirm`, one per doc a change under `scripts/` updates: `behaviour-changelog` (`CHANGELOG.md`), `behaviour-status-line` (`docs/testing-standard.md`) and `behaviour-ci-doc` (`docs/mech-review-ci.md`). `require` is any-of, so a rule per doc is how all three are required: a PR that updates two of them gets the third's entry.

**Proof cases** (#85). [R0's static half](#r0-adapter-proof) runs both cases of every rule in the file at the **head** (the PR's version, as R0 proves the PR's adapter file), each as one PR in a throwaway repo: the case's paths seeded on base, changed on head, built in git's index (never as files). `flagged` must give the rule's entry, `control` none. A rule that lacks a case, or whose case reads wrong, is one R0 `fail` entry of class `agent-fixable` naming the rule and each cause: ``co-change rule `x` fails its proof: no `control` case``, ``… `flagged` case (`README.md`) gave no entry (want the rule's entry)``, ``… `control` case (`src/a.py`) gave the rule's entry (want none)``, or a case git does not build as given (a `..` segment, a path that is a folder of another). It blocks no check: a rule's proof is not the adapter's. R0's note adds `co-change rules: 2 of 3 proved; failed: x`, and `checks.R0["co-change"]` lists each case. A head file that does not read leaves the rules `unproven` (R0's note names the error; R2's guard is the entry). No file, or no rule, adds nothing to R0.

**Guards** (#85). When the range (`merge-base..head`) changes `.ekit/co-change.toml`, R2 checks the change. Each is one entry on the rule file:

| The change | Entry |
|---|---|
| The file at the head does not read (any load error above, also on python < 3.11) | `fail`, `agent-fixable`: ``the co-change rule file this range writes does not read: <the error>``; not a usage error, since the PR wrote it |
| A new rule (an `id` the merge base's file has not) whose `incident` resolves to no commit or PR | `fail`, `agent-fixable`. A sha resolves when it names a commit the head reaches; `#N` when the message of a commit the head reaches names `#N` (a merge or squash commit names its PR). Git only, no network: anything else resolves to nothing |
| A new rule without both cases | `fail`, `agent-fixable`: ``new co-change rule `x` has no `control` case`` |
| A rule that fires in the range (the base's rule, as R2 applies it) and that the range weakens or removes, against the merge base's version | `fail`, `needs-human`: ``co-change rule `x` fires in this range, and this range weakens it (severity fail -> confirm; trigger loses `lib/**`; require gains `docs/**`)`` or ``… removes it``. Weaker is a lower severity, a `trigger` glob gone or a `require` glob added, compared as text whatever the globs match; a renamed `id` or a deleted file removes the rule. The weakening goes in a PR of its own, where the rule does not fire |

Adding a rule with its cases and an incident that resolves, promoting one to `fail`, adding a trigger glob, removing a require glob, and editing `reason`, `incident` or the cases of an existing rule give no entry; so do a weakening and a removal in a range where the rule does not fire. A rule the base adds after the merge base is not one the PR removed. A file at the merge base that does not read is a usage error, as at the base.

## Limits

- Fork and Dependabot PRs get a read-only `GITHUB_TOKEN`: the comment cannot be posted (GitHub answers 403). `report` then prints a warning, leaves the result in the job summary, and passes or fails on the result alone. Waiver comments are still read.
- Permissions are `contents: read` and `pull-requests: write` only. The workflow uses `pull_request`, not `pull_request_target`, so forks get no secrets.
- `guard` decides from git diffs only. `red-first` compiles and runs the PR's tests (the code under review) with a job-level `contents: read` token and no other secrets.
- R1 needs the branch name: the workflow passes `github.head_ref`. A run without it skips R1 and says so.
- `baseline` (rust) and `mutants` run cargo-mutants, which builds and runs the PR's tests (once for the baseline, once per mutant), with a job-level `contents: read` token and no other secrets. The unmutated baseline runs once, in `baseline` (same token), not once per shard.
- rust R3 builds: the baseline and shard steps export `CARGO_INCREMENTAL=1` (the toolchain action exports 0) and `CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0`. Build time only: the same tests run on the same mutants. Measured on a real TUI crate (one shard of 5 mutants, 4 cores, the shard argv): 654 s wall and 347 s of mutant builds before, 416 s and 148 s after, same verdicts (4 caught, 1 unviable).
- cargo-mutants is pinned to 27.1.0 through `taiki-e/install-action` (pinned to a full SHA). If the install fails the step continues and R3 reports `n/a (env)`: a missing tool is never a pass and never a code failure.
- ts: Stryker 10.0.0 is pinned in the workflow. The vitest and jest plugins, and the install scripts of the repo's dependencies, run PR code with a read-only token, as the tests do. Yarn berry (PnP, no `node_modules`) and `node --test` are not supported: the runner is `node_modules/.bin/vitest` or `jest`.
- python: `mutmut` 3.8.1 is pinned in the venv. A repo that already has `[tool.mutmut]` in its `pyproject.toml` gets R3 `n/a (env)`: the runner needs `only_mutate` to limit the run to the changed files, and does not override the repo's table.
- python: only the project dir's own top-level entries reach mutmut's copy. With `project-dir` in a subfolder, a test (or the code under test) that reads a file above it (`../docs`) fails there, and R3 reports `baseline tests fail at head`. `doctor` names the missing paths.
- python: a top-level entry holding a symlink mutmut cannot copy (dangling, to a dir, or leaving the project dir) is left out of mutmut's copy as a whole. A test that reads another file in that entry (`docs/usage.md` beside a dangling `docs/html -> ../_build/html`) fails there, and R3 reports `baseline tests fail at head`. `doctor` names the link: track its target or remove the link.
- The shard count is at most 4, at most the mutants under `max-mutants` and the estimated cost (rust), or the changed file count (python, ts), set by the `baseline` job; a rust shard never runs empty. The per-mutant timeout is derived from the baseline unless `mutant-timeout` is set (see Inputs). The wall time of R3 is the baseline (once) plus about the budget per shard, not the budget times the shards.
- R3 runs cargo-mutants in a worktree at the head, in the crate dir (`project-dir`), on `base...head` changes only (`--in-diff`; the diff is made relative to the crate dir, and result paths are mapped back to the repo root). A checkout that does not match head is not mutated.
- R1 checks out the merge base as a git worktree and puts the PR's test-path files on top; the caller's checkout is not moved. A new or changed test in a file outside `test-paths` (a rust `#[cfg(test)]` mod beside the code) is not on the base's code, so R1 does not run it there: its note counts it (`N in files outside test-paths: not run there`), R4 still runs it at head, and R1 needs at least one red test in a `test-paths` file.

## Trust limits

- R1 and R4 results come from `red-first`, the job that compiles and runs PR code. A malicious test can forge that job's JSON. `red-first` has a read-only token (`contents: read`) and cannot edit the comment, but its result is only as trustworthy as the code it ran. R2 runs in `guard`, a separate job with no PR code, and is the hard guard. For a [parser-backed](#parser) adapter file `guard` also runs, before R2, the install and build code of the parser package the base branch's adapter file declares, and of its dependencies, which are not pinned, with `GITHUB_ENV` and `GITHUB_PATH` writable for the steps after it: code the repo's owner trusts (ADR 0001), not the PR's, and not sandboxed ([what ekit does not do](#parser)).
- Non-`.rs` files outside `test-paths` (for example `Cargo.toml`) come from the base in R1's checkout: a test that needs a new dev-dependency is compile-red there (red).
- R3 results come from `mutants`, which runs the PR's tests. A malicious test can forge that job's JSON, as with R1 and R4; the read-only token stops it editing the comment, not forging its own result. R2 is still the hard guard for weakened tests.
- R3 measures test strength on the changed production code only. A MISSED mutant can be an equivalent mutant (no observable change): the fix is then to assert the behaviour the code really has, and a person may decide the mutant is not worth a test: that is a [waiver](#waivers). Without one a MISSED mutant stays `fail` until a test kills it or the code changes.
- `partial` (budget hit or `max-mutants` reached, nothing MISSED so far) does not block, so part of the diff was not mutated. The reviewer reads the `tested/total` note; a bigger `mutation-budget` or `max-mutants` (or fewer changed lines) is the fix. A budget hit with a MISSED found is `fail`.
- Shard results are merged by `mech-review.py merge`. A missing or stale shard is a CI `fail` entry that names the shard; the other shards' entries are kept. Each `mutants` result carries `shard: {k, n, max_mutants}`; a shard given twice, a shard index missing for `--shards`, or shards that disagree on head, base or cap give one CI `fail` entry (`mutants shards do not match: …`, #42). A result without `shard` (an older engine) is checked on head and base only, unless another result carries it; a malformed field is named. `--envelope K` given twice is a usage error. The CI entries reach the sticky comment and fail the check.

With `stack: auto` the stack and project dir come from the PR's tree, so the `stack` job reads them at the base too and stops when the head finds something else: a PR cannot switch the stack its own checks run with. The job runs no PR code, and its outputs (`stack`, `project-dir`, `error`) reach later jobs only through `env` and `if:` conditions, never a `run:` script. A dir name with a control character is an error, not an output.

The `baseline` job runs PR code too (rust), and its outputs decide whether the shards run, so a malicious test can forge them and skip R3. The outputs reach later jobs only through `env` and the matrix, never a `run:` script. R2 stays the hard guard.
