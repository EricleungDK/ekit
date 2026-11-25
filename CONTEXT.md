# ekit

A plugin that makes coding agents prove their work: in-session skills and hooks on the developer's machine, and mechanical checks on each pull request.

## Language

### Stacks

**Stack**:
The language, test framework and toolchain one project in a repo is built with (Java with Maven and JUnit 5, say).
_Avoid_: language (alone), tech, framework

**Current stack**:
A stack the repo's tracked files already show, through its manifests.
_Avoid_: detected stack, existing stack

**Planned stack**:
A stack the user means to build with that the repo's files don't show yet: a new project, a migration target, or an added service.
_Avoid_: intended stack, future stack, target stack

**Retiring stack**:
A current stack the user is migrating away from: still checked, and expected to lose its manifests.
_Avoid_: legacy stack, old stack, deprecated stack

**Stack plan**:
The one file in a repo that lists its stacks (planned, current and retiring), where each lives, which adapter checks it and its target OS.
_Avoid_: verification plan, stack config, ci-doctor-stack

**Drift check**:
The git-only comparison of the stack plan with the repo's tracked manifests: a manifest no stack covers blocks the PR (check `D`, class `adapter-fix`); planned, retiring and vanished stacks get a message.
_Avoid_: plan check, stack lint

**Adapter file**:
A declarative file in the user's repo that tells ekit's checks everything stack-specific about one stack.
_Avoid_: config, stack file, plugin

**Built-in adapter**:
An adapter shipped with ekit itself (Rust, Python, TypeScript/JavaScript), used when no adapter file overrides it.

### Machines

**Developer machine**:
The computer where the user's agent session runs, on macOS, Windows or Linux; ekit's skills and hooks run here.
_Avoid_: host, local, client

**Target OS**:
The operating system a stack's tests must run on to mean anything (Windows for a WPF app); it decides the CI runner for that stack, whatever the developer machine is.
_Avoid_: runner OS, platform

### Checks

**Co-change rule**:
A rule kept as data in the repo (`.ekit/co-change.toml`): when a path matching its triggers changes, at least one path matching its required globs must change in the same range; R2 reports each broken one, at `confirm` until promoted to `fail`.
_Avoid_: doc rule, update rule, path lint

### Mutation (R3)

**Unconfirmed survivor**:
A mutant mutmut reports surviving on a changed line whose whole-suite retry the budget did not reach or cut short: one R3 `confirm` entry naming its file, line and mutation, with the id a MISSED entry of that mutation has, out of the tested count, and a missed mutant until a test kills it. A mutant mutmut never ran is not one: the partial entry counts it as untested.
_Avoid_: untested mutant, unreached mutant
