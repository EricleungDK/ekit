---
type: llm
# a claim only the trace shows: where the new pattern came from. The replay grader cannot tell a copied line apart,
# so this one does. A known limit: a read in the middle of a long run can fall in the part of the trace the judge's
# view drops
focus: trace
weight: 1
---

Judge the trace. Pass only if the agent wrote the adapter's new `[run.outcome]` pattern from the runner output it read (`red-first.log`, or a run of the adapter's command of its own), not by copying the kit's reference adapter (`tests/fixtures/adapters/java.toml`): no read of that file's `[run.outcome]` lines followed by the same pattern in the edit.
