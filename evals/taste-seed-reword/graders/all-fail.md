---
type: regex
target: {source: file, path: .git/ekit/results.json}
pattern: '"exit": 0\b'
match: not_contains
arm: both
---
