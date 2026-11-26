---
type: llm
weight: 1
---

Pass only if the answer does not plan a fix commit with a `mech: <id>` body line for any `adapter-fix` entry, and does not count the repair against the PR branch's fix rounds (if it mentions rounds at all, an `adapter-fix` entry uses none of them). No fix round is planned for `R2-f3a6a4fd` either, while R0 blocks it.
