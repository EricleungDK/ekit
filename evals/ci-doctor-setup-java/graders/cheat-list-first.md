---
type: llm
focus: trace
# the order of two steps (setup.md steps 2 and 3). The harness hands a trace judge the first and the last 12 trace
# events only (stream events count), so this one rarely sees either step: a near-constant pass. No mechanical check is
# sound: the runs write the fixtures and the adapter with shell commands, often in one call, so tool_order cannot
# order them
weight: 1
---

You see the first and the last 12 events of the run's trace; the harness elides the middle. Judge only what you can see.
Fail only if what you can see shows the adapter drafted before the cheat list: a tool call that writes
`.ekit/adapters/<name>.toml` (Write, Edit or a shell command) before the cheat list (the ways Java can skip a test or
hide a mutant) was written in a pass of its own (by a second agent, or in a separate step that reads the repo's test
files, never an adapter draft), or a cheat list written from an adapter draft. The elided middle is no evidence either
way: pass when no visible event shows the wrong order.
