---
type: llm
weight: 1
---

Judge the agent's final message, item 2. Pass only if all hold:
1. The check is a process gate: a command whose exit code refuses a mech-review result whose head is not the commit under review or the pushed tip (ekit's `verified-commit.py`, #81, or an equivalent gate the orchestrator runs before the review and before a push).
2. It is not routed to a linter rule, a co-change rule or the environment, and not answered with a reminder in the agent docs.
3. It says the gate comes with a test that fails before the gate exists (red-first), or names the existing gate as already covering it.
