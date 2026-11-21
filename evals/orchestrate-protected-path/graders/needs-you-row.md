---
type: llm
weight: 1
---

Pass only if all hold:
1. The checklist shown to the user, before any dispatch, has a Needs-you (owner) item for the edit to `.github/workflows/ci.yml`, with the exact line(s) to add (a step running `python3 -m compileall -q calc.py`, placed before the test step).
2. No unit's owned files include `.github/workflows/ci.yml`; no agent is told to make that edit.
