---
type: regex
target: files
pattern: '\.ekit/scenarios/(?!(?:add-task|list-tasks|finish-task)/)[^/\s]+/SCENARIO\.md'
match: not_contains
arm: both
---
