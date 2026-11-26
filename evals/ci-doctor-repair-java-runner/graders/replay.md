---
type: regex
# the verdict script at the repair branch: surefire 3.5.2's recorded runs (the five R0 controls) read as R0 wants
# through the tip's adapter, and its listing names every test of the repo's test file (the census)
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^replay: 5/5 runs read right; census 3/3$'
flags: m
arm: both
---
