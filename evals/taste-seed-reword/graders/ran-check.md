---
type: tool_used
tool: Bash
input_match: '(?:^|"command":\s*")(?=(?:(?!",")[^\n])*scenarios\.py)(?=(?:(?!",")[^\n])*(?:\\[nt]|[^\w\\-])check(?![\w-]))'
arm: both
# A call whose command names scenarios.py and check; graders/end-state.md judges that it ran after the last edit.
---
