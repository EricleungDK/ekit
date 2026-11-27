# Testing standard

One bar for tests in every ekit-adopting repo. Apps link this from their agent docs (`AGENTS.md` / `CLAUDE.md`) and add a short local doc with repo specifics ([per-app doc](#per-app-doc)). Don't fork these rules into the app.

Status: R1 (red-first) and R4 (determinism) implemented (#16, `mech-review.py red`). R2 implemented (#13). R3 (mutation on the diff) implemented (#17, `mech-review.py mutants`, cargo-mutants 27.1.0). Python stack (#21): R2, R1, R4 and R3 (mutmut 3.8.1); see [CI doc](mech-review-ci.md#python-r3-mutmut). TypeScript/JavaScript stack (#22): R2, R1, R4 (vitest, jest) and R3 (Stryker 10.0.0); see [CI doc](mech-review-ci.md#typescript-r3-stryker). Unconfirmed survivors (#79): a python mutant mutmut reports surviving whose whole-suite retry the budget did not reach is one R3 `confirm` entry by file, line and mutation (field `unconfirmed`, the id of a MISSED entry of that mutation; a mutant mutmut never ran is only counted), the partial entry names its causes (cap, budget, unconfirmed survivors), and `r3-local.py` exits 1 on one. R3 cap (`max-mutants`, default 40) and risk order (#26): rust and python, a capped run's tested/total per risk class in its note, the merge, the comment and `mech-summary.py` (#122; not ts); ts by changed lines, riskiest first, the mutants counted by Stryker's own instrumenter before the run (#63); cost-based shard count: rust and python (#64: the suite's measured test time), not ts (no baseline measured); see [CI doc](mech-review-ci.md#r3-cap-risk-order-and-shards). Adapter files (EricleungDK/ekit#16): R2 for a stack described as data (`mech-review.py r2 --adapter <file>`), proven on TS; R1 and R4 through a file (#18, `red --adapter <file>`: its `[run]` one-test command and outcome patterns, where `pass` needs a counted passed test, and `[commands]` install, build, lint, test), proven on TS by the TS red-first suite; R3 through a file (#19, `mutants --adapter <file>`: its `[mutation.tool]` command, report and report format, read as mutation-testing-elements JSON, PIT XML or a line pattern; MISSED on changed lines only; no tool `n/a`, a tool that cannot run or does not run on the stack's target OS `n/a (env)`; the program on PATH or absolute, never from the reviewed checkout; changing `[mutation.tool]` is R0's `needs-human` entry), proven on TS by the TS mutants suite with Stryker declared in `ts.toml`; see [CI doc](mech-review-ci.md#run-side-r1-and-r4) and [R3 side](mech-review-ci.md#r3-side-mutation-tool). Parser-backed adapter files (#27): `[parser]` names one command that prints a file's facts as JSON, checked against a schema; a parser that fails is one blocking `CI` entry, never a pattern fallback; a repo's adapter file found by name (#17) takes the same path, from the base; the workflow's `guard` and `red-first` jobs install the parser the base's adapter file declares (`mech-review.py parser-install`), and a failed install is the one `CI` entry, never a pass; see [CI doc](mech-review-ci.md#parser). Stack resolution from the repo (#17): `resolve` takes the stacks to run from the base branch's plan (several print as `stacks`, and the workflow runs one set of checks per stack, a matrix over them, reported as one comment and one check: a row per stack, entries labelled with their stack and ids distinct by stack, the check failing when any stack fails or has no result; each stack's mutants merge counts only the results that name that stack, and its project dir when `merge --project-dir` is given, and a stack given twice to the report is one `CI` entry, #62), else detects the manifests of the repo's adapter files too (`.ekit/adapters/<name>.toml`, one named like a built-in in its place), all read at the base; `r2` and `r0 --stack <name>` take the repo's adapter file for that name from the base, and `red` runs R1 and R4 through that file when it has `[run]` (#18); without `[run]`, R1 and R4 on a stack only the repo defines are `n/a` and a file named like a built-in keeps the built-in's run side; R3 on a repo stack runs through the file's `[mutation.tool]`, and is `n/a` without one (#19); an override keeps the built-in's R3 unless it declares a tool; see [CI doc](mech-review-ci.md#stack-resolution). R0 static half (#20): `mech-review.py r0` proves the adapter against the cheat suite, the negative controls and malformed adapter tables, git and adapter only, in the guard job and first in `all`; a failed case is one `adapter-fix` entry and blocks R1, R2 and R4 (`n/a`; their entries still count), a case with no fixture is `unproven`; adapter files gain `[limits]`; loosening a limit, changing a target OS or changing an adapter file's `[mutation.tool]` is one `needs-human` entry; `.ekit/scenarios/**` is a test path for every stack; see [CI doc](mech-review-ci.md#r0-adapter-proof). R0 runtime half (#21): `red --r0 DIR` runs the census (the runner's listing against the scanner, `found/listed`, misses named), assert density (over `[limits] assert-density`, default 10%: one `needs-human` entry until a person accepts the list in `.ekit/r0-accepted.json`, read at the base) and the runner controls (pass, fail, none, build, none, and the skip idiom); `mutants --r0 DIR` (shard 0) the R3 control (weak fixture MISSED, strong none); their runner-dependent cases only when the part's fingerprint (stack, project dir, adapter, fixtures, ekit, target OS, toolchain version lines) has no pass in DIR, density and the changed files' census every run, the hit read before any PR code runs and DIR rewritten with only that run's verdicts, on the stack's target OS; a failed case is one `adapter-fix` entry blocking R1, R2, R4 (run) or R3 (r3); the workflow remembers a pass in `actions/cache`; proven against real pytest and cargo here, the python R3 control against real mutmut, the ts run part against real vitest 2.1.9 and 3.2.7 (built-in and `ts.toml`), after the fix that joins vitest's `-t` names with a space as vitest and jest match them; the ts runner controls against real jest 29.7.0 through `runtime-jest/`; rust's and ts's R3 control not run for real; see [CI doc](mech-review-ci.md#runtime-half). Target OS (#58): an adapter file's `target-os` (default `linux`, the built-ins too) is in `resolve`'s output, and the workflow runs `red-first`, `baseline` and `mutants` on it. Stack plan (#56): `.ekit/stack-plan.toml` and the drift check (`mech-review.py drift`, check `D`, class `adapter-fix`; the base branch's plan judges), and the plan entry's target OS in `resolve`; the guard job runs the drift step before R2; session start (#57) adds the drift at HEAD to the context (git only; one line on python < 3.11), and (#61) declares the build, lint and test commands of the stacks CI resolves at HEAD as the session's verify commands (a built-in: its test command; a step with no command named once; none declared, one line why, on python < 3.11); see [CI doc](mech-review-ci.md#stack-plan). R2 rename with changed asserts is `confirm` (#41). R2 spec-reversed removal is `confirm` (#53): a removed test that a line of a commit message, `spec: #N reverses <test name>`, names, #N among the PR's `--linked-issue`s (the lowest N when several are; none when that name is removed from several files), is one `confirm` for the reviewer, not a waiver; see [CI doc](mech-review-ci.md#inputs). Local R3 (#35): `scripts/r3-local.py` runs the workflow's R3 steps with its pins before the review request, one run per `--env-dir` at a time (a second exits 2 naming the first's pid); see [CI doc](mech-review-ci.md#r3-locally). Developer machine (#34, #46, #59): the hooks and in-session scripts run on macOS, Windows and Linux with Python 3.9+ and Git (launcher, verify commands re-run in their declared shell, `n/a (env)` for a missing one; scenarios as `run.py` with no shell, a `run.sh` or `run.ps1` whose shell is missing `NOT-RUN (env)`); the python suite passes natively on Windows; see [CI doc](mech-review-ci.md#developer-machine). Seeded scenarios (#60): a `- feature:` line in SCENARIO.md marks a scenario's feature; `scenarios.py run` and `check` print `N of M features working`, and `seeded <id>` reads a scenario that passes before its feature exists `CHECKS NOTHING YET`. Verified commit (#81): `scripts/verified-commit.py` refuses a mech-review result whose head is not the review request's head (`--expect`), the worktree's head or the pushed tip (`--allow-behind`: or a tip behind it, fixes not pushed yet); the orchestrate-agent review relay runs it before the review and before a push; see [CI doc](mech-review-ci.md#reading-a-run). Co-change rules (#83): `.ekit/co-change.toml`, read at the base, says "when these paths change, one of those must change too"; R2 gives one `agent-fixable` entry per broken rule at the rule's severity (`confirm` by default, `fail` when promoted), and a malformed file is a usage error naming the field; proof cases and guards (#85): R0's static half runs each rule's `flagged` and `control` case at the head (a rule missing one, or whose case reads wrong, fails R0), and R2 guards a change to the rule file (a head file that does not read, a new rule whose incident resolves to no commit or PR or that lacks a case, a rule that fires and is weakened or removed in the same range: needs-human); see [CI doc](mech-review-ci.md#co-change-rules); ekit's own first rules (#86): a change under `scripts/` updates the changelog, this status line and the CI doc, one rule per doc, at `confirm`. ekit's own CI locally (#84): `scripts/ci-local.py` runs the mech checks (with R0's runtime half) with the checkout's engine, the suite on CI's Python 3.14 through uv, and R3 with ekit's caller inputs, each step passed, failed or not run here, exit 0 only when all passed; and (#115) every `.ekit/scenarios` scenario, which no CI job runs: a FAIL fails the step, named, and a scenario this machine cannot run (its one stderr fail message `ASSERT FAILED: unrunnable here: <what>` on a plain exit-code failure, or the runner's `NOT-RUN (env)`) is not run here, naming the scenario and what is missing; see [CI doc](mech-review-ci.md#developer-machine). Until a check runs, a reviewer applies its rule by hand. Never report a planned check as run. Java end to end (#22): a hand-written reference adapter, a test fixture and no built-in (`tests/fixtures/adapters/java.toml`, never offered by `resolve` or `auto`, deleted by #25), runs R2, R1, R4 (Maven surefire), R3 (PIT on the changed classes, then the changed-line filter) and both R0 halves (census by JUnit's dry run) on a Maven/JUnit 5 fixture repo with the real toolchain, `n/a (env)` without a JDK; the format gains declared tests (`[tests] style = "declared"`: a marked `[functions]` shape, `@Test void x()`), `{module}` and `{package}` in `[mutation.tool].mutate` (a changed file's dotted name, or its package, under `module_roots`; a file under none is named and not mutated), `[mutation] skip_annotations` (marker words that hide code from the tool), an `env` outcome pattern read only when no count was, `[lexer] unicode_escapes`, markers spelled with spaces or comments after `@`, and a mutation tool that ran and wrote no report reads R3 `fail` (no longer `n/a (env)`) and `test-paths` in R0's runtime `controls.json`; see [CI doc](mech-review-ci.md#java-reference-adapter).

## Contents

1. [Good test](#1-good-test)
2. [Test mix](#2-test-mix)
3. [Forbidden cheats](#3-forbidden-cheats)
4. [Checks](#4-checks)
5. [Mech-review vs code review](#5-mech-review-vs-code-review)
6. [Contract](#6-contract)
7. [Per-app doc](#per-app-doc)
8. [Before PR](#before-pr)

## 1. Good test

| Rule | Means |
|---|---|
| Public interface | Call the public API, CLI or endpoint. Assert observable output. Never private helpers. |
| One behaviour | One behaviour per test. Several asserts on one result are fine. |
| Spec-like name | Says the behaviour: `rejects_empty_title`, not `test_3` or `test_helper`. |
| Deterministic | No wall clock, network, unseeded random, or order dependence. Same code, same result. |
| Fast | Unit tests run in milliseconds. A slow test is justified in a comment. |
| Mocks at boundaries | Mock network, clock, filesystem, process, paid APIs. Never your own modules. Prefer a fake (in-memory store) to a mock. |
| No logic | No `if`, loops or computed expectations. Table rows are data, fine. |
| Specific assert | Exact value or error variant. Not "truthy", "is_ok", "not None". |
| Proven red | Fails before the fix, for the ticket's reason. See [R1](#4-checks). |

Specific assert:

```rust
assert!(parse("1.2").is_ok());                       // bad: any Ok passes
assert_eq!(parse("1.2"), Ok(Version::new(1, 2, 0))); // good
```

```python
assert parse("1.2")                     # bad: any truthy value passes
assert parse("1.2") == Version(1, 2, 0) # good
```

```ts
expect(parse("1.2")).toBeTruthy();                        // bad
expect(parse("1.2")).toEqual({ major: 1, minor: 2, patch: 0 }); // good
```

Name:

```
test_1                        # bad
parses_version_1_2            # bad: says nothing about the rule
rejects_empty_version_string  # good
```

## 2. Test mix

Many unit, some integration, few e2e.

| Level | Covers | Share | Speed |
|---|---|---|---|
| Unit | One function or module, through its public interface | most | ms |
| Integration | Modules together, real filesystem or DB in a temp dir | some | seconds |
| E2E | Built binary or app, real entry point | few | slowest |

If a behaviour can be tested at unit level, test it there. Push e2e to the one path per feature that proves it is wired.

## 3. Forbidden cheats

`forbidden` is the shortcut text an entry carries. `caught by`: R1–R4 ([checks](#4-checks)) or code review.

| Cheat | Caught by | Forbidden | Do instead |
|---|---|---|---|
| Delete or rename a failing test | R2 (`fail`, agent-fixable) | deleting or renaming a test to hide a failure | Fix the code; the test is restored. A test the spec reverses (#53): a line of a commit message `spec: #N reverses <test name>` (R2's name for it, `Class::test_fn` in python), with #N an issue the PR closes (`--linked-issue N`), makes the removal one `confirm` entry, `removed, spec #N reverses it`: the reviewer confirms only against a quoted sentence of #N that reverses its assertion, else the test is restored. Any other removal the owner wants is the owner's call, outside the agent loop: the entry stays `fail` until the owner waives it ([waiver](mech-review-ci.md#waivers)); the agent never self-waives it. |
| Rename a test when the spec changes what it asserts | R2 (`confirm`) | renaming a test to hide a changed or weakened assertion | The sanctioned rename (#41): keep the body, change the assertions the spec changed, give it the name of what it now checks. R2 pairs a removed test that has asserts with an added test that has no fewer, when their bodies match. The body is the span the stack's parser gives (after the signature, to the test's end), with its assert lines left out. For a call-style test (ts, adapter files) it is the callback's block, never an `it.each` table or an options object; a callback with no block has no body. Match means Python difflib's `SequenceMatcher.ratio()` over those lines is at least 0.6, and at least 3 lines are shared, and at least half of the old test's lines. It reports one `confirm` entry, `renamed, assertions changed`: the reviewer's decision is on record. A rename with the same asserts gives no entry; an unrelated test in place of a removed one stays the `fail` above. A body too short to keep while its assertion changes (a one-line test) cannot match: remove it, add the new test, and name the spec that reverses it with a `spec: #N reverses <test name>` line (row above), a `confirm`; without that line the removal stays `fail` and the owner waives it. |
| Skip or ignore a test: `#[ignore]`, `@pytest.mark.skip`, `@pytest.mark.xfail`, `@unittest.skip`, `self.skipTest()`, `pytest.skip()` in a body, `it.skip`, `it.todo`, `xit`, `test.only`, `it.only`, `fit`, a `describe.skip` or `describe.only` around it, a `cfg` that disables it or its enclosing mod (`cfg(any())`, `cfg(FALSE)`, `cfg(not(test))`), a skipped class | R2 (`fail`) | #[ignore] / skip / xfail / only on a test | Fix the test failure. Can't run here: note verification debt, don't skip in code. |
| Turn a failing test into a panic-expecting one: `#[should_panic]` added to an existing test | R2 (`confirm`) | adding #[should_panic] to an existing test | Assert the error or the value instead. Intended change: reviewer confirms the `confirm` entry. |
| Drop or move assertions out of a test | R2 (`fail`) | fewer asserts in test `<name>`; fewer asserts in changed test file `<file>` (outside test fns) | Keep the assert. Add a stronger one if needed. Extracting asserts into a helper that the test itself calls is fine (the helper must gain the asserts); moving them into another test, or into a helper the test does not call, is not. |
| Replace an assert in place with a weaker one, any kind: `assert_eq!(x, 3)` to `assert!(x.is_some())`, `assert!(v.len() > 2)` to `assert!(true)` | R2 (`confirm`) | weakening an assertion in place | Keep the assert at least as strict. Intended change: reviewer confirms the `confirm` entry. Reordering asserts is not a replacement. |
| Change expected value to match output | R2 (`confirm`) | editing an expected value to match the code's current output | Check the spec or ticket. The spec sets the value; fix the code. Intended change: reviewer confirms the `confirm` entry. |
| Lint/type suppression without reason: `#[allow]`, `# noqa`, `# type: ignore`, `eslint-disable` (no `-- reason`), `@ts-ignore` (no text after it) | R2 (`fail`) | silencing a lint without a reason | Fix the lint. If it must stay, same-line reason (`#[allow(x, reason = "…")]` with a non-empty reason, `# noqa: E501 — url literal`, `// eslint-disable-next-line no-console -- debug log`, `// @ts-expect-error: the bad input under test`). An empty reason is no reason. |
| Hide code from mutation testing: `#[mutants::skip]` (also in `cfg_attr`), `# pragma: no mutate`, `// Stryker disable`, or a change to the R3 tool's config (`mutants.toml`, `[tool.mutmut]` / `[mutmut]`, `stryker.conf.*` / `stryker.config.*`) | R2 (`fail`, `needs-human`) | hiding code from mutation testing (R3) | Add the test R3 asks for. Code that truly cannot be tested (only a PTY smoke reaches it) is a person's call, in its own PR. No agent downgrade path. |
| Edit a protected path: CI, gate scripts, agent docs | R2 (`fail`, `needs-human`) | editing CI, gate scripts or agent docs to get the gate green | Stop. A human decides. Never edit the gate to pass. No agent downgrade path. |
| No test catches the change: every new or changed test passes on the base's code too | R1 | a production change no test catches | Write a test that fails on the base's code for the ticket's reason (writing it first is still the way). A test that pins existing behaviour passes on base by design: it is a guard and may sit beside it. Fix an R1 fail with a new commit; no history rewrite. |
| Weak or missing assert: test still passes with the code broken, or no test reaches the changed line (python `no tests`, stryker `NoCoverage`) | R3 | MISSED mutant `<desc>` in `<file>` | Add the assert that kills the mutant, or the test that reaches the line: an assert on what a caller or user can observe ([§1](#1-good-test)). A mutant that changes nothing observable is an equivalent mutant: simplify the code until the variant is gone, or hand the entry to the owner ([waiver](mech-review-ci.md#waivers)). Never assert an internal call or move the line to get past the check: that is the last row of this table. |
| Flaky test: passes and fails on same code | R4 | retrying a test until it passes | Find the nondeterminism (time, order, shared state, sleep). Fix it. Never retry to green. |
| Test asserts internals, mocks own code, bad name, logic in test | code review | n/a | Test through public interface. Mock only boundaries. Rename to the behaviour. Remove the logic. |

## 4. Checks

| Check | Enforces | Status |
|---|---|---|
| R1 red-first | The tests base..head adds or changes run on the base's production code (a worktree at the merge base with head's test-path files on top). At least one fails there; a test that does not build there is `compile-red` and counts as red (R4 builds and runs it at head in the same job, so only this PR's production change can be what it needs); the rest are guards. R4 runs them at head. A new or changed test in a file outside `test-paths` (a rust `#[cfg(test)]` mod beside the code) is not on the base's code: R1 does not run it there and counts it in its note, so R1 needs at least one test in a `test-paths` file. Commit order and subjects do not matter, so a later commit fixes an R1 fail. A PR whose only new tests are files of another language under `test-paths` (a python PTY smoke in a rust crate) gets an agent-fixable fail per file with the route in the hint (a stack test; smoke-only logic moved into a testable fn). Agent branches only (`--head-branch` starts with the agent prefix), when production files changed. | implemented (#16; fails-on-base) |
| R2 test-diff guard | Cheat rows above: removed tests (a rename with the same asserts is not a removal; one with its body kept and its asserts changed is `confirm`), new skip/ignore/xfail/only, `should_panic` added to an existing test (`confirm`), fewer asserts per surviving test fn, weakened or changed expected values (`confirm`), unreasoned suppressions, mutation skips and mutation config edits (`needs-human`), protected paths. No waiver in the PR body, commits or files: only a person's `/mech-waive` PR comment waives ([waivers](mech-review-ci.md#waivers)). A `spec: #N reverses <test>` commit line waives nothing: it turns the removal's `fail` into a `confirm` a reviewer decides against #N (#53). | implemented (#13, #26, #27, #41, #53, review round 1) |
| R3 mutation on diff | Rust: cargo-mutants `--in-diff` on changed production code only, run in a worktree at head. Python: mutmut 3.8.1 on the functions that hold a changed line, MISSED kept on changed lines only; a mutant still missed there is tried once against the whole test suite, which also holds the tests mutmut cannot credit. TypeScript: Stryker 10.0.0 on the changed lines (`--mutate` ranges). MISSED mutant = `fail` (agent-fixable), one entry per mutant. TIMEOUT and UNVIABLE ignored. per-mutant timeout derived from the measured baseline (`mutant-timeout` overrides); the baseline runs once, shards skip it; budget per shard and for the baseline (`mutation-budget`, minutes). Budget hit with no MISSED so far = `partial` (`partial: R3 (tested/total)` in the summary), does not block. A mutant the budget never reached (python: also one still waiting for its whole-suite retry) is untested, never MISSED. At most `max-mutants` (default 40) per PR, riskiest first (branch conditions, returns and booleans, arithmetic, the rest, strings and arguments last); past it = `partial` (rust, python; ts by changed lines, #63). Tool not installed = `n/a (env)`. No production file changed = skipped. Sharded in the workflow: risk-ordered round-robin; rust and python (#64) `min(4, mutants, ceil(estimated minutes / (budget / 2)))` shards, no empty shard (python: the suite's measured time; one per changed file, at most 4, when nothing was measured); ts one per changed file, at most 4. | implemented (#17, #26) |
| R4 determinism | Each new or changed test runs 5× at head, in a worktree. Any failing run = `fail`, class `agent-fixable`. A test that does not build or cannot run is a `fail` too. | implemented (#16) |

R2 assert rules:

- Test fns are keyed by name qualified with their enclosing mods (`m1::works`); top-level fns are bare.
- A test that loses asserts is a `fail` unless a helper (non-test fn in the same file) it calls by name gained at least as many asserts. Each gained assert explains one lost assert, once. A helper that nothing calls explains nothing.
- Asserts outside test fns (helpers) are counted per file; the count must not drop.
- Each side is classified by its own path: moving a file between test and prod paths is judged per side.
- Replacing an assert in place (any kind) is `confirm`; reordering is not a change.
- Python assertions: bare `assert`, `self.assert*` (`assertEqual` and `assertNotEqual` are eq and ne), `pytest.raises`. Test fns: `test_*` functions, `test*` methods of `Test*` classes, of `unittest.TestCase` subclasses (a subclass in the same file counts), and, in a file pytest collects (`test_*.py`, `*_test.py`), of a class on a base the file does not define (an imported base such as `from _kit import Fixture`, directly or through same-file helper classes; never in `conftest.py` or a helper module, where a fake's `test_connection` is no test; a class with no base, or only `object`, is no test class unless it is named `Test*`). Names: `test_fn`, `Class::test_method`. Outside `test-paths` these are read only in a file named like a test file (`test_*.py`, `*_test.py`, `tests.py`): a `test_connection()` in `src/app.py` is production code, not a test.
- Python suppressions: `# noqa` and `# type: ignore` need a reason after the codes (`# noqa: E501 - url literal`). An unparseable file is an R2 `fail` (it cannot be checked), not a crash.
- TypeScript/JavaScript assertions: `expect(x).toBe(y)`, `toEqual`, `toStrictEqual` (eq; `.not` makes it ne), any other matcher is `other`. Test fns: `it`/`test` inside `describe` (qualified `Describe > name`), and at top level; `.each` rows are one test. Suppressions: `eslint-disable*` (`-- reason`), `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck` (text after the directive). The parse check is lexical (brackets, unterminated comment or template): a file that passes it can still fail to compile, which the runner reports as `build`.

Statuses (per check, in the envelope):

- `pass`: ran, no `fail` entries.
- `fail`: at least one `fail` entry. Blocks. Only a code fix, or a person's waiver of each entry, clears it.
- `waived`: the check ran and every `fail` entry it had was waived by a person (CI report step only). Does not block. Never `all pass`.
- `partial`: R3 budget hit with no MISSED so far, or mutants past `max-mutants`. The summary reads `partial: R3 (tested/total)`. Does not block.
- `skipped`: check does not apply, or a subcommand does not run it (`not run by r2`). Reason in the note. R1 is skipped for docs-only PRs and non-agent branches.
- `n/a`: the check could not run here: its toolchain or tool is absent or not installable (`toolchain absent … (env)`, `n/a (env)`). Not `pass`, not `skipped`: the summary names it. Say so in the report.

R3 is not run by `r2`, `red` or `all` (note `not run by <subcommand>`); it runs in the `mutants` subcommand, one shard per workflow job. A check that did not run is never reported as passed.

## 5. Mech-review vs code review

Both are required for merge. Neither overrides the other.

| | Mech-review | Code review |
|---|---|---|
| Answers | Facts: did the rule break? | Judgment: is the test good? |
| Input | git base..head, config, test and mutation runs | diff, mech-review JSON, spec |
| Same input, same output | Yes | No |
| Covers | Rows R1–R4 | Test design, naming, mock placement, spec fit, whether a `confirm` entry is the spec'd behaviour |

Order:

1. Mech-review runs first. Its JSON (`<!-- mech-review -->` PR comment) goes to the reviewer.
2. Reviewer does not re-derive facts. It reads `confirm` entries and decides each.
3. A reviewing agent cannot waive a `fail` entry: fix it or report it. A person can, with a `/mech-waive <id> <reason>` PR comment ([waivers](mech-review-ci.md#waivers)).
4. Mech green does not mean review passed. Review approve does not excuse a `fail`.

## 6. Contract

Entry fields (stable; add fields, never rename):

| Field | Values |
|---|---|
| `id` | `<check>-<8 hex of sha1(check + file + key)>`, key = rule and test fn name (`ignore:<fn>`, `assert-count:<fn>`, ...). Same across rounds, survives line moves. A repeat of one key in one file (line order): the 2nd occurrence is keyed `<key>#1`, the 3rd `<key>#2`; the first keeps the plain key. |
| `check` | `R1`, `R2`, `R3`, `R4`, `D` (the stack plan's drift check; only in a repo with a stack plan, see [CI doc](mech-review-ci.md#stack-plan)), `CI` (`CI` reserved for CI-level failures outside R1–R4 and D, e.g. mech-review's own infra error) |
| `class` | `agent-fixable`, `needs-human`, `env`, `adapter-fix` (the stack plan or an adapter file needs a change, in a PR of its own: a manifest no stack covers, check `D`) |
| `severity` | `fail` (blocks), `confirm` (reviewer decides), `waived` (was `fail`; a person let it through, see `waiver`) |
| `waiver` | only on a `waived` entry: `{by, reason, url}` of the `/mech-waive` comment |
| `file`, `line` | location |
| `problem` | what broke |
| `hint` | intended fix |
| `forbidden` | shortcut not allowed |
| `unconfirmed` | only on an R3 unconfirmed survivor (#79): `true`. Its id is the one a MISSED entry of the same mutation has |

Envelope: head SHA, base SHA, ekit version, per-check status (`pass|fail|waived|partial|n/a|skipped`) with note, entries, summary. Check `D` is present only when the repo has a stack plan on base or head, and carries `messages` (planned, retiring and vanished stacks); without a plan no summary names it.

Summary:

- `all pass <sha>`: no entries and every check passed. Never while a check is skipped or n/a.
- Otherwise `<pass|fail> <sha> (<F> fail, <C> confirm[, <W> waived]; ran: <checks>[; partial: R3 (<tested>/<total>)][; skipped: <checks>][; n/a: <checks>])`. `, <W> waived` appears only when a person waived an entry. The `; partial:` part appears only when R3 hit its budget (a partial check is also listed under `ran`), `; skipped:` only when some check is skipped, `; n/a:` only when some check is n/a, e.g. `pass <sha> (0 fail, 1 confirm; ran: R2; skipped: R1 R3 R4)`. `fail` when `F` > 0.
- Same format in `--format text` (first line) and in the envelope.

## Per-app doc

Each repo writes a short `docs/testing.md` (or section in `AGENTS.md`). Link the standard. Add repo specifics only. Copy and fill:

```markdown
# Testing: <app>

Standard: https://github.com/EricleungDK/ekit/blob/<ekit-tag>/docs/testing-standard.md
Rules there apply here. This file holds only repo specifics.
Link must match the ekit tag pinned in the caller workflow.

- Stack: rust
- Agent branch prefix: agent/
- Mutation budget: <minutes>

- Unit tests: `src/**` `#[cfg(test)]` modules
- Integration tests: `tests/*.rs`
- E2E: `tests/e2e/`, run by `make e2e`
- Gate: `make check` (fmt, clippy, test). Run before push.
- Mock here: HTTP client (`src/net.rs` trait), clock (`src/time.rs` trait)
- Protected paths: `.github/`, `scripts/gate.sh`, `AGENTS.md`, `CLAUDE.md`
```

Stack examples for test paths: Python `tests/test_*.py`, TS `src/**/*.test.ts`.

## Before PR

- At least one new or changed test fails on the base's code for the ticket's reason (R1), and passes at head.
- No skip, ignore, only, or new suppression without reason.
- No assert removed, moved out of its test, or weakened in place.
- Expected values match the spec, not the output.
- Gate passes locally. Say which checks were not run.
- Python stack: R3 passes locally (`scripts/r3-local.py`, the CI inputs): a MISSED mutant on a changed line is fixed before review.
- ekit's own engine tests call the CLI through `run_cli(argv)` (`tests/py/_kit.py`), in-process: R3's mutmut credits only in-process calls, so a subprocess-only test leaves every line it reaches MISSED. Start a subprocess only where process isolation is the point (`-I`, a hook's exit code, an env var read at start).
