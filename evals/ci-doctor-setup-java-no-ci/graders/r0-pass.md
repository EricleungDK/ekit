---
type: regex
# the verdict script at the setup branch: the adapter the plan names passes R0's static half (every cheat and control, none unproven)
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^r0: pass '
flags: m
arm: both
---
