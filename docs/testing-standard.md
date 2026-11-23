# Testing standard

One bar for tests in every ekit-adopting repo. Apps link this from their agent docs (`AGENTS.md` / `CLAUDE.md`) and add a short local doc with repo specifics ([per-app doc](#per-app-doc)). Don't fork these rules into the app.

Status: R1 (red-first) and R4 (determinism) implemented (#16, `mech-review.py red`). R2 implemented (#13). R3 (mutation on the diff) implemented (#17, `mech-review.py mutants`, cargo-mutants 27.1.0). Python stack (#21): R2, R1, R4 and R3 (mutmut 3.8.1); see [CI doc](mech-review-ci.md#python-r3-mutmut). TypeScript/JavaScript stack (#22): R2, R1, R4 (vitest, jest) and R3 (Stryker 10.0.0); see [CI doc](mech-review-ci.md#typescript-r3-stryker). R3 cap (`max-mutants`, default 40) and risk order (#26): rust and python; ts by changed lines, riskiest first, the mutants counted by Stryker's own instrumenter before the run (#63); cost-based shard count: rust and python (#64: the suite's measured test time), not ts (no baseline measured); see [CI doc](mech-review-ci.md#r3-cap-risk-order-and-shards). Adapter files (EricleungDK/ekit#16): R2 for a stack described as data (`mech-review.py r2 --adapter <file>`), proven on TS; R1, R3, R4 through a file not yet; see [CI doc](mech-review-ci.md#adapter-file). Target OS (#58): an adapter file's `target-os` (default `linux`, the built-ins too) is in `resolve`'s output, and the workflow runs `red-first`, `baseline` and `mutants` on it. Stack plan (#56): `.ekit/stack-plan.toml` and the drift check (`mech-review.py drift`, check `D`, class `adapter-fix`; the base branch's plan judges), and the plan entry's target OS in `resolve`; the guard job runs the drift step before R2; session start (#57) adds the drift at HEAD to the context (git only; one line on python < 3.11); see [CI doc](mech-review-ci.md#stack-plan). R2 rename with changed asserts is `confirm` (#41). Local R3 (#35): `scripts/r3-local.py` runs the workflow's R3 steps with its pins before the review request; see [CI doc](mech-review-ci.md#r3-locally). Developer machine (#34, #46, #59): the hooks and in-session scripts run on macOS, Windows and Linux with Python 3.9+ and Git (launcher, verify commands re-run in their declared shell, `n/a (env)` for a missing one; scenarios as `run.py` with no shell, a `run.sh` or `run.ps1` whose shell is missing `NOT-RUN (env)`); the python suite passes natively on Windows; see [CI doc](mech-review-ci.md#developer-machine). Seeded scenarios (#60): a `- feature:` line in SCENARIO.md marks a scenario's feature; `scenarios.py run` and `check` print `N of M features working`, and `seeded <id>` reads a scenario that passes before its feature exists `CHECKS NOTHING YET`. R0 static half (#20): `mech-review.py r0` proves the adapter against the cheat suite, the negative controls and malformed adapter tables, git and adapter only, in the guard job and first in `all`; a failed case is one `adapter-fix` entry and blocks R1, R2 and R4 (`n/a`; their entries still count), a case with no fixture is `unproven`; adapter files gain `[limits]`; loosening a limit or changing a target OS is one `needs-human` entry; `.ekit/scenarios/**` is a test path for every stack; the runtime half (#21) not yet; see [CI doc](mech-review-ci.md#r0-adapter-proof). Until a check runs, a reviewer applies its rule by hand. Never report a planned check as run.

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
| Delete or rename a failing test | R2 (`fail`, agent-fixable) | deleting or renaming a test to hide a failure | Fix the code; the test is restored. A removal the owner wants is the owner's call, outside the agent loop. The entry stays `fail` until the owner waives it ([waiver](mech-review-ci.md#waivers)); the agent never self-waives it. |
| Rename a test when the spec changes what it asserts | R2 (`confirm`) | renaming a test to hide a changed or weakened assertion | The sanctioned rename (#41): keep the body, change the assertions the spec changed, give it the name of what it now checks. R2 pairs a removed test that has asserts with an added test that has no fewer, when their bodies match. The body is the span the stack's parser gives (after the signature, to the test's end), with its assert lines left out. For a call-style test (ts, adapter files) it is the callback's block, never an `it.each` table or an options object; a callback with no block has no body. Match means Python difflib's `SequenceMatcher.ratio()` over those lines is at least 0.6, and at least 3 lines are shared, and at least half of the old test's lines. It reports one `confirm` entry, `renamed, assertions changed`: the reviewer's decision is on record. A rename with the same asserts gives no entry; an unrelated test in place of a removed one stays the `fail` above. A body too short to keep while its assertion changes (a one-line test) cannot match: that rename stays `fail`, lands in its own commit, and the owner waives its entry. |
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
| R2 test-diff guard | Cheat rows above: removed tests (a rename with the same asserts is not a removal; one with its body kept and its asserts changed is `confirm`), new skip/ignore/xfail/only, `should_panic` added to an existing test (`confirm`), fewer asserts per surviving test fn, weakened or changed expected values (`confirm`), unreasoned suppressions, mutation skips and mutation config edits (`needs-human`), protected paths. No waiver in the PR body, commits or files: only a person's `/mech-waive` PR comment waives ([waivers](mech-review-ci.md#waivers)). | implemented (#13, #26, #27, #41, review round 1) |
| R3 mutation on diff | Rust: cargo-mutants `--in-diff` on changed production code only, run in a worktree at head. Python: mutmut 3.8.1 on the functions that hold a changed line, MISSED kept on changed lines only; a mutant still missed there is tried once against the whole test suite, which also holds the tests mutmut cannot credit. TypeScript: Stryker 10.0.0 on the changed lines (`--mutate` ranges). MISSED mutant = `fail` (agent-fixable), one entry per mutant. TIMEOUT and UNVIABLE ignored. per-mutant timeout derived from the measured baseline (`mutant-timeout` overrides); the baseline runs once, shards skip it; budget per shard and for the baseline (`mutation-budget`, minutes). Budget hit with no MISSED so far = `partial` (`partial: R3 (tested/total)` in the summary), does not block. A mutant the budget never reached (python: also one still waiting for its whole-suite retry) is untested, never MISSED. At most `max-mutants` (default 40) per PR, riskiest first (branch conditions, returns and booleans, arithmetic, the rest, strings and arguments last); past it = `partial` (rust, python; ts by changed lines, #63). Tool not installed = `n/a (env)`. No production file changed = skipped. Sharded in the workflow: risk-ordered round-robin; rust and python (#64) `min(4, mutants, ceil(estimated minutes / (budget / 2)))` shards, no empty shard (python: the suite's measured time; one per changed file, at most 4, when nothing was measured); ts one per changed file, at most 4. | implemented (#17, #26) |
| R4 determinism | Each new or changed test runs 5× at head, in a worktree. Any failing run = `fail`, class `agent-fixable`. A test that does not build or cannot run is a `fail` too. | implemented (#16) |

R2 assert rules:

- Test fns are keyed by name qualified with their enclosing mods (`m1::works`); top-level fns are bare.
- A test that loses asserts is a `fail` unless a helper (non-test fn in the same file) it calls by name gained at least as many asserts. Each gained assert explains one lost assert, once. A helper that nothing calls explains nothing.
- Asserts outside test fns (helpers) are counted per file; the count must not drop.
- Each side is classified by its own path: moving a file between test and prod paths is judged per side.
- Replacing an assert in place (any kind) is `confirm`; reordering is not a change.
- Python assertions: bare `assert`, `self.assert*` (`assertEqual` and `assertNotEqual` are eq and ne), `pytest.raises`. Test fns: `test_*` functions, `test*` methods of `Test*` classes and of `unittest.TestCase` subclasses (a subclass in the same file counts). Names: `test_fn`, `Class::test_method`. Outside `test-paths` these are read only in a file named like a test file (`test_*.py`, `*_test.py`, `tests.py`): a `test_connection()` in `src/app.py` is production code, not a test.
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
