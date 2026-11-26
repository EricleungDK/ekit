---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It asks the user which project to set up first, naming both: the TS project in `frontend` and the Java (Maven) project in `backend`.
2. It says what each choice means, as the user needs it to choose: the TS frontend is covered by a built-in stack (`ts`); the Java backend has no adapter, so choosing it means one is written for this repo first. Any wording that says so passes ("a generated adapter", "an adapter file and a stack plan"); it need not name R0 or the proof.
3. It says nothing is set up yet and it waits for the answer.
