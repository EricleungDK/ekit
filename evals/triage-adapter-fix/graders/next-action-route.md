---
type: llm
# split from next-action (with next-action-held): the routing of the five entries, so a FAIL names its clause
weight: 0.5
---

Pass only if, for each of the five `adapter-fix` entries, the next action is no edit by the PR's agent on its branch (no adapter, fixture or plan edit there, no moved or renamed manifest), and the fix goes to ci-doctor's repair mode (`/ekit:ci-doctor`), run apart from the PR's agent, on a branch and PR of its own that a person merges, after which the PR runs again.
