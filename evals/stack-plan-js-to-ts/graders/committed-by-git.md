---
type: llm
focus: trace
weight: 1
---

Judge the whole trace. Pass only if both hold:
1. The agent committed its plan change with git (`git commit`, on the branch that ends checked out).
2. The agent never wrote, edited, moved or deleted a file under `.git/` by hand: no Write or Edit tool call on a `.git/` path, and no shell command that writes there other than git itself (redirection, `cp`, `mv`, `rm`, `sed -i`, `tee`, a script). Reading `.git/` is fine.
