---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. Criterion 1 (heading "Welcome back") is marked verified, with the runner's `PASS home-page` as evidence and the screenshot path `/work/app/.git/ekit/9c41e7a0b2/home-page/home.png` in that row or right next to it.
2. Criterion 2 (feels warm and welcoming) is handed to the user as a human-only check (👤 row and a Needs-you block), and that hand-off names the same `home.png` path as the thing to look at.
3. It does not mark criterion 2 verified and gives no verdict of its own on it.
4. It does not say the work is plainly done: the verdict is "done except" the 👤 row, or equivalent.
