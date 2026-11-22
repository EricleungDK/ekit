---
type: regex
target: files
pattern: '\.ekit/scenarios/(?!(?:add-note|export-notes)/)[^/\s]+/SCENARIO\.md'
match: not_contains
arm: both
---
