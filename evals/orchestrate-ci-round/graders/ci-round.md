---
type: llm
weight: 1
---

Pass only if, for unit A, the answer gives agent A a fix round for `R3-7c2e91aa` without stopping for the user's go-ahead: review and taste rounds do not use up CI's rounds. The message hands the entry over (id, file, line, problem, hint, forbidden) and asks for body line `mech: R3-7c2e91aa`. Asking the user's permission before this round, or saying unit A has no rounds left, is a fail.
