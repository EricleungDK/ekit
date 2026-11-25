---
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
runs: 2
---

Retro of the ticket run that merged #74, #75, #76 and #77 in ekit's own repo. It found five agent mistakes; here they are, one per item, each with its evidence. This turn is a dry run: change no file and commit nothing. For each mistake, tell me where its check belongs, or that none is made, and end each item with the one result line you would give back.

1. In #76 a new test proved that the parser gives up on input nested 5000 deep by expecting Python's `RecursionError`; on a runner with a bigger recursion limit it passed without testing anything. The fix (commit `4e1a9c2`) replaced it with an explicit depth limit and a test of that limit. No other test in the repo relies on the recursion limit.
2. In #75 an agent's report quoted mech-review's result for head `a13f00d`; the commit pushed for review was `c7e2b19`, one fix later, never checked. The same happened in #77.
3. In #76 a new engine module, `scripts/mech_review/cochange.py`, was not added to the hand-kept module list in `tests/mech-modules.test.sh`, so its layering was never checked; #74 had left out `merge.py` the same way.
4. In #77 a behaviour change under `scripts/mech_review/` updated neither `CHANGELOG.md` nor `docs/mech-review-ci.md`, though `AGENTS.md` says a behaviour change updates both; #75 did the same.
5. In #74 and #76 tests passed on the agent's Linux machine and failed only in the macOS CI job (`hooks-macos`): BSD `sed` and bash 3.2.
