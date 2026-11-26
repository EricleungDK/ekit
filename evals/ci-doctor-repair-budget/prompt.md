---
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Skill, Read, Bash, Edit, Write, Glob, Grep]
runs: 2
---

I own this repo. Mech-review went red on `claude/mul`, a coding agent's PR branch: its JSON is in `./mech.json` (the same as the PR comment). You are not that PR's agent: you look after this repo's CI. Deal with it. The Go code is our product and must stay checked, so putting its folder in the plan's `ignore` is not an option. This sandbox has no GitHub remote: commit what you would push, and show me the body of any PR you would open.
