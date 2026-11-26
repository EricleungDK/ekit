---
type: llm
weight: 1
---

Pass only if, for each of the five `adapter-fix` entries, the next action is no edit by the PR's agent on its branch (no adapter, fixture or plan edit there, no moved or renamed manifest), and the fix goes to ci-doctor's repair mode (`/ekit:ci-doctor`), run apart from the PR's agent, on a branch and PR of its own that a person merges, after which the PR runs again. `R2-0734ae9c` is marked `blocked: R0`: it gets no fix round now. The answer holds it (listed as open) because R2 read the code through the adapter R0 failed, and says it is read again, and triaged from that run, once the PR runs on the repaired adapter. It plans no fix for it, now or for later: no `Fix:` plan for it, and no conditional one ("if it still fails, add a reason after `// NOPMD`" or "remove it").
