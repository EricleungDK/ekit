---
type: llm
# a claim only the trace shows: the order of two steps (setup.md steps 2 and 3). A known limit: the judge's view of a
# long trace drops its middle, which may hold either step
focus: trace
weight: 1
---

Judge the trace. Pass only if the cheat list (the ways Java can skip a test or hide a mutant) was written in a pass of its own before the adapter was drafted: by a second agent, or, with no subagent tool, in a separate step that ends before the first tool call that writes `.ekit/adapters/<name>.toml` (Write, Edit or a shell command). That step reads the repo's test files, never an adapter draft.
