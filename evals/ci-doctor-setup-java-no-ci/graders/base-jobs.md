---
type: regex
# the verdict script at the setup branch: a job the setup added (no ekit call, in any workflow file) runs the
# adapter's [commands] test
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^base-jobs: yes '
flags: m
arm: both
---
