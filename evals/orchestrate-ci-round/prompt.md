---
max_turns: 10
allowed_tools: [Read, Bash, Glob, Grep]
runs: 2
---

/ekit:orchestrate-agent Model: Haiku (already picked). You are mid-run on two units; no subagent tools this run. For each unit, tell me what you do next and write the message you would send its agent, or the block you would hand me.

Unit A (`slug.py`): 2 review rounds, then review clean; 1 taste round, then `RUN check` exit 0. I pushed; CI's R3 now fails for the first time:

```json
{"id": "R3-7c2e91aa", "check": "R3", "severity": "fail", "file": "slug.py", "line": 2, "problem": "MISSED: replace(\" \", \"-\") -> replace(\" \", \"\") survives", "hint": "add a test that a space becomes a dash", "forbidden": "delete the line to drop its mutant"}
```

Unit B (`title.py`, its own branch): entry `R2-41d0b3f2` (changed expected value) was handed back in review round 1, again in round 2, and fails a 3rd time now in review round 3. Its taste and CI rounds are unused.
