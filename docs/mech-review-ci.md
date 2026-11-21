# mech-review CI (adopters)

Reusable workflow: `EricleungDK/ekit/.github/workflows/mech-review.yml`. On each PR it runs up to seven jobs and merges them into one sticky comment (marker `<!-- mech-review -->`) and one check result:

- `stack`: settles `stack` and `project-dir` once (`scripts/mech-review.py resolve`), git only. With `stack: auto` (the default) it finds the one project from the tracked manifests; a set stack is passed through as is. Every later job reads the result from this job's outputs.
- `guard`: R2 test-diff guard (`scripts/mech-review.py r2`), git diffs only, no toolchain.
- `red-first`: R1 red-first and R4 determinism (`scripts/mech-review.py red`). Compiles and runs the PR's new or changed tests, so it needs the stack toolchain (rust: stable; python: a venv with pytest; ts: node 22 and the repo's installed dependencies).
- `plan`: decides whether R3 runs (a production file changed). Git only.
- `baseline`: the R3 baseline, once per PR (`scripts/mech-review.py baseline`). Rust: runs cargo-mutants 27.1.0's unmutated baseline (the tests once) and lists the mutants; sets the shard count (`min(4, mutants, ceil(estimated minutes / (budget / 2)))`, see [R3 cap, risk order and shards](#r3-cap-risk-order-and-shards)) and the per-mutant timeout the shards use. Python and ts: the shard count from the changed production files, at most 4 (git only). A baseline that fails or times out is R3's result: the shards do not run. Skipped when `plan` says no production file changed.
- `mutants`: R3 mutation on the diff (`scripts/mech-review.py mutants`), one job per shard. Runs cargo-mutants 27.1.0 (`--in-diff`, round-robin shards, baseline skipped) on the PR's code (rust), mutmut 3.8.1 on the functions the diff touches in the changed files (python), or Stryker 10.0.0 on the changed lines (ts). Skipped when `baseline` says no shard runs.
- `report`: merges the results (the baseline's R3, or the shards' R3), edits the comment, sets the check.

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
| `stack` | `auto` | language adapter: `auto`, `rust` (cargo test, cargo-mutants), `python` (pytest, mutmut) or `ts` (vitest or jest, Stryker). Sets up the toolchain for `red-first` and `mutants`. `auto` finds the one project from the tracked manifests (`Cargo.toml`; `pyproject.toml`, `setup.py` or `setup.cfg`; `package.json`; the shallowest ones, `tests/`, fixture, vendored and build dirs skipped, as `doctor` does), at the PR base and at its head, git only. Several projects, none, or a head that finds a different one than the base: no check runs, and the comment names the projects found and asks for `stack` and `project-dir`. It never guesses. With `project-dir` set, only that dir is read |
| `test-paths` | `tests/**` | test file globs, one per line; `.rs` files here count every assert; a `.rs` file outside them is production code for R1. A repo with `.ekit/scenarios/` adds `.ekit/scenarios/**` (ci-doctor writes it; `doctor` gives an `env` entry when a file of the stack there is not covered) |
| `protected-paths` | `.github/**` | globs, one per line; any change under them is a `needs-human` fail |
| `agent-branch-prefix` | `agent/`, `claude/`, `codex/`, `copilot/`, `cursor/` | prefixes, one per line: R1 runs only when the PR head branch starts with one of them (`--agent-prefix`, repeatable); other branches skip R1. `*` runs R1 on every branch. A value you set replaces the default list |
| `mutation-budget` | `10` | R3 budget in minutes, per mutants shard and for the baseline step. A budget hit is `partial` (no MISSED so far) or `fail` (a MISSED found), never a crash; a baseline that does not finish in it is `n/a`. Applies to all stacks |
| `max-mutants` | `40` | R3 cap: the most mutants tested per PR, riskiest first (see [R3 cap, risk order and shards](#r3-cap-risk-order-and-shards)). The rest are untested: R3 reads `partial (tested/total)`, never `pass`. rust and python; ts does not apply it |
| `extra-apt-packages` | `` | apt packages (space-separated) installed in `red-first`, `mutants` and (rust) `baseline`, before the tests run |
| `project-dir` | `.` | crate dir under the repo root (`package.json` for ts). With `stack: auto` and `project-dir` left at `.`, the dir found is used; a dir you set is never replaced (`.` set by hand reads as left at the default). R1, R4 and R3 run there; `test-paths` and `protected-paths` stay repo-root globs; a path with `..` or a leading `/` is a usage error |
| `setup-command` | `` | shell command (run with bash) in `red-first`, `mutants` and (rust) `baseline`, after `extra-apt-packages`, before the tests. A non-zero exit stops that job, which then reports a CI entry |
| `mutant-timeout` | `` (derived) | R3 per-mutant timeout in seconds. Empty is the timeout derived from the measured baseline: 5× its test time, at least 20 s (cargo-mutants' own rule; `timeout_multiplier` and `minimum_test_timeout` are read from the crate dir's `.cargo/mutants.toml`, not a workspace root above it). A set value is used as is. Neither caps the baseline: it runs once, in the `baseline` job, bounded by `mutation-budget`. Stryker's `timeoutMS` is 120 s when unset |
| `rust-toolchain` | `stable` | Rust toolchain for `red-first` and `mutants` (rust stack), passed to the toolchain action, e.g. `1.96.0` to pin a repo |

Globs: `**` any depth, `*` one segment.

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

- Jobs: `guard` (artifact `mech-review-json`), `red-first` (artifact `mech-review-red-json`), `plan`, `baseline` (artifact `mech-review-baseline-json`), `mutants` (artifacts `mech-review-mutants-<shard>`), `report` (`needs` all five, runs even if one fails).
- `report` merges the results: each job owns its checks (R2 from `guard`; R1 and R4 from `red-first`; R3 from `mutants`). The shard results are combined by `mech-review.py merge` first. It edits the sticky comment, or creates it: a summary line, a table of entries (id, severity, file:line, problem, forbidden) and the full JSON.
- A job with no usable result (crash, no JSON, or a result for an older head) fails its own checks and adds one `CI` entry naming the job. The other job's entries still show.
- Check fails on any `fail` entry, or any check whose status is `fail` (`confirm` and `waived` entries do not fail). A job's `CI` entries (a missing or mismatched mutants shard, no baseline result) are kept in the merged result and listed in the comment.
- A `fail` entry of class `needs-human` reads `needs-human` in the comment (severity cell, and the headline when every fail entry is needs-human). The JSON keeps `severity: fail` and the summary keeps `fail`; the check stays red.
- R1 on a non-agent branch, or a PR with no production file changed, is `skipped` and named as such. A missing toolchain is `n/a` (not run, not pass). Each `n/a` note names the cause and the input to set (`setup-command` for a toolchain, the install step for cargo-mutants, `project-dir` for no manifest: `Cargo.toml` for rust, `pyproject.toml`, `setup.py` or `setup.cfg` for python), and the comment adds one line under the headline: `Did not run: R3 (no Cargo.toml in .: set project-dir)`. A missing manifest where R1 or R4 runs is a `fail` (cannot run), with `set project-dir` in its hint.
- Summary: `all pass <sha>` only when every check ran and passed. A run with R3 skipped (no production file changed) reads like `pass <sha> (0 fail, 1 confirm; ran: R1 R2 R4; skipped: R3)`. A budget hit reads `partial: R3 (tested/total)`, and an absent tool reads `n/a: R3`; neither is `all pass`.
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
- mutmut credits a test with a mutant only when the test calls the function inside mutmut's own process, under the module name mutmut derives from the file path. A test that starts the program as a subprocess, or imports the file under another name, is not credited: its lines read `no tests`. So each mutant still MISSED on a changed line gets one more try. `mutmut apply` writes it into the worktree, the whole suite runs once (`python3 -B -m pytest -x -q -p no:cacheprovider --ignore=mutants`), and a failing suite has caught it; the file is put back each time. The note counts them (`N more caught only by the whole suite`): a visible nudge towards a test that calls the function, not a blocker. A suite that is red without any mutant is not used (the job log says so). One suite run on a mutant may take 5× the clean run (at least 30 s); one that takes longer is counted as hung, neither caught nor missed. The whole step shares `mutation-budget`. A mutant whose retry the budget does not reach, or cuts short, is untested, not MISSED: R3 reads `partial` and the note counts it (`N missed by mutmut, whole-suite retry not reached at budget: untested`). So is every mutant still waiting for its retry when the budget ends mutmut's own run. A flaky test in the suite can give a false catch here; R4 is the check for flaky tests.
- A mutant of a touched function that mutmut leaves unrun without a budget hit makes R3 `partial`, never `pass`. A method is located inside its class (mutmut names it `Class` + U+01C1 + `method`), so a method name that two classes share is found in the right one. A missed mutant whose name maps to no line in the file is `unlocated`: one `confirm` entry, not a fail and not a silent pass, counted in the note (`N unlocated`) for a reader to check by hand.
- `no tests` (no test reaches the line) is a MISSED mutant: the fix is a test that calls it. Survived mutants are MISSED. `timeout`, `suspicious` and similar are neither caught nor missed, as TIMEOUT and UNVIABLE are for cargo-mutants.
- Timing is wall time only (`checks.R3.timing.wall_s`): mutmut prints no per-phase durations, so the cargo-mutants phase fields are left out, not guessed. `--mutant-timeout` does not apply: mutmut's own timeout (its `timeout_multiplier` times the test time) decides.
- A budget hit reads the results mutmut kept: `partial (tested/total)`. A mutant mutmut reports missed before the budget ended its run has had no whole-suite retry, so it is untested too.

## R3 locally

`scripts/r3-local.py` runs the R3 jobs of this workflow on your machine, so a MISSED mutant shows before the review request, not after CI. POSIX only: on Windows run it in WSL (native Windows exits 2).

```bash
python3 -I scripts/r3-local.py --base origin/main --stack python --test-paths 'tests/**' --mutation-budget 20 --env-dir ~/.cache/ekit-r3env
```

- Setup: the stack's R3 tool with the workflow's pins (the adapter's `r3_tool`): python a venv with `pytest==9.2.0` and `mutmut==3.8.1`, then the project dir's `requirements*.txt`, installed from a checkout of head (`git archive`; pip runs in the project dir there, as CI does, so `-c`, `-r ../x.txt` and `-e .` resolve the same; a link in the tree that points out of the checkout is left out and named on stderr: CI keeps it and never follows it), the venv first on `PATH` (`PYTHONPATH` and `PYTEST_ADDOPTS` are dropped: CI has neither); ts `@stryker-mutator/core@10.0.0` and `jest-runner` in their own npm prefix, passed as `--mutants-cmd`; rust `cargo install cargo-mutants@27.1.0` and the workflow's cargo env. `--env-dir` keeps it and reuses it while the pins and the requirements files match; without it a temp dir is removed after the run. `setup-command` and `extra-apt-packages` are not run: install those yourself.
- Steps: `plan`, `baseline --shards 4`, every shard at the same time (`mutants --shard K/N`, the CI budget and `max-mutants` each, `--mutant-timeout` or else the baseline's), `merge`. Defaults are the workflow's (`test-paths` `tests/**`, budget 10, `max-mutants` 40); pass your caller's inputs: `--test-paths` (repeat), `--mutation-budget`, `--max-mutants`, `--mutant-timeout`, `--project-dir`. The shards share this machine's CPUs, where CI gives each its own runner: wall times differ, and so can a mutant that hits mutmut's own timeout.
- Output: the merged summary, R3's status (`tested/total`), each shard's note and wall time, the fail entries; the results are in `<env-dir>/out/` (without `--env-dir` they are removed, and the output says so). It tests the head commit: uncommitted changes are not in it.
- Exit 0 no fail, 1 a fail entry, 2 setup failed, usage or git error, a step gave no usable result, or native Windows.

## Reading a run

`scripts/mech-summary.py <run-id | PR number | #N | PR URL> [--repo OWNER/NAME]` downloads a run's artifacts (`gh run download`; a PR resolves to the run of its newest `mech-review report` check) and prints the summary line, each check's status and note, each shard's note, and the fail entries grouped by file, merged as the report job merges them. Waivers are not applied. `--dir DIR` reads artifacts already downloaded. Artifacts: `mech-review-json` (R2), `mech-review-red-json` (R1, R4), `mech-review-baseline-json`, `mech-review-mutants-K` (one per shard); a `mech-review-mutants-merged-json` (the merged R3) is used when the run has one. A run still in progress is a note (exit 2), not a result. The job list (`gh run view`) tells a baseline job that was skipped (the plan found no production change: R3 skipped) from one that ran and left no JSON (R3 fails, as in the comment).

The merged R3 artifact comes from this step in the `report` job, right after `merge mutants (R3, baseline and shards)` (#38; not yet in the workflow: an owner edit):

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

A partial R3 adds one `confirm` entry: class `agent-fixable`, id `R3-…` (stable across heads and counts), problem `R3 partial: <untested>/<total> mutants untested at budget` (or `total unknown` when the mutant list was never written). One entry per run, however many shards hit the budget. The check stays green and the exit code stays 0: partial never fails.

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
- Who: comments whose author is `OWNER`, `MEMBER` or `COLLABORATOR` of the repo, and not a bot. These are GitHub's author associations, not permission levels: `COLLABORATOR` includes an outside collaborator with read or triage access, and `MEMBER` any member of the owning org. The PR's own content (body, commits, files) can never waive: that is what the checks judge. The sticky comment itself (`<!-- mech-review -->`) is never read for waivers, whoever posts it.
- Edited comments do not waive. Anyone with write access can edit anyone's comment while the author shown stays the same, so a comment edited after posting (`updated_at` ≠ `created_at`) is ignored, and the sticky comment says so. To change a waiver, post a new comment. The stamps have one-second resolution: an edit within the same second as the post is not seen.
- When: the `report` job reads the PR's comments each time it runs. With the [waiver re-run caller](#waiver-re-run) set up, posting, editing or deleting a `/mech-waive` comment re-runs `report` on its own. Without it, re-run the run's failed job (`report`, the only one that fails on entries), or push: the next run picks the waiver up.
- Effect: the entry's `severity` becomes `waived` and it gains `waiver: {by, reason, url}`; a check whose fail entries are all waived reads `waived`; the summary counts it (`0 fail, 0 confirm, 1 waived`); the comment says who waived what and why. A waived entry does not fail the check. `all pass` is never printed over a waiver.
- Scope: a waiver is for one entry id. Ids are stable across pushes (rule + file + test name), so it holds while that same thing stays broken and falls away when the id does. To withdraw one, delete the comment and re-run.
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

- **Cap.** At most `max-mutants` (default 40) mutants are tested per PR. Past it, the riskiest are picked and the rest are untested: R3 reads `partial (tested/total)`, never `pass`, and the note says `N past the cap (max-mutants M): untested`.
- **Risk order.** Branch conditions first, then returns and boolean literals, then arithmetic, then the rest; string and argument mutants last. Ties: file, then position (rust) or function and mutant number (python), then name. So every run picks the same set, whatever order the tool lists them in.
  - rust, from `cargo mutants --list --json`: `MatchArmGuard`, and a binary or unary operator `==` `!=` `<` `>` `<=` `>=` `&&` `||` `!`, are branch conditions; `FnValue` (a replaced return value, `true`/`false` included) is a return; `+` `-` `*` `/` `%` `&` `|` `^` `<<` `>>` (and their `=` forms) are arithmetic; `MatchArm` and the rest come after.
  - python, from each mutant's edit in mutmut's own copies under `mutants/` (written by step 1, before any mutant runs): an edit inside a branch condition (from an `if`/`elif`/`while`/`assert` line to the end of its test, a match subject, pattern or guard, a comprehension's `if`, a conditional expression's test: found with `ast` on the function's copy, so a continuation line of a multi-line `if (...)` counts), on an `if`/`elif`/`while`/`assert`/`match`/`case` line, or of a comparison or `and`/`or`/`not`/`is`/`in`, is a branch condition; a string literal, or an argument dropped or set to `None` (`return f(a, b)` -> `return f(a)` included), comes last; `True`/`False`, or the whole returned value replaced by `None`, is a return; any other whole value replaced by `None` (an assignment's, `total = n * 2 + 1` -> `total = None`) is the rest, behind arithmetic, whatever operators the old value held; an arithmetic operator or a number is arithmetic; any other edit of a `return` line is a return. An edit those copies do not explain is ranked with the rest.
- **Where the cap applies.** Each shard lists the PR's mutants itself (rust: `--list --json --in-diff`; python: step 1 over every changed file, then only the mutants whose edit is on a line the PR changed, or that mutmut's copies cannot place, see [Python R3](#python-r3-mutmut)), sorts them by risk, caps the list and deals it round-robin over the shards. Shard `k` runs its own share: rust names each with an anchored `--re` (no `--shard`; `--in-diff` as before), python with `mutmut run <name> ...`. Shard 0 also reports the mutants past the cap as untested, so the merged `tested/total` counts each mutant once. A shard whose share is empty (fewer mutants than shards) reads `0 mutants in this shard`, `pass` with 0/0, and adds nothing to the merge. Within the cap: rust keeps cargo-mutants' own round-robin (`--shard k/n`), so its argv is as before; an unsharded python run keeps the touched functions' filters when every candidate is on a changed line, while a python shard still lists every changed file and names its share mutant by mutant.
- **A run that leaves the pick** (rust): cargo-mutants ORs `--re` with an `examine_re` in the crate's `.cargo/mutants.toml`, so such a config runs mutants past the cap. A capped shard whose run holds a mutant outside its pick is `n/a (env)` and names `examine_re`; it never reads `pass`. A capped note's `tested/total` is the check's.
- **A listing the budget cut** (python): a shard dealt from a step 1 the budget ended may hold a list the other shards do not, so its `total` is unknown (`tested/?`), never a dealt count.
- **Unreached is untested.** A mutant the budget never reached is untested (`partial`), with no MISSED entry. A mutant that really ran and survived is still MISSED. For python, a mutant mutmut reports missed is final only after its whole-suite retry, so one still waiting for that retry (or whose retry the budget cut short) is untested too.
- **Shard count** (`baseline` job) = `min(4, mutants, ceil(estimated minutes / (budget / 2)))`, at least 1: each shard aims at half its budget, so a small PR gets one shard, a large one at most 4, and none is empty.
  - rust: `mutants` is the listed count capped at `max-mutants`; the estimate is that count times the baseline's measured build plus test seconds (the clean build over-estimates an incremental mutant build).
  - python, ts: the `baseline` job installs no toolchain for them and measures nothing, so there is no estimate: the count stays one shard per changed production file, at most 4. A python shard whose share of the capped list is empty (fewer mutants than shards) reads `0 mutants in this shard` and still pays one listing run.
- **ts (Stryker) does not apply the cap or the order.** Stryker lists no mutant before its run and selects none by name (`--mutate` takes ranges), so its mutants are known only from its report, after they ran. A budget hit before its report is `partial` with no MISSED (tested unknown).

## What each stack mutates

The three tools do not make the same mutants, so R3 is not equally strict across stacks. This is a property of the tools, written down here so it is not a surprise:

| | cargo-mutants (rust) | Stryker (ts) | mutmut (python) |
|---|---|---|---|
| Operators, conditions, return values | yes | yes | yes |
| String literals | no | replaced by `""` only | wrapped (`"XXtextXX"`) and case-changed |
| Arguments removed or set to `None` | no | no | yes |
| Module-level code | n/a | yes | no (functions only) |
| A repo can switch a mutator off | config (an R2 `needs-human` change) | `excludedMutations` in the repo's Stryker config (same) | no: there is no such option |
| `max-mutants` cap and risk order | yes, from `--list --json` before the run | no: no mutant list before the run | yes, from mutmut's copies after its listing step |
| Shard count | cost-based, from the measured baseline | one per changed file (no baseline measured) | one per changed file (no baseline measured) |

In ekit's own code, most python string and argument mutants that survived were real gaps (a dictionary key, a git flag, an environment variable name), so they block like any other. The ones that are not gaps are equivalent mutants: see the R3 row of the [forbidden cheats](testing-standard.md#3-forbidden-cheats) for what to do with one.

## Adapter file

An adapter file is a TOML file that describes one stack to R2 as data: which files are this stack's, how tests are written and named, what an assert looks like, how a lint is silenced and with what reason, and what hides code from R3. ekit's own scanner reads the source with it (comments and strings masked, brackets matched, arguments split), so the file holds tables and words, never a regex over the file.

```
python3 -I scripts/mech-review.py r2 --repo . --base main --head HEAD --stack ts \
  --adapter scripts/mech_review/adapters/ts.toml --test-paths 'tests/**'
```

- `--adapter FILE` takes the stack from the file in place of the built-in of that name. `--stack` must equal the file's `name`; a name that is not built in is allowed only with `--adapter`. Without `--adapter`, `rust`, `python` and `ts` run as before.
- R2 only for now (`r2`): the run side of the file (test command, outcomes, mutation tool: R1, R3, R4) is not built yet, and `--adapter` with another subcommand is a usage error. The workflow does not pass `--adapter` yet.
- Reading the file needs python 3.11 or newer (`tomllib`); on an older python `--adapter` is a usage error that says so, and the built-in stacks keep working.
- A file that is unreadable, not TOML, or invalid is a usage error (exit 2, nothing on stdout) that names the field: `adapter file x.toml: tests.cases: want at least one entry`. An unknown key is an error too, so a misspelt key never passes silently.
- A source file whose masked text does not balance (a bracket never closed, an unterminated block comment or multiline string) is an R2 `fail` of class `needs-human`: the cause may be the file's lexer table, not the PR. The built-in stacks keep `agent-fixable`.
- Reference: [`scripts/mech_review/adapters/ts.toml`](../scripts/mech_review/adapters/ts.toml) describes TypeScript/JavaScript and gives the same R2 entries as the built-in `ts` adapter (`tests/mech-adapter.test.sh` runs the TS suites through it).

### Keys

Top level (required unless marked):

| Key | Value |
|---|---|
| `format` | `1` |
| `name` | the stack name (`--stack`): letters, digits, `_`, `-` |
| `extensions` | file extensions of this stack, e.g. `[".ts", ".js"]`. A file of the stack is test code when it matches a `--test-paths` glob, production code otherwise |
| `manifests` | optional: files that mark a project dir of this stack, e.g. `["package.json"]` |

`[lexer]`: how source is masked.

| Key | Value |
|---|---|
| `block_style` | `braces` (blocks are bracketed). `indent` and `keywords` are reserved, not supported yet: an error |
| `brackets` | bracket pairs, e.g. `["()", "[]", "{}"]`. Each character may appear in one pair only. `()` is required (a call is `name(...)`), and so is `{}` (blocks, `block_style = "braces"`) |
| `ident_chars` | optional: characters that are part of a word beside letters, digits and `_` (ts: `"$"`) |
| `member` | optional, default `"."`: the member-access character. A word right after it (`a.it(`) is a member, not a call |
| `line_comments` | optional: openers of comments that run to the line end, e.g. `["//"]` |
| `block_comments` | optional: `[open, close]` pairs, e.g. `[["/*", "*/"]]`. Not nested; an unterminated one is a parse error |
| `[[lexer.strings]]` | optional, one table per string form: `quote` (the delimiter), `escape` (one character, optional), `multiline` (default `false`: the string ends at its closing quote or the line end, with no error), `interpolation` (`[open, close]`, multiline only: a closing quote inside does not end the string), `name` (for the error, e.g. `template literal`: an unterminated multiline string is a parse error) |
| `[lexer.regex]` | optional: a regex literal form. `delimiter` (one character), `after` (characters after which it starts a literal, not a division), `after_words` (words after which it does). Also at the start of the file |

`[tests]`: test cases are calls.

| Key | Value |
|---|---|
| `style` | `calls`: a test is a call `case("name", fn)`, grouped by calls `group("name", fn)` |
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

Only call-style tests can be described today (`style = "calls"`). Declared tests (JUnit `@Test void x()`, Go `func TestX(t *testing.T)`, C# `[Fact]`, rust `#[test] fn x()`) cannot be described yet. Not supported either: a test whose body is a trailing block after the call (`test("keeps") { ... }` in Kotest or Kotlin, Swift trailing closures). The body must be an argument inside the call's parentheses (`case("name", fn)`). With a trailing block, the test is named without its group, its asserts count as outside test fns, and a skip on a trailing-block group (`xcontext("Calc") { ... }`) gives no entry: that skip is not caught.

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

`[mutation]` (optional): what hides code from R3 (an R2 `needs-human` fail).

| Key | Value |
|---|---|
| `skip_comments` | comment bodies that start with these words (whitespace between words free): a mutation skip marker |
| `config_files` | file names (any dir) of the mutation tool's config |
| `config_name` | the tool config's name in the entry, required with `config_files` |

### Fixed, not configurable

`block_style = "braces"` fixes these, and an adapter file cannot change them. A language that differs here cannot be described yet. Even a brace language needs call-style tests, as above, so Java/JUnit, Go and C# test files cannot be described today. The fixed rules:

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

- R1 and R4 results come from `red-first`, the job that compiles and runs PR code. A malicious test can forge that job's JSON. `red-first` has a read-only token (`contents: read`) and cannot edit the comment, but its result is only as trustworthy as the code it ran. R2 runs in `guard`, a separate job with no PR code, and is the hard guard.
- Non-`.rs` files outside `test-paths` (for example `Cargo.toml`) come from the base in R1's checkout: a test that needs a new dev-dependency is compile-red there (red).
- R3 results come from `mutants`, which runs the PR's tests. A malicious test can forge that job's JSON, as with R1 and R4; the read-only token stops it editing the comment, not forging its own result. R2 is still the hard guard for weakened tests.
- R3 measures test strength on the changed production code only. A MISSED mutant can be an equivalent mutant (no observable change): the fix is then to assert the behaviour the code really has, and a person may decide the mutant is not worth a test: that is a [waiver](#waivers). Without one a MISSED mutant stays `fail` until a test kills it or the code changes.
- `partial` (budget hit or `max-mutants` reached, nothing MISSED so far) does not block, so part of the diff was not mutated. The reviewer reads the `tested/total` note; a bigger `mutation-budget` or `max-mutants` (or fewer changed lines) is the fix. A budget hit with a MISSED found is `fail`.
- Shard results are merged by `mech-review.py merge`. A missing or stale shard is a CI `fail` entry that names the shard; the other shards' entries are kept. Each `mutants` result carries `shard: {k, n, max_mutants}`; a shard given twice, a shard index missing for `--shards`, or shards that disagree on head, base or cap give one CI `fail` entry (`mutants shards do not match: …`, #42). A result without `shard` (an older engine) is checked on head and base only, unless another result carries it; a malformed field is named. `--envelope K` given twice is a usage error. The CI entries reach the sticky comment and fail the check.

With `stack: auto` the stack and project dir come from the PR's tree, so the `stack` job reads them at the base too and stops when the head finds something else: a PR cannot switch the stack its own checks run with. The job runs no PR code, and its outputs (`stack`, `project-dir`, `error`) reach later jobs only through `env` and `if:` conditions, never a `run:` script. A dir name with a control character is an error, not an output.

The `baseline` job runs PR code too (rust), and its outputs decide whether the shards run, so a malicious test can forge them and skip R3. The outputs reach later jobs only through `env` and the matrix, never a `run:` script. R2 stays the hard guard.
