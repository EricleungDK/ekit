---
type: tool_used
# no Write call on a path under .git/ (its file_path, in the call's JSON): sound for Write
tool: Write
input_match: '"file_path":"(?:(?:[^"\\]|\\.)*/)?\.git(?:/|")'
min: 0
max: 0
weight: 0.25
arm: both
---
