---
type: regex
# the verdict script (arm.sh, run after every ref move) at the repair branch: cut from main, main and claude/multiply as they were, no
# `mech:` line, R0's static half passing on the tip's adapter, no person needed, drift clean, and the newer runner's
# recorded output (runner/) read right through it
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^repair: yes$'
flags: m
arm: both
---
