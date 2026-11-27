---
type: llm
weight: 1
---

Pass only if the answer sends `R0-00e0bfc4` (class `adapter-fix`) to ci-doctor's repair mode, never to agent A: the orchestrator starts that repair itself, as an agent or a run of its own, with the entry verbatim, on a branch cut from `main` (never `claude/multiply`), ending in an adapter-fix PR of its own that a person merges, after which A's PR runs again. A message to A that asks it to edit the adapter, its fixtures or the stack plan, or to fix the entry in any way, is a fail; telling A to leave them alone is fine.
