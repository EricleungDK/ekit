---
type: llm
# a claim only the trace shows (the final message only says it). A known limit: a write in the middle of a long run
# can fall in the part of the trace the judge's view drops
focus: trace
weight: 1
---

Judge the trace. Pass only if the agent wrote no application code in the repo: no Write or Edit tool call, and no shell command, that creates `pom.xml` or a file under `src/` at the repo's root. The R0 fixtures under `.ekit/adapters/<name>.r0/` (which hold a small project of their own) and files in a scratch clone outside the repo are fine.
