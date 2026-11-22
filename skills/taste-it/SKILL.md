---
name: taste-it
description: Verify a deliverable by using it as a real user, via black-box scenarios in .ekit/scenarios/. Use when acceptance criteria need a user run, when adding or changing scenarios, when a scenario fails, when a user reports a bug or the agent finds one in use, or before calling a feature done in a repo with .ekit/scenarios/. Not /code-review (that reads code; this uses the result).
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

Write the run file as `run.py`: it runs with the Python the hooks found, on any OS, bash or not. Write `run.sh` (bash; Git Bash on Windows) or `run.ps1` (PowerShell: `pwsh`, else Windows PowerShell) only when the user asks for that shell; existing ones keep running wherever their shell is. One run file per folder: two or more → FAIL naming them. A host without the run file's shell → `NOT-RUN <id>: ... (env)`, never PASS: verification debt (finish skill). No `SCENARIO.md` → FAIL. Nothing under a `fixtures/` dir is a scenario, even a sample project with a run file of its own. The run file gets `EKIT_REPO`, `EKIT_SCENARIO_DIR`, `EKIT_PARENT_DIR`, `EKIT_ARTIFACT_DIR` in a fresh temp cwd; a child reuses its parent's setup and fixtures via `EKIT_PARENT_DIR`. Scenarios write to their temp cwd only; writing into `EKIT_REPO` fails the run (untracked Python bytecode excepted). They run with `PYTHONDONTWRITEBYTECODE=1` (one that tests bytecode caching must unset it: `unset`, `os.environ.pop`) and without the caller's `PYTHONOPTIMIZE`, `PYTHONSAFEPATH`, `PYTHONINSPECT`. Files a person should see, screenshots first, go in `EKIT_ARTIFACT_DIR`: the runner keeps them beside the transcript and lists them under `artifacts` in results.json.

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
| `RUN check` | exit 0 iff fresh PASS for the current tree; a filtered `run <id>` leaves it "partial run" → finish with a full `RUN run`; a run whose only reds are `NOT-RUN` says `cannot run here: <id>: <reason>; ...` |
| `RUN can-fail <baseline-ref>` | `CAN-FAIL ✓ <id>`, `CANNOT FAIL <id>`: passes at baseline (exit 1), `N/A <id>: <reason> (env)`: could not run on this host, no proof either way (exit 4), or `ERROR <id>`: two or more run files (exit 2); the same for every run file |
| `RUN tree-hash` | current tree hash |

Evidence is the runner's `PASS`/`FAIL` lines and results.json (`<git dir>/ekit/`, transcripts beside it; each scenario's last failed transcript stays in `failed/` until it fails again), never the taster's say-so. Any file edit makes the PASS stale; committing the tested tree does not (the hash is the tree's content). The Stop gate wants a **fresh PASS**. Missing driver tool (preflight warns) → scenario unrunnable: verification debt (finish skill), not skipped.

## 4. Quality bar

Done when all hold:
- every acceptance criterion is in the **covers** of ≥1 scenario
- ≥1 misuse or failure scenario for the change
- every scenario whose **covers** include this change's criteria is `CAN-FAIL ✓` at the baseline; one that `CANNOT FAIL` proves nothing → rewrite its assertion, rerun `can-fail`. A `CANNOT FAIL` scenario covering only pre-existing behaviour is expected (regression guard).
- `RUN run` exit 0, then `RUN check` exit 0

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
