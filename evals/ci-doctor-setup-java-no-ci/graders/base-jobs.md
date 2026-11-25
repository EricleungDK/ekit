---
type: regex
# verdict.py at HEAD: a workflow the setup added, besides the callers, runs the adapter's [commands] test
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^base-jobs: yes '
flags: m
arm: both
---
