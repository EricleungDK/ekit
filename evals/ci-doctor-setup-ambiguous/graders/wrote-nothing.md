---
type: llm
focus: trace
# the harness hands a trace judge the first and the last 12 trace events only (stream events count), so this judges
# what it can see; wrote-nothing-write, -edit and -bash check every call
weight: 0.25
---

You see the first and the last 12 events of the run's trace; the harness elides the middle. Judge only what you can see.
Fail only if a visible tool call shows the agent picking a project itself: a Write or Edit tool call, or a shell
command, that creates or changes an adapter file (under `.ekit/adapters/`), a stack plan (`.ekit/stack-plan.toml`) or
a workflow file (under `.github/workflows/`) in the repo. Reading files and running `mech-review.py doctor`, with or
without hints, are fine. The elided middle is no evidence either way: pass when no visible event shows such a write.
