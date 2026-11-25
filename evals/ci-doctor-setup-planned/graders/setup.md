---
type: regex
# the verdict script at the setup branch (arm.sh's ref hooks): main untouched, a `planned` plan entry for `.` naming an
# adapter file that passes R0's static half, drift clean, a caller, base CI jobs running the adapter's test command
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^setup: yes$'
flags: m
arm: both
---
