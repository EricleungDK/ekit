---
type: regex
target: files
pattern: '(^|/)\.ekit/scenarios/[^/\n]+/(?!fixtures/)[^/\n]+/'
flags: m
match: not_contains
arm: both
---
