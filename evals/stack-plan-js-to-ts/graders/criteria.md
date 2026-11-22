---
type: llm
weight: 1
---

Judge the transcript and the agent's final message. Pass only if all hold:
1. The last drift check the agent ran (`mech-review.py drift`, or `stack_plan.drift_at`) ran after the plan edit was committed, and its output shown in the transcript names no uncovered manifest: no `adapter-fix` / `fail` entry, check `D` `pass` (or `drift_at` with an empty `uncovered`).
2. That output carries the message for the retiring `js` stack (its manifest is still here: finish the migration, then remove its entry), so it read the edited plan: both entries were checked.
3. The plan kept the `js` entry, marked `retiring`, beside a TypeScript entry; the agent did not delete the `js` entry or claim the migration needs nothing more.
4. The final message tells the user the drift check is clean and that `js` stays `retiring` until the migration is finished.
