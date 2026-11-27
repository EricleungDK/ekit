# Adding a language

mech-review ships three built-in stacks: Rust, Python and TypeScript/JavaScript. Any other language the format can
describe ([what it can describe today](#before-you-start)) gets the same PR checks through an **adapter file**: a
TOML file in your repo that describes the language's tests, asserts, skips, lint suppressions, test runner and
mutation tool. `/ekit:ci-doctor` writes it for your repo, proves it against a list of cheats, and opens a setup PR
that you merge.

This guide follows one repo from install to merged setup PR, then covers what comes after: the stack plan, the
editing rules, a failed proof and its repair, and fixing the adapter by hand. It links to the
[CI doc](mech-review-ci.md) for every detail. The example is a Java repo built with Maven and tested with JUnit 5.
Other languages go the same way.

| Word | Meaning |
|---|---|
| **R0** | The adapter's proof, run as a check: the adapter must catch a fixed list of cheats and find every test the runner lists ([R0 adapter proof](mech-review-ci.md#r0-adapter-proof)). R1 to R4 are in [README § Words used here](../README.md#words-used-here) |
| **drift check** | Check `D`: every manifest (`pom.xml`, `package.json`, ...) in the repo must be covered by a stack plan entry ([Stack plan](mech-review-ci.md#stack-plan)) |
| **`needs-human`** | An entry class: a `fail` only a person settles, by a waiver or by their own PR |
| **`adapter-fix`** | An entry class: the adapter file or the stack plan needs a change, in a PR of its own, never by the PR's own agent |
| **target OS** | The OS of the CI runner that runs your tests (`linux`, `macos`, `windows`), not your own computer's ([target OS](#target-os)) |
| **The kit's Java adapter** | `tests/fixtures/adapters/maven.toml`, a Java adapter ci-doctor's setup mode generated for ekit's Java fixture repo, kept as a test fixture of ekit's, not a built-in. ci-doctor writes yours from your repo and must not copy this one ([the kit's Java adapter](mech-review-ci.md#the-kits-java-adapter)) |

## The short version

1. Install ekit ([README § Install](../README.md#install)) and start a session in your repo.
2. Run `/ekit:ci-doctor`. It detects the project, writes and proves an adapter, and opens a setup PR. If the proof
   does not pass within its budget, it opens no PR and reports what failed ([when setup stops](#when-setup-stops)).
3. Read the PR's proof report and check the points in [before you merge](#before-you-merge). The PR's own mech-review
   check cannot pass yet ([why](#the-setup-prs-own-check)).
4. Merge. From the next PR on, every PR is checked (in an empty repo, from the PR that adds the first manifest), and
   `mech-review report` can become a required check.

## Before you start

- **Python 3.11 or newer** where ci-doctor runs: the Python the `[ekit] Python:` session line names. Adapter files and
  the stack plan are TOML, and reading TOML needs 3.11: on an older Python, proving an adapter (`--adapter`) is a
  usage error that says so, and `doctor` on a repo that already has an adapter file or a plan names it too
  ([Adapter file](mech-review-ci.md#adapter-file)). The plugin's launcher tries `python3`, then `py -3`, then
  `python`, and takes the first that is 3.9+ ([README § Setup per OS](../README.md#setup-per-os)); it never looks for
  `python3.11` by name. So check `python3 --version` (`py -3 --version` on Windows). If it is older than 3.11, make a
  3.11+ the first `python3` on `PATH` before you start the session: an activated venv made from a 3.11+ works.
- **A GitHub remote you can push to, and a way to open the PR** (the `gh` CLI, or your harness's GitHub tools).
  Without them ci-doctor stops before the PR, and its report hands you the caller YAML and the PR body to open it
  yourself.
- **The language's toolchain**, if you have it (a JDK and Maven for the example). Without it, the proof's runtime half
  does not run on your machine, and the PR body says so. Your developer machine's setup per OS (Python, Git, the
  optional tools) is in [README § Setup per OS](../README.md#setup-per-os), from
  [#34](https://github.com/EricleungDK/ekit/issues/34). It is not repeated here.
- **What the format can describe today.** Braced languages whose tests are calls (`test("name", fn)`) or functions
  with a marker before them (JUnit's `@Test void adds()`). Tests declared by their name alone (Go's
  `func TestX(t *testing.T)`) or by a bracketed attribute (C#'s `[Fact]`) cannot be described yet. Neither can an
  indentation-based language, short of a parser command. See [Fixed, not configurable](mech-review-ci.md#fixed-not-configurable)
  and [Parser](mech-review-ci.md#parser). For such a language, setup ends with a report and no PR, not with a weak
  adapter.

## What `/ekit:ci-doctor` does

The steps are the skill's ([`skills/ci-doctor/setup.md`](../skills/ci-doctor/setup.md)). The mechanics are in the CI
doc's [Setup mode](mech-review-ci.md#setup-mode).

1. **Detection.** `mech-review.py doctor` reads the repo and reports `mode: setup` for a project no adapter covers,
   with its folder, manifests, language, build tool, test framework and target OS, and the team's own CI workflows
   (`own_ci`). For the example: `pom.xml`, `java`, `maven`, `junit5`, `linux`. When the repo holds several projects at
   the same depth (a Java backend beside a TS frontend), ci-doctor asks which one you mean. In an empty repo it asks
   what the repo will hold, and you name it ("a Java API built with Maven").
2. **Cheat list.** Before any adapter exists, a second agent that never sees the adapter lists every way a PR in your
   language can skip a test or hide a mutant. It writes the proof's fixtures in your repo's own style (for Java: a
   composed `@Disabled`, `assumeTrue`, `@Nested`, a file-activated Maven profile, `@SuppressWarnings`).
3. **Adapter file.** `.ekit/adapters/<name>.toml` (here, say, `java.toml`), written from how your repo writes
   its tests. Its fixtures go beside it in `.ekit/adapters/<name>.r0/`. [What it holds](#the-adapter-file).
4. **Target OS.** Taken from detection ([target OS](#target-os)). It becomes the adapter's `target-os`.
5. **Proof.** R0's static half, a census of your repo's own tests, the runtime half where the toolchain is installed,
   and the cheat list. The budget is 5 rounds of one adapter revision and one run of the proof.
6. **Stack plan.** One entry in `.ekit/stack-plan.toml`: `current` when the manifest is there, `planned` in an empty
   repo ([the stack plan](#the-stack-plan)).
7. **CI files.** The mech-review caller (`.github/workflows/mech-review.yml`, `stack` left at `auto`), the waiver
   re-run caller (`.github/workflows/mech-waive.yml`) and, only when the repo has no CI of its own, base CI jobs in a
   new `.github/workflows/<name>-base-ci.yml`. A workflow already there is never edited.
8. **Recheck and PR.** It commits on a new branch, proves the committed files the way CI reads them (`r0` and
   `drift`), pushes, and opens the setup PR with the proof report in its body.

ci-doctor asks you for `protected-paths` beyond `.github/**` and for any agent branch prefix outside the default list.
Those are your decisions.

### When setup stops

If the proof does not pass in 5 rounds, ci-doctor commits nothing and opens no PR. Its report names each failed case,
each cheat the adapter missed, where the draft is, and what would unblock it. A cheat the proof cannot catch is
accepted only when the CI doc names it as a limit of the format, or when you accept it under
`## Limits (owner decides)` in the PR body. Any other uncaught cheat is a miss.

## The setup PR

### Reading the proof report

The PR body has these parts ([setup.md step 8](../skills/ci-doctor/setup.md)):

| Part | Reads | What it proves |
|---|---|---|
| Static half | `N of N cases` | Each cheat (a deleted, skipped or renamed test, a changed expected value, a weakened assert, a suppression with no reason) gives its R2 entry, and the honest controls give none. [R0 adapter proof](mech-review-ci.md#r0-adapter-proof) |
| Census | `N of N tests` | Each test in your repo's test files is found by the adapter. This ties the adapter to your tests, not only to the fixtures |
| Runtime half | a result, or `not run here: <why>` | The adapter reads the real runner: every test the runner lists is found, the control tests read `pass`, `fail`, skipped, build failure and no such test, and the mutation tool finds a weak assert. [Runtime half](mech-review-ci.md#runtime-half) |
| Cheat list | each item caught, or a limit | Each language-specific cheat from step 2: caught by an R0 case or an `r2` run, or a limit the CI doc names (quoted) |
| `## Limits (owner decides)` | present only when needed | Cheats the proof cannot catch that the CI doc does not name. You accept or reject each before merging |

The body also quotes doctor's summary at the setup branch's head. It reads `fail <sha> (1 problems)`, mode `repair`,
with one `confirm` entry,
`` `java` in . is checked through the repo's adapter file: doctor trial-runs the built-in stacks only ``.
That is expected: doctor does not trial an adapter file, and the proof report stands in for its trial.

### Before you merge

- Every count is full: `17 of 17`, not `16 of 17`. A missing count is a gap, not a pass.
- The census count matches the number of tests you know your repo has.
- `not run here` for the runtime half: in CI, its `run` part (the census and the runner controls, in `red-first`) runs
  on the first PR after the merge, and its `r3` part (the mutation tool control, in `mutants`) on the first PR that
  changes production code. Each result is in that PR's comment (`R0:` line). Read both once.
- Each item under `## Limits (owner decides)`: you either accept it, or you ask for another round.
- The adapter names your real commands in `[commands]` ([the commands](#the-commands-each-adapter-names)), and its
  `target-os` is right.
- The stack plan entry names the right folder.
- The caller's `test-paths` covers your test folder: `src/test/**` for a Maven project at the repo root, which matches
  only there; `**/src/test/**` for a multi-module build. Add `.ekit/scenarios/**` if you have scenarios.
- The caller's `setup-command` provides what the runner lacks for your tests, by the rules in
  [the commands](#the-commands-each-adapter-names): nothing in mech-review's jobs runs the adapter's `install` command.
- If the adapter runs PIT, as the kit's Java adapter does: your pom declares the PIT plugin with
  `pitest-junit5-plugin`, which PIT needs to run JUnit 5 tests. **The proof does not cover this**: R0's mutation
  control runs on the fixture project's own pom, so it passes even when your pom lacks the plugin, and R3 on a later
  PR then fails with `pit ran and wrote no report`. If it is missing, add it in the setup PR, with the PIT version the
  adapter pins, or a version of your own when it pins none (the kit's Java adapter runs the pom's: its fixture pom
  declares `pitest-maven` 1.17.4 and `pitest-junit5-plugin` 1.2.1), under `<build><plugins>`:

  ```xml
  <plugin>
    <groupId>org.pitest</groupId>
    <artifactId>pitest-maven</artifactId>
    <version>1.17.4</version>
    <dependencies>
      <dependency>
        <groupId>org.pitest</groupId>
        <artifactId>pitest-junit5-plugin</artifactId>
        <version>1.2.1</version>
      </dependency>
    </dependencies>
  </plugin>
  ```

  In the setup PR this needs no waiver: no check runs there yet. After the merge, `[mutation] config_files` lists
  `pom.xml`, so every later pom edit is an R2 `needs-human` entry a person settles. That is by design: a pom can switch
  mutators off.
- If base CI jobs were added and they ran on the PR, they are green: that shows the adapter's commands work on the
  runner.

### The setup PR's own check

On the setup PR itself, mech-review cannot run your stack yet. The checks read the plan and the adapter from the base
branch, and the base has neither. So the `stack` job finds no project at the base, and the comment reads:

```
**no result** for head `<sha>`

reason: stack auto, base: no project found (no pyproject.toml, setup.py, setup.cfg, Cargo.toml, package.json); set the stack and project-dir inputs in the mech-review caller
```

The check is red, and that is expected. Ignore the hint at the end and keep `stack` at `auto`: an explicit
`stack: java` reads `stack java: want auto, python, rust or ts` at that base. A no-result comment is not an entry, so
there is nothing to waive. Merge on the proof report. Require `mech-review report` in branch protection only after the
merge, once the checks run (in an empty repo, once the first manifest has landed: see [an empty repo](#an-empty-repo)).
This is a [known gap](#known-gaps).

## The commands each adapter names

`[commands]` in the adapter file holds four shell commands, each required (`""` means the stack has none). ci-doctor
generates them from your repo's own toolchain, so read yours in the adapter. As an example only, the kit's Java
adapter's, quoted (its fixture repo has no lint step, and `mvn` fetches what it needs):

```toml
[commands]
install = ""
build = "mvn -B -ntp test-compile"
lint = ""
test = "mvn -B -ntp test"
```

- **`test`** is the one the engine runs. R1 and R4 start each one-test run from it, with the adapter's `[run]` words
  after it. [Run side](mech-review-ci.md#run-side-r1-and-r4).
- **`install`, `build`, `lint`** are never run by the engine. The base CI jobs ci-doctor writes run all four in order
  (install, build, lint, test) on the target OS's runner.
- **In mech-review's own jobs**, the reusable workflow sets up toolchains for the built-ins only, and nothing runs the
  adapter's `install`. Whatever your tests need beyond the runner image goes into the caller's `setup-command`
  ([Inputs](mech-review-ci.md#inputs)). The workflow runs it with bash as a step of its own in `red-first` and
  `mutants`, at the workspace root, before the tests; your repo is checked out in `caller/` there. Two rules follow:
  - A command that needs your project runs in it: `cd caller && ...`.
  - An `export` ends with the step. An env value or a `PATH` entry for the test steps goes through GitHub's files:
    `echo "NAME=value" >> "$GITHUB_ENV"`, `echo "<dir>" >> "$GITHUB_PATH"`. They apply from the next step on, so a
    command later in the same `setup-command` that needs them exports them too.

  A plain Maven repo may need nothing, since `mvn test` fetches its own dependencies. The reusable workflow takes no
  extra steps from the caller, so `actions/setup-java` cannot run inside it; use it in your own base CI file instead.
  Inside mech-review, pick a JDK the runner image ships: GitHub's images set `JAVA_HOME_<version>_X64` for each one
  (`JAVA_HOME_21_X64`; the image's README lists them). A repo that needs JDK 21 and a prefetch would set:

  ```yaml
      with:
        setup-command: |
          echo "JAVA_HOME=$JAVA_HOME_21_X64" >> "$GITHUB_ENV"
          echo "$JAVA_HOME_21_X64/bin" >> "$GITHUB_PATH"
          export JAVA_HOME="$JAVA_HOME_21_X64" PATH="$JAVA_HOME_21_X64/bin:$PATH"
          cd caller && mvn -B -ntp dependency:go-offline
  ```

  The variables expand when bash runs the command on the runner. Your existing workflows show what the tests need.
- **In your agent sessions**, the adapter's lint and test commands are the natural verify command to agree on: under
  `/ekit:orchestrate-agent` you agree one per unit in the checklist, for example the adapter's lint and test joined
  with `&&` (the test command alone where lint is `""`, as in the kit's Java adapter). Nothing copies them for you:
  give them when the checklist is agreed.

## Target OS

- **How ci-doctor infers it.** `windows` for a WPF app (`<UseWPF>true</UseWPF>`, the WPF project type, or a
  `PresentationFramework` reference in a .NET project), `macos` for an Xcode project or a `Package.swift` that names an
  iOS platform, else `linux`. `doctor` names the file that decided it (`target_os_why`). A Java repo is `linux`.
- **Where it goes.** The adapter's `target-os`, and the plan entry's when it is not `linux`.
- **Which jobs move.** Only the jobs that run your tests: `red-first`, `baseline` and `mutants`, on `windows-latest` or
  `macos-latest`. `stack`, `guard`, `plan`, `shards` and `report` stay on `ubuntu-latest`. Off Linux,
  `extra-apt-packages` is skipped. The base CI job runs on the target OS's runner too.
- **What else follows it.** R0's runtime half runs only on the target OS (elsewhere `n/a`, named), and a declared
  mutation tool must list that OS (`[mutation.tool] os`).
- **Changing it** needs a person ([editing rules](#editing-rules)).
- **Your own machine** is a separate matter: the per-OS setup for the plugin (Python, Git, the optional tools) is in
  [#34](https://github.com/EricleungDK/ekit/issues/34) and [README § Setup per OS](../README.md#setup-per-os).

Details: [Setup mode § Target OS](mech-review-ci.md#setup-mode) and [Stack plan § Target OS](mech-review-ci.md#stack-plan).

## The stack plan

`.ekit/stack-plan.toml` lists the repo's stacks: each one's name, folder, adapter (a built-in or an adapter file's
path), status (`planned`, `current` or `retiring`) and optional `target-os`. Format and rules:
[Stack plan](mech-review-ci.md#stack-plan).

- **It replaces detection.** With a plan on the base branch, `stack: auto` takes the stacks from the plan and detects
  nothing ([Stack resolution](mech-review-ci.md#stack-resolution)). Keep `stack` at `auto` in the caller. A plan with
  several stacks runs one set of checks per stack, reported as one comment and one check
  ([Several stacks](mech-review-ci.md#several-stacks)).
- **The drift check** (check `D`) runs on every PR whose checks run, once a plan exists. It fails a PR whose manifest
  (`pom.xml`, `package.json`, ...) no entry covers, and adds notes (`Stack plan:` lines) for planned, retiring and gone stacks. The same check runs at
  session start: a `[ekit] Stack plan drift at HEAD` line when something is off, nothing when clean.
- **Who edits it.** You or ci-doctor, as part of the work that changes the repo's stacks. No person is needed for
  each edit ([editing rules](#editing-rules)). A PR's own agent never edits it to get its PR past `D`.
- **The plan lands first.** A PR is judged by the base branch's plan. So a PR that adds a manifest and its entry
  together fails `D`. Add the entry in a PR of its own, with no manifest, then the code. A PR that edits only the plan
  is judged by its own plan, so it passes.

The messages quoted in the four situations below are the drift check's own.

### An empty repo

A planned stack, dormant until its manifest appears. Setup writes the adapter and an entry with `status = "planned"`.
R0's fixtures stand alone, so the adapter is proven on day one.

```toml
[[stack]]
name = "api"
folder = "."
adapter = ".ekit/adapters/java.toml"
status = "planned"
```

Dormant means no check runs, and the check is red. Until a manifest is there, every PR's mech-review comment reads
**no result**, with the reason `stack auto: the stack plan has no stack to run (no current, retiring or planned stack
whose manifest is here); set the stack and project-dir inputs in the mech-review caller`. Ignore that hint and keep
`stack` at `auto`. An explicit `stack: java` does resolve to `java` on this plan, but it pins the caller to that one
stack: once the plan has two stacks, the explicit stack checks only the one it names and drops the other. Do not make
the check required yet ([known gaps](#known-gaps)). The PR that adds `pom.xml` starts the checks, and drift tells you
the next step:

```
message: planned stack `api` (.): its manifest pom.xml is here and its adapter `.ekit/adapters/java.toml` is proven, so its checks start: set its status to current
```

### A migration

The old stack is marked retiring. Maven to Gradle in the same folder: one PR, with no new manifest, adds the new stack's
adapter and entry (`planned` until its manifest is there) and sets the old entry to `retiring`. One folder may hold
both entries.

```toml
[[stack]]
name = "api"
folder = "."
adapter = ".ekit/adapters/java.toml"
status = "retiring"

[[stack]]
name = "api-gradle"
folder = "."
adapter = ".ekit/adapters/gradle.toml"
status = "planned"
```

While `pom.xml` is there the old stack is still checked; the new one starts when its manifest lands. Drift notes
``retiring stack `api` (.): its manifest pom.xml is still here: finish the migration, then remove its entry``. After 30
days the note adds a reminder. When the PR that deletes `pom.xml` lands, the note becomes
``stack `api` (.): no pom.xml in . any more: remove the entry `api` from .ekit/stack-plan.toml``. Remove the entry
once the old code is gone and you agree the migration is done. The new entry needs a person only if it changes the
target OS, loosens a limit or changes the mutation tool against the old one ([editing rules](#editing-rules)). To get
the new adapter, run `/ekit:ci-doctor` and name the stack to come ("we are moving to Gradle"); ask it to generate and
prove that adapter as for a planned stack, and to edit the plan as its [Stack plan](../skills/ci-doctor/SKILL.md#stack-plan) section says.

### Adding a stack

A TS frontend in `web/` beside the Java backend: first a PR that adds the entry and no manifest, with
`status = "planned"` and `adapter = "ts"` (a built-in), then the code. For a language with no built-in, that first PR
also adds the adapter file and its fixtures, which ci-doctor's setup mode writes and proves. The code PR starts the stack's checks, and drift asks you to set it `current`. Added together, the PR
fails `D`:

```
fail D-7e776699 .ekit/stack-plan.toml:0 manifests no stack in .ekit/stack-plan.toml covers: web/package.json
```

That `D` entry is of class `adapter-fix`: ci-doctor's repair mode writes the entry on a branch cut from the base
branch, and the PR's agent does not touch it ([when R0 fails](#when-r0-fails-the-fixing-round)). A folder of samples
or templates goes in `ignore` instead.

### A swap before any code

The plan says Maven, the team picks Gradle, and no code exists yet. Ask ci-doctor for the new stack, as for an empty
repo, and have it replace the planned entry's adapter and delete the old adapter file and its fixtures in the same PR.
Nothing runs on that PR, as on every PR before the first manifest. Run R0's editing rules locally instead, naming the
base plan's stack:

```bash
$MR r0 --repo . --base origin/main --head HEAD --stack java --project-dir .
```

(`$MR` as in [fixing it by hand](#fixing-it-by-hand).) It calls the swap a person's call:
`fail R0-… .ekit/adapters/java.toml:0 a person decides: adapter file .ekit/adapters/java.toml: [mutation.tool] changed`.
Deleting the old adapter file counts as removing its mutation tool, even when the new file declares the same tool,
and a different tool or target OS in the new file counts too ([known gaps](#known-gaps)). You are that person: review
the swap and merge it.

To avoid the entry, keep the old adapter file in the swap PR and delete it in a later PR. Both PRs need no person when
the new file declares the same mutation tool and target OS: the same `r0` run reads `pass` for each.

## Editing rules

Editing an adapter file or the stack plan needs no person each time. R0 judges the adapter and the drift check judges
the plan. Note when R0 judges an edit: on the PR that makes it, CI proves the base branch's copy, so the edited copy
is judged by the proof you or ci-doctor run before the PR ([fixing it by hand](#fixing-it-by-hand)), and by R0 on every
PR after it merges. Only these need a person: one R0 `fail` entry of class `needs-human` names each, and it blocks no other
check ([R0 adapter proof § Editing rules](mech-review-ci.md#r0-adapter-proof)):

- a looser limit: an adapter's `[limits]` (`max-mutants`, `mutation-budget` or `census` lower, `assert-density`
  higher), or a caller's `max-mutants` or `mutation-budget` input lower;
- a changed target OS (the CI runner's OS), in a plan entry or an adapter file;
- a folder added to the plan's `ignore` list;
- a test accepted with no recognised assert (a name added to `.ekit/r0-accepted.json`);
- a changed mutation tool (`[mutation.tool]` added, removed or edited);
- a changed `[parser]` command: R0 does not run it until a person reviews it ([Parser](mech-review-ci.md#parser)).

**Several entries in one folder.** Each new or changed plan entry is compared with its **twin**: the base entry with
the same folder and adapter. A new entry in a folder that already has entries (a second stack beside the first, or
the new stack of a migration) has no twin, so it is compared against every base entry of that folder, and needs a
person only if it changes the target OS, loosens a limit or changes the mutation tool. So a migration (the old stack
`retiring`, the new one `current`) needs a person only in those three cases. An entry in a folder new to the plan is
compared with the defaults (linux, the default limits, no declared mutation tool): it needs no person when it keeps
them, and one when its target OS is not linux or its adapter declares a mutation tool.

**Named limit: an unproven adapter needs no person.** Swapping a proven adapter for one with unproven cases, or
editing a fixture so that a case turns `unproven`, gives no `needs-human` entry today. After the merge, R0 on later
PRs reads `unproven`, which exits 0 and blocks nothing, so those PRs are checked by an adapter nobody proved. Read
`unproven` in the comment's `R0:` line as a gap to close, and run the proof yourself before merging such a change
([fixing it by hand](#fixing-it-by-hand)). It is a [known gap](#known-gaps), for the head-proof follow-up.

Separately, every edit under `.github/**` (the callers, the base CI jobs) is a protected-path `needs-human` entry.
If the adapter lists the mutation tool's config files (the kit's Java adapter lists `pom.xml`), an edit to one is an R2
`needs-human` entry too. A person settles these with `/mech-waive <id> <reason>` ([Waivers](mech-review-ci.md#waivers)).

## When R0 fails: the fixing round

**R0** is the adapter's proof, run as a CI check. Its static half runs in `guard` on every PR, in seconds. Its runtime
half has two parts, each cached per PR: its `run` part runs in `red-first` once on every new PR, and its `r3` part in
`mutants` on a PR's first run that changes production code (R3 runs only then). Each runs again on that
PR when its fingerprint changes (the adapter, its fixtures, the ekit version, the target OS, the toolchain's version
lines, among others). It is mechanical: frozen inputs, no model.

**When it fails**, most often: a toolchain or test-framework upgrade changes the runner's output; the repo adopts a new
test style or assert library, so the census stops matching; or a new ekit release adds a cheat your fixtures lack,
which reads `unproven` (not a fail, but never `all pass`). A failed case is one `fail` entry of class `adapter-fix`.
The checks that read tests through the adapter are then `n/a` (`blocked: R0 failed`), and their entries stay and
still count.

**The fixing round** is ci-doctor's repair mode ([`skills/ci-doctor/repair.md`](../skills/ci-doctor/repair.md),
[Repair mode](mech-review-ci.md#repair-mode)). The PR's own agent never edits the adapter: an agent that can tune its
checker can tune it until its own PR passes. Under `/ekit:orchestrate-agent`, the orchestrator starts the repair
itself. Otherwise run `/ekit:ci-doctor` and give it the entry.

1. It cuts a branch from the PR's base branch (never the PR's), regenerates only the failing part (for a runtime case,
   from the runner's real output), and proves the edited copy as setup does, plus the PR merged onto the fix.
2. If the edit hits an editing rule, it stops before the PR and asks you.
3. It opens an adapter-fix PR against the base branch with the proof report in its body.
4. **That PR's own CI reads the same R0 fail until it merges**, because in CI, R0 proves the base branch's copy of the
   adapter, not the PR's. Read the proof in the body, waive that PR's R0 entry (`/mech-waive <id> <reason>`), and
   merge. This holds until a follow-up issue changes it.
5. The original PR picks up the fixed adapter on its next run: a push, or close and reopen it. Re-running an old run
   keeps its old base.

A drift repair (the `D` entry) edits only the plan, adds no manifest, and passes `D` in its own CI. Out of budget, the
repair opens no PR and reports what failed: the entry then needs a person.

**Waiving instead** is the emergency exit, for an urgent PR while the repair is pending: `/mech-waive` on the PR's
`R0` (or `D`) entry. Each `fail` entry of a blocked check still needs its own waiver, so waiving R0 alone never turns
the run `pass`. A `CI` entry cannot be waived.

## The adapter file

One TOML file per stack: [Adapter file](mech-review-ci.md#adapter-file) is the format, key by key.

| Part | Holds | Used by |
|---|---|---|
| `name`, `extensions`, `manifests`, `target-os` | the stack's name, its files, the files that mark its project, its OS ([Keys](mech-review-ci.md#keys)) | resolution, drift |
| `[lexer]` | comments, strings and brackets, so code in a comment or string never counts | R2 |
| `[tests]`, `[functions]` | how a test is declared and named, skip and focus markers ([Declared tests](mech-review-ci.md#declared-tests)) | R2 |
| `[[asserts.call]]`, `[[asserts.chain]]` | assert shapes, which operand is the expected value | R2 |
| `[[suppressions]]` | lint directives and where their reason goes | R2 |
| `[mutation]`, `[mutation.tool]` | what hides code from R3, the tool's config files, the mutation tool and its report ([R3 side](mech-review-ci.md#r3-side-mutation-tool)) | R2, R3 |
| `[limits]` | the stack's check limits | R0's editing rules |
| `[commands]`, `[run]`, `[run.list]`, `[run.outcome]` | the four commands, running one test by name, listing every test, reading a run's result ([Run side](mech-review-ci.md#run-side-r1-and-r4)) | R1, R4, R0's runtime half |
| `[parser]` | instead of the pattern tables: one command that prints a file's facts as JSON ([Parser](mech-review-ci.md#parser)) | R2 |

Its fixtures sit beside it in `.ekit/adapters/<name>.r0/` (`runtime/` for the runtime half). The
[Worked example](mech-review-ci.md#worked-example) is a whole file for a made-up language.
[The kit's Java adapter](mech-review-ci.md#the-kits-java-adapter) describes a Java adapter ci-doctor generated (a test
fixture of ekit's, not a built-in), and [Format limits](mech-review-ci.md#format-limits) what no adapter can make the
checks see: composed annotations, `@SuppressWarnings`, assumptions that stop a test from its body, among others.

### Fixing it by hand

You can edit the file yourself, in a PR of its own cut from the base branch. Editing it in the PR it judges changes
nothing for that PR: its checks read the base's copy. Prove the edit before you push, with the commands setup and
repair use. `<kit>` is the folder above `scripts/` in the `[ekit] Scenario runner:` line at session start, or
`~/.ekit`:

```bash
MR="python3 -I <kit>/scripts/mech-review.py"
# the static half, on the working tree
$MR r0 --repo . --base HEAD --head HEAD --stack java --adapter .ekit/adapters/java.toml
# the census: in a scratch clone, delete the test files and commit; every test must be named as removed
$MR r2 --repo <scratch> --base HEAD~1 --head HEAD --stack java --adapter <absolute path of the file> --test-paths 'src/test/**'
# the runtime half, where the toolchain is installed and this machine is the target OS (each --r0 an empty dir)
$MR red --repo . --base HEAD --head HEAD --stack java --adapter .ekit/adapters/java.toml --test-paths 'src/test/**' --head-branch claude/setup --r0 <dir>
$MR mutants --repo . --base HEAD --head HEAD --stack java --adapter .ekit/adapters/java.toml --r0 <dir>
# after committing: the committed files as CI reads them, and the plan
$MR r0 --repo . --base HEAD --head HEAD --stack java --project-dir .
$MR drift --repo . --base HEAD --head HEAD --format text
```

Pass for `r0` is `checks.R0.status` `pass` in the JSON, not the exit code (exit 0 also covers `unproven`). The census
`r2` exits 1 when it works: it names every removed test (`test fn ... removed`), each a `fail` entry, and a test it
does not name is a miss. Some subcommands' `--help` lists `--stack {python,rust,ts}`; `--stack java` still works with
`--adapter`, or when the repo has `.ekit/adapters/java.toml`. Then open the PR and
handle it as an adapter-fix PR: its CI proves the base's copy, so it reads the old result until it merges
([step 4](#when-r0-fails-the-fixing-round)). A change that hits an [editing rule](#editing-rules) is a person's call.

## R3 per language

R3 (mutation on the changed lines) depends on the tool the stack has:

| Stack | R3 |
|---|---|
| Rust, Python, TypeScript/JavaScript | cargo-mutants, mutmut, Stryker, set up by the workflow |
| An adapter file with `[mutation.tool]` | the tool it declares (PIT for Java, Stryker.NET, mull, ...), read from the tool's report. The workflow installs nothing for it: the runner image or your `setup-command` provides it. `max-mutants` is not applied (the tool lists no mutants before its run), and each changed file is one shard, at most 4 |
| An adapter file with no `[mutation.tool]` | `n/a`, named in every summary, never a pass |

There is no mutation for a language with no mutation tool yet: R3 reads `n/a` until ekit's own lexical mutator lands
(a later round). [What each stack mutates](mech-review-ci.md#what-each-stack-mutates) compares the tools, with a column
for a declared tool.

## Known gaps

These are documented behaviour today, with follow-ups to come:

- **The setup PR's own check** reads `no result` and is red, with nothing to waive: the base has no adapter yet
  ([the setup PR's own check](#the-setup-prs-own-check)). Merge on the proof report.
- **A planned-only plan** (an empty repo) makes every PR's check red with `no result` until the first manifest lands
  ([an empty repo](#an-empty-repo)).
- **A swap before code** is flagged `[mutation.tool] changed` even when the new adapter declares the same tool,
  because deleting the old adapter file counts as removing its tool ([a swap before any code](#a-swap-before-any-code)).
- **Named limit: an unproven adapter needs no person.** Swapping a proven adapter for an unproven one, or editing a
  fixture so that a case turns `unproven`, needs no person, and later PRs are then checked by an adapter nobody proved
  (R0 `unproven` exits 0). This belongs to the head-proof follow-up ([editing rules](#editing-rules)).
