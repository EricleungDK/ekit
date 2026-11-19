# Adapter limits: design note

Status: proposal for the owner. No code yet. Trust rules in [mech-review CI](../mech-review-ci.md) stay as they are.

Context: ekit moves from three hand-written adapters (`scripts/mech_review/stack.py`: rust, python, ts) to a language-free core. At setup `ci-doctor` writes a declarative adapter (`.ekit/stack.toml`) in the user's repo. The adapter proves itself against a language-neutral cheat list before the setup PR opens, and a person merges it. CI stays deterministic. The adapter is protected and read from the base branch.

This note answers three open problems.

| # | Problem | Recommendation |
|---|---|---|
| 1 | R3 with no mutation tool, fast | Use the language's tool when one exists. When none does: ekit's lexical mutator, but each mutant runs the PR's own tests first and the whole suite only if it survives them. One mutant per site, risk order, a count cap, one warm build tree. |
| 2 | Patterns are weaker than parsers | Structured patterns stay the default. The format allows one optional parser command that prints ekit's facts as JSON. The core only starts it and checks its output. |
| 3 | Weak adapter that passes the proof | Make the proof measure the adapter against the test runner, not against itself. Re-run the proof in CI: the git-only half on every PR, the half that runs tests when the adapter, the toolchain or ekit changes. |

Words used here:

- **PR's tests**: the new or changed tests R1 already finds and runs by name.
- **Site**: one place in a changed line where a mutant can be made (one operator, one condition).
- **Facts**: what the adapter interface returns for a file today (test fns with spans and markers, assertions with operands, suppressions, mutation skips).
- **Census**: comparing the tests the scanner finds with the tests the runner lists.

## 1. R3 without an off-the-shelf tool

### Recommendation

Three tiers, picked at setup and written in the adapter:

