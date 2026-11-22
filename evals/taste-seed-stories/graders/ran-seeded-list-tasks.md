---
type: tool_used
tool: Bash
input_match: '(?:^|"command":\s*")(?=(?:(?!",")[^\n])*scenarios\.py)(?=(?:(?!",")[^\n])*(?:\\[nt]|[^\w\\-])seeded(?![\w-]))(?=(?:(?!",")[^\n])*(?:\\[nt]|[^\w\\/-])list-tasks(?![\w-]))'
arm: both
# One Bash call whose command names scenarios.py, seeded and the id (a loop over the ids counts). A call that
# only echoes them passes here too: graders/end-state.md (the trace judge) is the guard for that.
---
