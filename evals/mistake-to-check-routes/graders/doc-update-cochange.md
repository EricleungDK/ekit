---
type: llm
weight: 1
---

Judge the agent's final message, item 4. Pass only if all hold:
1. The check is a co-change rule (`.ekit/co-change.toml`): a change under `scripts/mech_review/` (the trigger) requires a change to `CHANGELOG.md` or `docs/mech-review-ci.md` (the required paths).
2. The rule names its incident (#77, #75 or a commit of theirs) and has its two proof cases: one PR it must flag and one control it must leave alone.
3. The rule starts at `confirm` (non-blocking): no `severity = "fail"` for a new rule.
4. Its result line is a `Rule added:` line naming the rule.
