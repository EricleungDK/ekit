---
type: tool_used
# no Edit call on a path under .git/ (its file_path, in the call's JSON): sound for Edit
tool: Edit
input_match: '"file_path":"(?:(?:[^"\\]|\\.)*/)?\.git(?:/|")'
min: 0
max: 0
weight: 0.25
arm: both
---
