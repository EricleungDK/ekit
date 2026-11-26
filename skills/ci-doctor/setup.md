# Setup mode

For a project no built-in stack covers: generate its adapter file, prove it with R0, and open the setup PR. `DOCTOR`, `<py>` and `<kit>` are SKILL.md's; `MR` = `<py> -I <kit>/scripts/mech-review.py`. Format of every file named here: `<kit>/docs/mech-review-ci.md`, sections Adapter file (all subsections), R0 adapter proof (and Runtime half), Stack plan, Setup mode. `<name>` is the stack's name: the language or build tool (`java`, `maven`), letters, digits, `_` or `-`.

The proof gates the PR: a setup PR goes out only with every R0 case passing.

## 1. Detect

Start from `DOCTOR`'s `setup.projects[0]` (mode `setup`): folder, manifests, language, build tool, test framework, target OS and its reason, and `setup.own_ci`, the repo's own workflows.

An empty repo (`no project found: no ...`, mode null) where the user names the stack to come ("a Java API"): take language, build tool and test framework from their words (ask for what they leave open), folder `.`, and the target OS by doctor's rule: windows for a WPF app, macos for an iOS app, else linux. Its plan entry is `planned`.

## 2. Cheat list, from the language alone

Written before any adapter exists, by a second agent that sees the language, build tool and test framework and never the adapter. Harness with a subagent tool: start one with that brief and the categories below. Harness without one: write it yourself now, as a pass of its own, before step 3; it stands as written. Either way the writer reads the repo's test files (step 3's idioms), never an adapter draft.

The fixtures are written for this repo, never copied from the kit's test fixtures. The writer lists every way, in each category, that a PR in this language can skip a test or hide a mutant, and writes the R0 fixtures for them (`.ekit/adapters/<name>.r0/`: `seed`, `skip`, `expected-value`, `weaken-assert`, `suppression`, `helper-asserts` and the three `source-` cases; the runtime fixtures `runtime/`; their rules: the Fixtures bullets of R0 adapter proof and Runtime half), in the repo's own idioms:

- **Marker skips**: each marker, annotation, attribute or call that disables a test, conditional ones too (OS, runtime version, env).
- **Composed markers**: a marker the project defines that carries a skip or a test marker (meta-annotation, alias, macro, decorator factory).
- **Runtime skips**: a test that skips itself from its body (assumptions, skip calls).
- **Grouping**: nested or inner test groups: how the runner names one, runs it by name (R1, R4) and lists it (the census).
- **Config that changes what runs**: build profiles or config switched on by a file, env or OS, and runner filters (tags, include and exclude lists) that change which tests run or what the mutation tool mutates.
- **Lint silencing**: every form a suppression takes (comment, annotation, attribute), with and without a reason.
- **Mutation hiding**: markers and config that keep code from the mutation tool (generated-code markers, exclude lists).
- **Assert forms**: each assertion style the repo uses (plain call, member call, fluent chain), so the assert fixtures read like its tests.

Java, as an example of the categories: a composed `@Disabled` or `@Test`, `assumeTrue`, `@Nested`, a file-activated Maven profile, `@SuppressWarnings`.

## 3. Draft the adapter

