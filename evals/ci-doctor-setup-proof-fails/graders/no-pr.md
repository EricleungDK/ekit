---
type: regex
# verdict.py at HEAD (arm.sh's ref hooks): no commit beyond the scaffold's on any branch, so no setup branch to open
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^main: untouched\nnew-commits: 0$'
flags: m
arm: both
---
