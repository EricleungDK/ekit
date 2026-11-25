---
type: llm
weight: 1
---

Judge the agent's final message, item 5. Pass only if all hold:
1. No rule is made: it is an environment difference (the developer machine is not the macOS runner), so the fix is in the environment, and the macOS CI job (`hooks-macos`) is the check that already covers it.
2. It proposes no linter rule, co-change rule or gate over the diff for it, and no local simulation of macOS.
3. Its result line is a `No check:` line naming the environment, or an `Environment fix:` line.