Read how the repo writes its tests (test files, the manifest's test and lint setup), then write `.ekit/adapters/<name>.toml` for this repo: generated from what it holds, never copied from the kit's own test fixtures (`<kit>/tests/fixtures/adapters/`, ekit's tests of the format; the graders fail a copy). Its keys: `name`, `manifests` (every manifest of the build in the folder, e.g. both `build.gradle.kts` and `settings.gradle.kts`: one it leaves out reads as a second project), `extensions`, `target-os` (step 1's), the lexer, tests, asserts, suppressions and mutation tables, `[mutation.tool]`, `[commands]` (install, build, lint, test: the repo's own toolchain), `[run]`, `[run.list]` and `[run.outcome]`.

The proof runs the R3 control on the fixture project, so it cannot see whether the repo's own build runs the declared mutation tool (a plugin the build file must name, say). Check that it does. If it does not, add that wiring to the setup PR, or leave `[mutation.tool]` out so that R3 reads `n/a`. The PR body says which.

## 4. Prove it with R0

The proof is every R0 case of both halves, the census and the cheat list. Budget: 5 rounds; a round is one adapter revision and one run of the proof below, and a failing case of either half counts the same. Nothing is committed yet; each step reads the working tree:

1. **Static half**: `MR r0 --repo <repo> --base HEAD --head HEAD --stack <name> --adapter .ekit/adapters/<name>.toml`. Pass is `checks.R0.status` `pass`, never the exit code: exit 0 also covers `unproven`, a case with no fixture yet.
2. **Census of the repo's own tests**: clone the repo into a scratch folder, delete its test files there and commit, then run `MR r2 --repo <scratch> --base HEAD~1 --head HEAD --stack <name> --adapter <abs path of the file> --test-paths '<glob>'`. It must name every test the repo's test files hold (`test fn ... removed`); each one it misses is a failed case. An empty repo has none.
3. **Runtime half**, where the toolchain is installed and this machine is the target OS (`--r0` takes an empty scratch dir): `MR red ... --stack <name> --adapter <file> --test-paths '<glob>' --head-branch claude/setup --r0 <dir>` (census, runner controls) and `MR mutants ... --r0 <dir>` (the R3 control). `checks.R0` must read `pass`; an `n/a` is the report's "not run here: <why>".
4. **The cheat list**: each item with no R0 case of its own is proved like the census, in a scratch clone (never a branch of the repo): commit the seed, then the cheat, and `MR r2` on that pair must give its entry.

Each failed case is a fix to the adapter; a cheat fixture changes only when it is not valid code in the language, and the report says which and why.

A cheat the proof cannot catch is a **limit** only when the CI doc already names it as one (`<kit>/docs/mech-review-ci.md`: the format's own limits), or when the PR body lists it under a `## Limits (owner decides)` heading, which the owner accepts or rejects before merging. Name each in a comment at the top of the adapter too. Any other uncaught cheat is a miss. A limit covers an uncaught cheat alone, never a failing R0 case or a census miss, and it replaces no round: when the doc names a limit you expect to fail the proof (Go's tests declared by their name alone, say), still draft the adapter and its fixtures, run the proof and revise round by round; the report names each case that still fails as `r0` or `r2` gave it.

Budget spent with a case failing, unproven or missed: stop here. Commit nothing, open no PR, and report blocked via finish: each failed case as `r0` or `r2` names it, the cheats missed, the draft's path, and what would unblock it.

## 5. Stack plan

Add the entry to `.ekit/stack-plan.toml` (write the file if there is none): `name`, `folder`, `adapter = ".ekit/adapters/<name>.toml"`, `status` `current` when the manifest is there, `planned` when it is not yet; `target-os` when not linux. A migration also follows SKILL.md's Stack plan section.

## 6. CI files

The caller and the waiver caller as SKILL.md step 3 (`test-paths`: the project's test folder, e.g. `src/test/**`, plus `.ekit/scenarios/**`; `stack` stays `auto`: the plan names it).

Base CI jobs only when `setup.own_ci` is empty (no workflow with a build or test job of the team's): a new file, `.github/workflows/<name>-base-ci.yml` (another free name if that one is taken), with one job on the target OS's runner (`ubuntu-latest`, `windows-latest`, `macos-latest`) that sets up the toolchain and runs the adapter's `[commands]` in order, install, build, lint, test (an empty one left out). Every workflow file already there stays byte for byte.

## 7. Commit and recheck

On a new branch, commit it all, then prove the committed files the way CI reads them: `MR r0 --repo <repo> --base HEAD --head HEAD --stack <name> --project-dir <folder>` (`pass`) and `MR drift --repo <repo> --base HEAD --head HEAD --format text` (`pass`, no fail entry).

## 8. Open the setup PR

Push and open it, as SKILL.md step 5. Its body, beside step 5's:

- How its own check reads. The base resolves no stack (no built-in project there): `no result`, red with nothing to waive; the owner merges on the proof report below, then makes the mech-review check required (an empty repo: after the first manifest lands). The base resolves one (a built-in project beside the new one): the check runs and reads red `needs-human` for `.github/**`, and also for the new stack when its adapter declares a `[mutation.tool]` or its target OS is not linux (R0 compares a folder new to the plan with the defaults: linux, the default limits, no mutation tool); the owner waives those entries, as SKILL.md step 5 says, and merges. Later PRs compare with the merged entry and give none.

- Files: the adapter and its fixtures, the stack plan entry, the callers, the base CI jobs or why none (`own_ci` names the team's), and the mutation tool's wiring in the repo's build, or that `[mutation.tool]` is left out (step 3).
- Detection: doctor's `setup` (language, build, test framework, target OS and why).
- Proof report: the static half (`N of N cases`), the census (`N of N tests`), the runtime half's result or not run here and why, and the cheat list, each item caught (its R0 case, or the r2 run) or a limit the CI doc names (quoted).
- `## Limits (owner decides)`: each other cheat the proof cannot catch, with why; leave the heading out when there is none.
