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
