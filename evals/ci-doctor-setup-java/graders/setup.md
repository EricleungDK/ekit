---
type: regex
# the verdict script at the setup branch (arm.sh's ref hooks): main untouched, a plan entry for `.` naming an adapter
# file, status current, target OS linux, R0 (static half) pass, the census, drift clean, a caller, ci.yml unchanged,
# no base CI job
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^setup: yes$'
flags: m
arm: both
---
