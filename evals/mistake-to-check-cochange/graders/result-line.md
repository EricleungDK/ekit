---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It shows a mech-review result run after the rule was committed in which both of the rule's cases pass (`<id>:flagged` and `<id>:control`, under R0's co-change cases), or it names the refused or failed command that stopped that proof as not verified. It does not claim a proof it did not run.
2. It ends with one `Rule added:` line naming the rule, where it lives and its incident (#12 or its commit).
3. It says the new rule is non-blocking (`confirm`) until promoted, and does not promote it in this change.
