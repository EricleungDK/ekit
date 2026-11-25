---
type: regex
# the verdict script at the setup branch: with the repo's test files deleted on a scratch commit, R2 through the
# committed adapter names every one of the repo's tests removed (the adapter reads the tests the repo has)
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^census: (\d+)/\1 of the repo''s tests read$'
flags: m
arm: both
---
