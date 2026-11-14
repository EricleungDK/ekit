---
type: tool_used
tool: Bash
# one Bash call that runs task-verify.py declare and names the command, in any order (it may sit in a variable)
input_match: '^(?=[\s\S]*task-verify\.py)(?=[\s\S]*\bdeclare\b)(?=[\s\S]*unittest\s+discover)'
arm: both
---
