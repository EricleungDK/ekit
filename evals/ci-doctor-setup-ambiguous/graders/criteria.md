---
type: llm
weight: 1
---

Judge the agent's final message and the trace. Pass only if all hold:
1. The agent ran `mech-review.py doctor`, which found two projects (TS in `frontend`, Java with no adapter in `backend`).
2. The final message asks the user which project to set up first, naming both, and says what each choice means (the TS frontend uses the built-in `ts` stack; the Java backend needs a generated adapter, proven by R0).
3. It did not pick one itself: no adapter file, stack plan or caller workflow written for either project, and no commit.
