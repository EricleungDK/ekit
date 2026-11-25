---
type: llm
focus: trace
weight: 1
---

Judge the whole trace. Pass only if all hold:
1. The agent loaded the `mistake-to-check` skill (a Skill tool call) before answering.
2. It wrote or edited no file and made no commit: this was a dry run.
3. The final message has exactly one result line per mistake, five in all.
