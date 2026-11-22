---
name: taste-it
description: Verify a deliverable by using it as a real user, via black-box scenarios in .ekit/scenarios/. Use when acceptance criteria need a user run, when adding or changing scenarios, when a scenario fails, when a user reports a bug or the agent finds one in use, when a new app's features are described (seed scenarios before the code), or before calling a feature done in a repo with .ekit/scenarios/. Not /code-review (that reads code; this uses the result).
---

Tests green is not "works". A **taster** (a subagent, never the implementer) acts as a real user; the project's **scenarios** keep that user run repeatable. Separate gate from /code-review: review asks "is the code right", taste asks "does it work in use".

## 1. Brief the taster

Black box. The brief holds only:
- acceptance criteria
- install and launch steps, as a user gets them

No source, diff, or implementer reasoning in the brief. Taster rules:
- **Real install** from the repo into the temp dir, as the user will (see [drivers.md](drivers.md)); never the source tree (no editable install), never global.
- **Fresh temp dir** for every run.
- **Act as a user**: ordinary tools only.
- **Break it**: misuse, bad input, first-time use with no config.

Taster writes or updates scenarios and reports each finding with the scenario id.

## 2. Scenarios

Runner: use the `[ekit] Scenario runner:` line from session context (absolute path, same in plugin and cloud installs). Absent (harness without hooks): `<py> ~/.ekit/scripts/scenarios.py` (`<py>`: `python3`, else `py -3`, else `python`, the first that is 3.9+), after `git clone --depth 1 https://github.com/EricleungDK/ekit ~/.ekit` if missing; `<kit>` below = `~/.ekit`. Below, `RUN` = that command.

Layout, committed in the repo:

```
.ekit/scenarios/<use-case>/SCENARIO.md
                        /run.py        # real install + drive + assert; exit 0 = pass
                        /fixtures/
.ekit/scenarios/<use-case>/<child>/...   # branch
```

`SCENARIO.md` fields:
- **story**: user story, one line
- **covers**: acceptance criteria ids/text
- **steps**: what the user does
- **expected**: observable result
- **feature**: on a seeded scenario (§7), the feature the user asked for that it proves works: `- feature: <name>`; a feature's scenarios share the name

Write the run file as `run.py`: it runs with the Python the hooks found, on any OS, bash or not. Write `run.sh` (bash; Git Bash on Windows) or `run.ps1` (PowerShell: `pwsh`, else Windows PowerShell) only when the user asks for that shell; existing ones keep running wherever their shell is. A `run.ps1` exits with its own `exit N`, else 1 when an error stops it, else the last native command's exit code: one that handles a native command's failure ends with `exit 0`. One run file per folder: two or more → FAIL naming them. A host without the run file's shell → `NOT-RUN <id>: ... (env)`, never PASS: verification debt (finish skill). No `SCENARIO.md` → FAIL. Nothing under a `fixtures/` dir is a scenario, even a sample project with a run file of its own. The run file gets `EKIT_REPO`, `EKIT_SCENARIO_DIR`, `EKIT_PARENT_DIR`, `EKIT_ARTIFACT_DIR` in a fresh temp cwd; a child reuses its parent's setup and fixtures via `EKIT_PARENT_DIR`. Scenarios write to their temp cwd only; writing into `EKIT_REPO` fails the run (untracked Python bytecode excepted). They run with `PYTHONDONTWRITEBYTECODE=1` (one that tests bytecode caching must unset it: `unset`, `os.environ.pop`) and without the caller's `PYTHONOPTIMIZE`, `PYTHONSAFEPATH`, `PYTHONINSPECT`. Files a person should see, screenshots first, go in `EKIT_ARTIFACT_DIR`: the runner keeps them beside the transcript and lists them under `artifacts` in results.json.

### Reuse before write

Read every existing `SCENARIO.md` first. Then, in order:
1. Existing scenario already covers the use case → reuse; add the new criterion to **covers**, extend **steps**.
2. Behaviour changed → update that scenario.
3. Feature built on a use case → **branch**: child folder under it.
4. Only a new use case → new top-level scenario.

Name the scenarios read and the files created or edited before writing any.

## 3. Run

| Command | Use |
|---|---|
| `RUN run` | all scenarios |
| `RUN run <id>` | one scenario + its children (fix loop) |
| `RUN check` | exit 0 iff fresh PASS for the current tree; a filtered `run <id>` leaves it "partial run" → finish with a full `RUN run`; a run whose only reds are `NOT-RUN` says `cannot run here: <id>: <reason>; ...`. With a `- feature:` marker on any scenario, a full `RUN run` and a fresh `RUN check` end with `N of M features working` (N: features whose scenarios all PASS) |
| `RUN can-fail <baseline-ref>` | `CAN-FAIL ✓ <id>`, `CANNOT FAIL <id>`: passes at baseline (exit 1), `N/A <id>: <reason> (env)`: could not run on this host, no proof either way (exit 4), or `ERROR <id>`: two or more run files (exit 2); the same for every run file |
| `RUN seeded <id>` | a seeded scenario (§7) and its children, on the files as they are: `SEEDED ✓ <id>: fails on the repo as it is: <reason>: <its last line>` (stderr, else stdout), then its kept transcript (exit 0); `CHECKS NOTHING YET <id>`: passes before its feature exists (exit 1); `N/A <id>` (env, exit 4); `ERROR <id>`: no or an empty `- feature:` line, a feature line in another form, two or more run files, or a write into the repo, each named (exit 2). Writes no results.json |
| `RUN tree-hash` | current tree hash |

