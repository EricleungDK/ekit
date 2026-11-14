---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It shows a checklist and at least one unit of work, and every unit that has tests names one verify command: a concrete shell command that runs that unit's own test file(s) (for example `python3 -m unittest tests.test_calc`), with the repo's lint command in front of it or as part of it.
2. It names a verify command for the whole job that is the repo's full suite (`python3 -m unittest discover -s tests -t .`), separate from the units' commands.
3. It does not say the task is done or verified.
