---
type: regex
target: files
pattern: '(^|/)\.ekit/scenarios/(?!(?:add-task|list-tasks|finish-task)/)'
flags: m
match: not_contains
arm: both
---