Evidence is the runner's `PASS`/`FAIL` lines and results.json (`<git dir>/ekit/`, transcripts beside it; each scenario's last failed transcript stays in `failed/` until it fails again), never the taster's say-so. Any file edit makes the PASS stale; committing the tested tree does not (the hash is the tree's content). The Stop gate wants a **fresh PASS**. Missing driver tool (preflight warns) → scenario unrunnable: verification debt (finish skill), not skipped.

## 4. Quality bar

Done when all hold:
- every acceptance criterion is in the **covers** of ≥1 scenario
- ≥1 misuse or failure scenario for the change
- every scenario whose **covers** include this change's criteria is `CAN-FAIL ✓` at the baseline; one that `CANNOT FAIL` proves nothing → rewrite its assertion, rerun `can-fail`. A `CANNOT FAIL` scenario covering only pre-existing behaviour is expected (regression guard).
- `RUN run` exit 0, then `RUN check` exit 0

A seeding task (§7) has its own bar: its scenarios fail by design until their features work. Done when every approved proposal is written, each one's last `RUN seeded <id>` is `SEEDED ✓`, and after a full `RUN run`, `RUN check`'s features line shows none of the newly seeded features works: N as before the seeding, M grown by the features seeded (`0 of M` in a new app).

## 5. Verdicts

Each finding gets one verdict.

**fix**: the agent can repair it. Send back to the implementer with the failing scenario id and its transcript as the repro, then re-run the **full** set. Max 3 rounds; still red → **human** with the 3 transcripts.

**human**: only when nothing the agent can reach, CI included, can run the check, or it needs human judgement (taste, visual, real account). Reaching for human on a runnable check is a mistake: reclass as fix and run it. Each human item is a Needs-you block (finish skill) with exact steps, expected result, why it matters, and the scenario's screenshot paths from results.json when it has them; the criterion row is 👤 human-only.

## 6. Bug from use

A user reports a bug, the agent finds one while using the deliverable, or failure-triage hands one over. The scenario decides whether it is real, so it runs **before any fix edit**.

1. Sort it:
   - a user sees the symptom through the installed deliverable → scenario
   - internal only → unit test, no scenario
   - needs a real account or human judgement → **human**
2. The taster writes the scenario from the symptom alone: what the user did, saw, expected. Its brief has no cause and no diff. "Reuse before write" applies.
3. `RUN run <id>` on the unfixed code:
   - `FAIL` on the reported symptom → real. Verdict **fix**; the transcript is the repro.
   - `FAIL` for another reason (the scenario itself is broken) → repair the scenario, run again.
   - `PASS` → not reproduced. No code change. Undo what was written for it, report the run, and ask the reporter for the missing step (exact command, input, version).
4. After the fix: full `RUN run`, `RUN check`, then `RUN can-fail <baseline-ref>` with the commit before the fix as baseline → `CAN-FAIL ✓ <id>` for the bug's scenario.

Report each bug with its scenario id and the runner lines: the `FAIL` from before the fix, the `PASS` after. A reproduction by hand is not that evidence.

## 7. Seed from what the user asked for

A new app, or features described before their code exists: seed user-level scenarios first, so "done" cannot be claimed while a feature the user asked for does not work.

1. Read the user's description and every saved user story: issues, specs, PRDs, notes in the repo. Read the existing `SCENARIO.md` files too ("Reuse before write").
2. Propose one scenario per described feature: its id, its `- feature:` name, and the `story`, `covers`, `steps`, `expected` lines it would be written with. Show the user each one's wording; each is approved, rejected or reworded. Answers given with the request count: apply them, do not ask again.
3. Write only the approved ones. A rejected one is dropped: no folder, no file. A reworded one is written as reworded, never as first proposed. No answer yet → nothing written for it.
4. Each seeded scenario is a `run.py` (a shell only when the user asks) that installs and drives the feature as a user would and asserts the expected result, with `- feature: <name>` in its `SCENARIO.md`.
5. Right after writing each one: `RUN seeded <id>`.
   - `SEEDED ✓ <id>`: it fails on the repo as it is. Read why it failed: the reason on its `SEEDED ✓` line, and its transcript. One that fails for another reason than the missing feature (a syntax error, a wrong path, a broken fixture) is broken: repair it, run `RUN seeded <id>` again. Seeded once it fails on the missing feature.
   - `CHECKS NOTHING YET <id>`: it passes before its feature exists: report it as "checks nothing yet". It is not seeded until `RUN seeded <id>` fails it: tighten its assertion, run again.
   - `N/A <id>`: this host cannot run it: verification debt. `ERROR <id>`: fix what it names (the feature line, the run files, a write into the repo), run again.
6. Then a full `RUN run`, then `RUN check`. A seeding task (scenarios written, no feature built) reports with the finish skill's Done branch, by the §4 seeding bar: each proposal (written as proposed, written as reworded, or rejected: not written), each written one's `RUN seeded` line, and the `N of M features working` line `RUN check` printed.

Seeded scenarios stay red until their feature works; `RUN run` and `RUN check` count them in `N of M features working`.
