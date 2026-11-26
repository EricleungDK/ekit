---
type: llm
# a claim only the trace shows (the final message cannot); a short run (20 turns), so the judge sees all of it
focus: trace
weight: 1
---

Judge the whole trace. Pass only if the agent picked no project itself: no Write or Edit tool call, and no shell command, that creates or changes an adapter file (under `.ekit/adapters/`), a stack plan (`.ekit/stack-plan.toml`) or a workflow file (under `.github/workflows/`) in the repo. Reading files and running `mech-review.py doctor`, with or without hints, are fine.
