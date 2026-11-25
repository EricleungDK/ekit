---
type: regex
# verdict.py at HEAD (arm.sh's ref hooks): a setup branch, main untouched, a plan entry for `.` naming an adapter file,
# status current, target OS linux, R0 (static half) pass, drift clean, a caller, ci.yml unchanged, no base CI job
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^setup: yes$'
flags: m
arm: both
---
