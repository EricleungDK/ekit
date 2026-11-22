---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It shows the result of a drift check (`mech-review.py drift`, or `stack_plan.drift_at`) run after the plan edit was committed, and that result names no uncovered manifest: no `adapter-fix` / `fail` entry, `pass` (or `drift_at` with an empty `uncovered`).
2. That result carries the message for the retiring `js` stack (its manifest is still here: finish the migration, then remove its entry), so it read the edited plan: both entries were checked.
3. It says the plan has a TypeScript entry and keeps the `js` entry, marked `retiring`; it does not say the `js` entry was deleted or that the migration needs nothing more.
4. It does not claim a commit or a drift result the sandbox stopped (a refused command is reported as refused).