1. **A tool exists: use it.** The adapter declares the command, the report path and the report format. The core reads three report formats and has no per-tool code: mutation-testing-elements JSON (the Stryker family; mull's `Elements` reporter), PIT's `mutations.xml`, and a line pattern with named groups (`file`, `line`, `status`) for the rest. The tool mutates the changed files; ekit keeps the MISSED mutants on changed lines, as it does for mutmut today. A tool's own diff flag is a speed-up, never a requirement.
2. **No tool: the ekit lexical mutator, tests in two steps.** Details below.
3. **Neither can be proven at setup: R3 is `n/a`**, named in every summary (`n/a: R3`). Never a pass.

The lexical mutator, made fast:

- **One mutant per site.** A fixed table picks the one replacement per operator that is hardest to kill (`<` to `<=`, `==` to `!=`, `&&` to `||`, `+` to `-`, `true` to `false`, a negated branch condition). The adapter lists the language's operator spellings, longest first, so `->` and `=>` are not read as `-` and `>`. Mutants are made on masked text: never in strings or comments.
- **Risk order.** Sites on a line with a branch keyword (`if`, `while`, `case`, the adapter lists them) come first, then return lines and boolean literals, then arithmetic. Ties break by file, line, column. The order is the same on every run.
- **Count cap.** `max-mutants` per PR (proposed default 40). Sites past the cap are not tested and R3 is `partial (tested/total)`, never `pass`.
- **One warm build tree per shard.** A mutant is written in place, built incrementally, tested, and the file is put back (content and mtime handled as `whole_suite` does for python today). No fresh checkout per mutant.
- **Two test steps per mutant, both fail-fast.** Step 1 runs the PR's tests, by name, with the single-test command the adapter already proved. A failure is a kill. Only a mutant that survives step 1 gets step 2: the whole suite once. A failure is a kill; a pass is MISSED.
- **Coverage, when the adapter declares it.** The baseline's one suite run also writes a coverage file (lcov, Cobertura XML or JaCoCo XML; the core reads these three). A mutant on a line no test reaches is MISSED (`no coverage`) at once: no build, no test run. Without a coverage command this step is left out; nothing else changes.

Why this one: test time dominates, not build time, and the PR's tests are the tests most likely to kill a mutant on the PR's lines. Step 1 needs nothing new from the adapter. cargo-mutants already pays one incremental build per mutant, so the build cost is on par with the rust stack today.

### Cost on a typical PR

Model: 5 changed functions, about 60 changed lines, 30 mutants (one per site). Of these 2 do not build, 20 are killed by the PR's tests, 4 only by older tests, 4 survive. Clean build 90 s, incremental build 15 s, whole suite 120 s (a fail-fast kill stops at 60 s on average), the PR's tests 5 s, the tests that cover one line 15 s. 4 shards; each shard starts with one clean build. The `baseline` job (one build, one suite run: 3.5 min) is the same for every row and left out.

| Option | Builds | Test runs | Machine | Per shard |
|---|---|---|---|---|
| Lexical, whole suite per mutant, no fail-fast (rejected) | 4 clean + 30 incremental | 28 whole | 70 min | 17 min: `partial` at the default budget |
| Same, with fail-fast | 4 + 30 | 28 whole (24 stop early) | 46 min | 11 min: `partial` |
| Coverage-guided test selection (per-test coverage) | 4 + 30, and one coverage run | 28 small | 22 min | 4.4 min |
| Mutant schemata alone (one build, mutants switched by env var) | 4 instrumented + about 4 rebuilds | 28 whole | 41 min | 10 min |
| Count cap alone (15 of 30) | 4 + 15 | 14 whole | 26 min | 6.4 min, and always `partial` |
| PR's tests first, whole suite for survivors | 4 + 30 | 28 small + 8 whole | 28 min | 7.0 min |
| **Recommended**: the row above, with coverage declared (2 of the 4 survivors are on uncovered lines) | 4 + 28 | 26 small + 6 whole | 23 min | 5.8 min |
| PR's tests first, plus schemata (no coverage) | 4 instrumented + about 4 rebuilds | 28 small + 8 whole | 23 min | 5.8 min |
| An existing tool (PIT-like: no rebuild per mutant, its own per-test coverage) | 1 | 1 coverage pass + 30 small | 5.5 min | one shard |

Reading the table:

- Step 1 removes 20 of 28 whole-suite runs. That is the main saving, and it is language-neutral.
- Schemata alone saves only the 30 incremental builds (7.5 min of 46): the suite runs remain. It pays off where an incremental build is slow (60 s and more), and those languages have tools.
- Coverage-guided selection is the fastest ekit-owned option on paper, but it needs per-test coverage, which has no common output format across languages. Aggregate coverage is common and is used above only to skip uncovered lines.
- A real tool is four to five times cheaper than the best fallback. The fallback is the last resort, not the design centre.
- Slow suite (10 min instead of 2): the recommended design needs 19 min per shard and reports `partial`; the rejected one needs 43 min. The fallback does not rescue a slow suite. The answers stay the documented ones (smaller diff, narrower tests), or a tool.
- Interpreted language (no build): 14 min of machine time for the recommended design, 32 min for whole-suite-per-mutant with fail-fast.

These are model numbers. `checks.R3.timing` already reports build and test seconds per mutant; the first real fallback run replaces them.

### Fit with sharding, `mutation-budget` and `partial`

| Rule today | With the lexical mutator |
|---|---|
| `baseline` runs once, sets shard count and timeout | Same job: clean build, whole suite once at head (red is R3 `fail`: baseline tests fail at head), coverage if declared. The mutant list comes from git and the adapter alone, so it is exact before any build. Step 2 timeout: 5× the measured suite, at least 20 s. Step 1 timeout: 5× the measured PR's tests. |
| Shards: at most 4, never empty, round-robin | The list is sorted by risk, then dealt round-robin, so every shard holds an even share of the high-risk sites. Shard count: `min(4, mutants, ceil(estimate / half the budget))`, with the estimate from the baseline's build and suite seconds. A small PR gets one shard and one clean build. |
| `mutation-budget` per shard; hit with no MISSED is `partial`, with a MISSED is `fail` | Unchanged. A shard works through its list in risk order; what the budget does not reach is untested. |
| `tested/total` | `total`: all sites in the diff, before the cap. `tested`: mutants with a final verdict. A mutant cut off between step 1 and step 2 is untested, not MISSED: surviving the PR's tests alone is not proof. |
| TIMEOUT and UNVIABLE are neither caught nor missed | A mutant that does not build is unviable (the adapter's compile-vs-fail pattern says which). A lexical mutant in a type position (`List<String>`) costs one failed build, never a false MISSED. |
| MISSED = `fail`, one entry per mutant | Unchanged. Entry key: file, function, operator, occurrence in the function. It survives line moves. |
| Hiding code from R3 is `needs-human` | The lexical mutator has no skip marker and no config file in the repo. `max-mutants` and the operator list live in the protected adapter. |
| Tool not runnable = `n/a (env)` | Build or suite command not runnable: `n/a (env)`, with the adapter key in the note. |

What the lexical mutator does not make: return-value replacements, removed statements, removed arguments. It is the weakest column of the "what each stack mutates" table, and that table should say so.

### Alternatives

- **Mutant schemata as the default**: one build, but it needs a per-language rewrite of expressions (a conditional form, a place to read the mutant id, no use in constant contexts), and one bad mutant breaks the whole build. Not safe from patterns alone. Possible later behind the parser command of problem 2.
- **Per-test coverage selection**: fastest, but each language needs its own collector; ekit would grow a driver per coverage tool.
- **Cap by risk alone**: bounded cost, but a typical PR never reaches `pass`.
- **Several survivors in one suite run**: fewer runs, but mutants can hide each other, so neither a pass nor a fail of the group says anything certain about one mutant.
- **Shared build output across shards (artifact or cache)**: saves 3 clean builds, but build directories are not portable across runners in general. Left to `setup-command`.
- **A middle step: test files that name the changed functions** (text search): cheap to add later if timing shows step 2 dominating.
- **No fallback at all (`n/a` without a tool)**: simplest and honest, but R3 is then missing for every long-tail language.

Tool notes, to check when each is pinned (not verified on real runs here): PIT's `scmMutationCoverage` goal was removed and line-level git filtering is a separate plugin, so plan on changed classes plus ekit's own line filter. Stryker.NET has `since` (changed files, whole files mutated). mull has `-git-diff-ref` and an Elements reporter. Go has no single maintained default (gremlins is pre-1.0; go-mutesting lives in forks): a Go repo may well land on the lexical mutator. universalmutator is prior art for regex mutation of any language; its authors report the same cost this note plans for: mutants that do not compile.

## 2. Patterns versus parsers

### How much it matters

Two of today's three adapters are already lexical (rust and ts: masking, bracket matching, regex). Only python uses a parser. So the step down is not "parser to patterns". It is "500 lines of hand-tuned code per language" to "what a declarative file can say". What that costs, by cheat row:

| Cheat row | Needs from the scanner | Risk with patterns |
|---|---|---|
| Deleted or renamed test | test names | Low where tests are declared by annotation or name (`@Test`, `func TestX`, `[Fact]`, `def test_x`). Medium for generated tests and DSLs. |
| Skipped test | a list of skip markers | Medium: the list is open-ended. Backstop: R4 runs every changed test, and a test that did not run is `none`, a fail. |
| Fewer asserts in a test | the test's span | Low for brace languages. High for indentation and `do … end` languages: no bracket to match. |
| Weakened assert, changed expected value | assert calls and their operands | Medium: custom assert helpers and fluent chains (`assertThat(x).isEqualTo(y)`) each need a pattern. |
| Suppression, mutation skip | comments and annotations | Low. |
| Unparseable file | balance check | Weak by design, as for ts today: the runner reports `build`. |

The larger risk is the masking step, not the regexes. String syntax a generic lexer cannot express (heredocs, C++ raw strings, C# and Swift raw and interpolated strings, Ruby regex literals) shifts every span after it in the file. The rule for that case is fail-closed: a file whose masked text does not balance is an R2 `fail` (cannot be checked), as an unparseable python file is today. Because the cause may be the adapter and not the PR, its class is `needs-human`.

So: for brace languages with declared tests (Java, C#, Go, Kotlin, PHP, Swift, C and C++ with a test macro) patterns give what the rust and ts adapters give today. For Ruby, Elixir, Haskell-like layouts and DSL-heavy test styles they do not.

### Recommendation

**Structured patterns by default, plus one optional parser command with a fixed JSON contract.**

- Patterns are not raw regex over a file. The adapter gives a lexer table (comment forms, string forms, block style: `braces`, `indent` or `keywords`) and call shapes (`assertEquals(a, b)`: kind `eq`, operands 0 and 1; `expect(a).toBe(b)`: a chain). The core keeps its own masking, bracket matching and argument splitting. ci-doctor fills in tables; it does not write a scanner.
- `[scan] command` is optional. Contract: the file's text on stdin, the path as an argument, facts as JSON on stdout (the adapter interface of `stack.py`, serialized). One file per call, no network, no project config read. The core validates the JSON against its schema; output that does not validate is a failed run.
- The command comes from the base branch's adapter, like everything else in it. It reads PR files as data and must never load code or config from the PR (a parser that reads `tsconfig`, a build file or plugins is not allowed in `guard`).
- A declared command that cannot run, or prints invalid output, means `guard` has no usable result: one `CI` entry, as for a crashed job today. Not `n/a` (R2 is the hard guard and `n/a` does not block), and no silent fall back to patterns (two scanners would give two sets of entry ids).
- "python3 stdlib only" holds: the core gains `subprocess` and a JSON check. The parser is the adopter's tool, installed in `guard` at a pinned version by a step the adapter names. `guard` then has a toolchain for that repo, but still runs no PR code.

Why: the fact contract is the one stable seam. The same proof (problem 3) judges patterns and parser alike, so a parser is not trusted more for being a parser. Languages the lexer table cannot describe get a route that is not "R2 is weak here".

Is the cheat-proof step enough? Not alone. It shows the adapter is not blind to one instance of each cheat. It does not measure how many tests or asserts the adapter misses in the repo's real files. Problem 3 adds that.

### Alternatives

- **Patterns only, forever**: simplest; indentation and keyword-block languages stay weak or unsupported.
- **Parser required for every language**: strongest scan; every adopter installs a toolchain in `guard`, and most do not need it.
- **tree-sitter built into the core**: breaks "stdlib only" (a compiled dependency and one grammar per language).
- **Parser adds findings on top of patterns**: no single source of facts; the same test found twice under two names.
- **Raw regex in the adapter**: most freedom for ci-doctor, least reviewable, and each adapter re-solves masking.

## 3. A weak adapter that passes the proof

### What a weak adapter looks like, and what catches it

| Weakness | Caught by | When |
|---|---|---|
| Misses tests (pattern too narrow) | **Census**: every test the runner lists must be found by the scanner, over the whole repo. The proof report shows `found/listed` and names the misses. | setup, each proof run |
| | Per PR: the same count on the changed test files. A mismatch is a `needs-human` entry: the adapter is behind the code. | `red-first` |
| Misses a skip idiom | Runner control: a skipped test must read `none`. R4 already fails a changed test that did not run. | proof, every PR |
| Misses assert forms | **Assert density**: the proof report lists tests with no recognized assert. Above a threshold (proposed 10%) the proof fails until a person accepts the list. | setup, each proof run |
| Reports `pass` when nothing ran | Runner controls: five fixture tests must read `pass`, `fail`, `none` (skipped), `build` (does not compile), `none` (no such test). Core rule kept: `pass` needs a counted passed test. | proof |
| Flags everything (passes every cheat trivially) | **Negative controls**: a rename with the same asserts, reordered asserts, asserts moved into a called helper must give no entry. | proof |
| Right on fixtures, wrong on real files | Census and density run on the repo's own tests. R2 on an empty diff of every test file must give no entry. The count of files whose masked text does not balance is shown. | setup, each proof run |
| R3 wiring wrong | A fixture with a weak assert must give a MISSED mutant; the strong version must give none. | proof |
| The author wrote cheats it knew it would catch | Cheats that are mechanical (delete, comment out, rename a test) are made by the core. The rest are written by a second agent that sees the language and the test framework, not the adapter: the taster pattern ekit already uses. | setup |
| Adapter weakened later | Protected path (`needs-human`), read from base, and the proof runs on the PR's adapter: a cheat caught on base and not at head is a fail. | every adapter PR |

What nothing here catches: a person who merges the setup PR without reading the proof report. The report is therefore numbers and named misses in the PR body, not a green tick.

### Recommendation

**The proof is a deterministic check (`R0`) that CI re-runs. Its inputs are frozen files; no model is involved.**

- **Fixtures** live in `.ekit/proof/`: one small test file and one small production file of the repo's language, with a before and an after version per cheat. They are new files copied into a throwaway worktree at paths the adapter names. They are never patches against real files, so they do not rot when the repo changes. They do go stale when the toolchain or test framework changes, which is the thing to detect.
- **Static half** (git and the adapter only: every R2 cheat, the negative controls, the empty-diff check): in `guard`, on every PR. Seconds.
- **Runtime half** (runner controls, census, density, the R3 control): in `red-first` and `mutants`, when the **fingerprint** is new. Fingerprint: hash of the adapter, the fixtures, the ekit version, and the version lines of the toolchain commands the adapter names (`java -version`, the test framework's version). A passed fingerprint is remembered in the workflow cache; a miss only means the proof runs again. Estimated 1 to 3 min, plus one small R3 run.
- **A PR that changes the adapter or the fixtures**: both halves run on the PR's version, in their own steps, and the result is in the comment for the person who decides. R1 to R4 on that PR still use the base's adapter. The R2 `needs-human` entry for the protected path stays; the proof is the evidence for waiving it.
- **Result**: `R0` is a new check value (the contract allows adding one). A failed proof is one `fail` entry, class `needs-human`: an agent never edits the adapter to get green. The checks that depend on the failed half are `n/a`, with the cause in the note, so a broken adapter is never read as a pass. A person can waive the `R0` entry to land an urgent PR; the adapter fix is its own PR.
- **First setup PR**: the base has no adapter, so R1 to R4 are `n/a` there and `R0` runs on the PR's adapter. The person merges on the proof report.

Why re-run: the toolchain changes without any PR to the adapter (a runner image update, a test framework bump in a lockfile, an ekit release behind the `v0` tag). The runner's output format is what the outcome patterns read, so that is where an adapter breaks silently. The static half is nearly free. The runtime half is paid only when something it depends on moved.

### Alternatives

- **Proof at setup only**: no CI cost; a toolchain bump can turn every R1 result wrong with nothing to show it.
- **Full proof on every PR**: simplest rule; 1 to 3 min and a small R3 run on each PR for a result that almost never changes.
- **A committed lock file instead of the cache**: visible in review, but each toolchain bump then needs a protected-path PR before the note goes away.
- **A scheduled weekly proof on the default branch**: finds drift between PRs, but the fingerprint check finds it at the next PR anyway.
- **Count tests on base and head with the runner** (a fall in passed or a rise in skipped without an R2 entry): catches skips made in config files, which no scanner sees; costs one more suite run on the base. Worth its own decision, see below.

## Open questions for the owner

1. **"Fast" as a number.** The recommended fallback is about 6 to 7 min per shard on the model PR, against 11 to 17 min for the rejected idea and about 6 min in total for a real tool. Is that under the bar, or should a language with no tool start at `n/a` until timing from real repos says otherwise?
2. **`max-mutants` default** (proposed 40) and whether it is a workflow input next to `mutation-budget` or an adapter key only. In the adapter it is protected; as an input it is easier to tune.
3. **Untested versus MISSED at the budget.** This note counts a mutant that survived the PR's tests but did not reach its whole-suite run as untested (`partial`). The python path keeps such a mutant MISSED, because mutmut had already judged it against its own test selection. Confirm the difference is wanted.
4. **A toolchain in `guard`.** The parser command puts a pinned parser install into the one job that today needs only git. Acceptable for repos that opt in, or should the parser run in a separate job whose facts `guard` reads as an artifact (more moving parts, same trust)?
5. **Parser failure as a `CI` entry.** It blocks until a re-run works and cannot be waived. The alternative is `n/a`, which does not block and would let a PR merge without R2 on a bad day.
6. **`R0` waivable?** This note says yes, by a person, so an adapter fix can land while the base's adapter is broken. The stricter choice is not waivable, with the fix PR exempted by rule.
7. **Thresholds.** Census must be 100% or list each exception for the person; assert density proposed at 10% of tests with no recognized assert. Both are guesses until a few real repos are measured.
8. **Base-versus-head test count** as a new check for skips made outside test files (build config, runner config). It needs a suite run on the base in a job that runs PR code. In scope for the language-free core, or a separate proposal?
9. **Report formats in the core.** Three mutation report readers and three coverage readers are proposed. Each is small and stdlib-only, but each is surface to maintain. Start with fewer (mutation-testing-elements and lcov only)?
10. **Cheat list versions.** When an ekit release adds a cheat to the neutral list, existing repos have no fixture for it. Proposed: `R0` names it `unproven` and the summary cannot read `all pass` until the fixture is added. Or hold new cheats to a major version.
