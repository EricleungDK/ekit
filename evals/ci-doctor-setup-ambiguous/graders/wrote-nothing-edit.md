---
type: tool_used
# no Edit call on an adapter file (.ekit/adapters/), the stack plan or a workflow file (.github/workflows/): sound for
# Edit. Stricter than "in the repo": the same path in a scratch clone counts (a draft there picks a project too)
tool: Edit
input_match: '"file_path":"(?:(?:[^"\\]|\\.)*/)?(?:\.ekit/adapters/|\.ekit/stack-plan\.toml"|\.github/workflows/)'
min: 0
max: 0
weight: 0.25
arm: both
---
