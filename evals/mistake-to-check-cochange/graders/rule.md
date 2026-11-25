---
type: llm
focus: trace
weight: 1
---

Judge the whole trace, and the `.ekit/co-change.toml` the agent committed. Pass only if all hold:
1. The check is a co-change rule in `.ekit/co-change.toml` (`format = 1`): `trigger` matches `app/core.py` (for example `app/**`), `require` matches `CHANGELOG.md`.
2. The rule names its incident: `#12`, or the sha of #12's commit (`core: three retries (#12)`).
3. It has both proof cases: `flagged` (the paths of a PR it must flag, such as `app/core.py`) and `control` (a PR it must leave alone, such as `app/core.py` with `CHANGELOG.md`).
4. It has no `severity = "fail"`: a new rule starts at `confirm`.
5. The rule was committed with git. No line was added to `AGENTS.md` as the fix in its place.
