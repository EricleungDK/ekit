---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It says the proof did not pass after the stated budget of rounds (one adapter revision and one run of the proof each), and how many rounds it ran.
2. It names what failed, as the commands reported it: the R0 cases (cheats or controls, by name, e.g. `delete`, `skip`), the census (tests of `calc_test.go` the adapter does not read), or both; and why the adapter cannot catch them (Go declares a test by its name alone, and skips it from its body; the adapter format cannot describe that yet).
3. It opens no PR and shows no PR body as ready to open; it says the setup stops there, and what would unblock it (a person's decision, or the format supporting the shape).
4. It calls no `unproven` or failing R0 a pass.
