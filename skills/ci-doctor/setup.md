# Setup mode

For a project no built-in stack covers: generate its adapter file, prove it with R0, and open the setup PR. `DOCTOR`, `<py>` and `<kit>` are SKILL.md's; `MR` = `<py> -I <kit>/scripts/mech-review.py`. Format of every file named here: `<kit>/docs/mech-review-ci.md`, sections Adapter file (all subsections), R0 adapter proof (and Runtime half), Stack plan, Setup mode. `<name>` is the stack's name: the language or build tool (`java`, `maven`), letters, digits, `_` or `-`.

The proof gates the PR: a setup PR goes out only with every R0 case passing.

## 1. Detect

Start from `DOCTOR`'s `setup.projects[0]`: folder, manifests, language, build tool, test framework, target OS and its reason, and `setup.own_ci`, the repo's own workflows.

An empty repo (`no-project`) where the user names the stack to come ("a Java API"): take language, build tool and test framework from their words (ask for what they leave open), folder `.`, and the target OS by doctor's rule: windows for a WPF app, macos for an iOS app, else linux. Its plan entry is `planned`.

## 2. Cheat list, from the language alone

Written before any adapter exists, by a second agent that sees the language, build tool and test framework and never the adapter. Harness with a subagent tool: start one with that brief and the categories below. Harness without one: write it yourself now, as a pass of its own, before step 3; it stands as written. Either way the writer reads the repo's test files (step 3's idioms), never an adapter draft.

The writer lists every way, in each category, that a PR in this language can skip a test or hide a mutant, and writes the R0 fixtures for them (`.ekit/adapters/<name>.r0/`: `seed`, `skip`, `expected-value`, `weaken-assert`, `suppression`, `helper-asserts` and the three `source-` cases; the runtime fixtures `runtime/`), in the repo's own idioms:

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

Read how the repo writes its tests (test files, the manifest's test and lint setup), then write `.ekit/adapters/<name>.toml`: `name`, `manifests`, `extensions`, `target-os` (step 1's), the lexer, tests, asserts, suppressions and mutation tables, `[mutation.tool]`, `[commands]` (install, build, lint, test: the repo's own toolchain), `[run]`, `[run.list]` and `[run.outcome]`.

## 4. Prove it with R0

Budget: 5 rounds; a round is one adapter revision and one static run. Nothing is committed yet; the static half reads the working tree:

```
MR r0 --repo <repo> --base HEAD --head HEAD --stack <name> --adapter .ekit/adapters/<name>.toml
```

Pass is `checks.R0.status` `pass`, never the exit code: exit 0 also covers `unproven`, a case with no fixture yet. Each failed case is a fix to the adapter; a cheat fixture changes only when it is not valid code in the language, and the report says which and why.

Each cheat-list item with no R0 case of its own: commit the seed and then the cheat in a scratch repo, run `MR r2 --repo <scratch> --base <seed> --head <cheat> --stack <name> --adapter <file> --test-paths '<glob>'`, and record it as caught (the entry) or a limit (no entry the format can give). Name each limit in a comment at the top of the adapter and in the report.

Runtime half, where the toolchain is installed and this machine is the target OS (`--r0` takes an empty scratch dir): `MR red ... --stack <name> --adapter <file> --test-paths '<glob>' --head-branch claude/setup --r0 <dir>` (census, runner controls) and `MR mutants ... --r0 <dir>` (the R3 control). `checks.R0` must read `pass`; an `n/a` is the report's "not run here: <why>".

Budget spent with a case still failing or unproven: stop here. Commit nothing, open no PR, and report blocked via finish: each failed case as `r0` names it, the cheats left uncaught, the draft's path, and what would unblock it.

## 5. Stack plan

Add the entry to `.ekit/stack-plan.toml` (write the file if there is none): `name`, `folder`, `adapter = ".ekit/adapters/<name>.toml"`, `status` `current` when the manifest is there, `planned` when it is not yet; `target-os` when not linux. A migration also follows SKILL.md's Stack plan section.

## 6. CI files

The caller and the waiver caller as SKILL.md step 3 (`test-paths`: the project's test folder, e.g. `src/test/**`, plus `.ekit/scenarios/**`; `stack` stays `auto`: the plan names it).

Base CI jobs only when `setup.own_ci` is empty: `.github/workflows/ci.yml`, one job on the target OS's runner (`ubuntu-latest`, `windows-latest`, `macos-latest`) that sets up the toolchain and runs the adapter's `[commands]` in order, install, build, lint, test (an empty one left out). Every workflow the team wrote stays byte for byte.

## 7. Commit and recheck

On a new branch, commit it all, then prove the committed files the way CI reads them: `MR r0 --repo <repo> --base HEAD --head HEAD --stack <name> --project-dir <folder>` (`pass`) and `MR drift --repo <repo> --base HEAD --head HEAD --format text` (`pass`, no fail entry).

## 8. Open the setup PR

Push and open it, as SKILL.md step 5. Its body, beside step 5's:

- Files: the adapter and its fixtures, the stack plan entry, the callers, the base CI jobs or why none (`own_ci` names the team's).
- Detection: doctor's `setup` (language, build, test framework, target OS and why).
- Proof report: the static half (`N of N cases`), the runtime half's result or not run here and why, and the cheat list, each item caught (its R0 case, or the r2 run) or a named limit.
