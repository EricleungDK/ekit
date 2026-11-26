---
max_turns: 10
allowed_tools: [Read, Bash, Glob, Grep]
runs: 2
---

/ekit:orchestrate-agent Model: Haiku (already picked). You are mid-run on one unit; no subagent tools this run. Tell me what you do next: write the message you would send its agent, the brief or command that starts anything else, and the block you would hand me, if any. Then give the unit's fix rounds left per source.

Unit A (`Calc.java`, branch `claude/multiply`, base `main`): 1 review round, then review clean; taste clean on the first run. Rounds used: review 1, taste 0, CI 0. I pushed; CI's mech-review now fails with these entries:

```json
{"id": "R0-00e0bfc4", "check": "R0", "class": "adapter-fix", "severity": "fail", "file": ".ekit/adapters/maven.toml", "line": 0, "problem": "R0 runtime half (run) failed for the `maven` adapter: control `pass` read error: [INFO] Scanning for projects... (want pass); control `fail` read error: [INFO] Scanning for projects... (want fail); control `skipped` read error: [INFO] Scanning for projects... (want none); control `no-such-test` read error: [INFO] Scanning for projects... (want none)", "hint": "repair the adapter (ci-doctor repair mode) in a PR of its own, then re-run R0; the PR under review never edits its own checker", "forbidden": "tuning the adapter or its fixtures until this PR passes"}
{"id": "R4-3f0be0be", "check": "R4", "class": "agent-fixable", "severity": "fail", "file": "src/test/java/com/example/CalcTest.java", "line": 27, "problem": "test `CalcTest.multiplies` cannot run at head: [INFO] Scanning for projects...", "hint": "fix the test setup (manifest, flags); the toolchain did not reach a test result", "forbidden": "a check that did not run", "blocked": "R0"}
```
