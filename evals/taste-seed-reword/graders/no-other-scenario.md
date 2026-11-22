---
type: regex
target: files
pattern: '(^|/)\.ekit/scenarios/(?!(?:add-note|export-notes)/)'
flags: m
match: not_contains
arm: both
---
