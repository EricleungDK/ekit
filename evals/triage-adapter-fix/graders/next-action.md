---
type: llm
weight: 1
---

Pass only if, for each of the five `adapter-fix` entries, the next action is no edit by the PR's agent on its branch (no adapter, fixture or plan edit there, no moved or renamed manifest), and the fix goes to ci-doctor's repair mode (`/ekit:ci-doctor`), run apart from the PR's agent, on a branch and PR of its own that a person merges, after which the PR runs again. `R2-f3a6a4fd` is marked `blocked: R0`: it gets no fix round now. The answer holds it (listed as open) because R2 read the code through the adapter R0 failed, and says it is read again once the PR runs on the repaired adapter; it never proposes adding a reason after `// NOPMD` or removing it today.
