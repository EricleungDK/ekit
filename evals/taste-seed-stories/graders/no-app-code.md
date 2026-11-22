---
type: regex
target: files
pattern: '^(?!(?:[^\n]*/)?\.(?:ekit|git)/)[^\n]*\.py$'
flags: m
match: not_contains
arm: both
---
