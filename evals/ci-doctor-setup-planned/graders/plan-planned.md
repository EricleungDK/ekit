---
type: regex
# the verdict script at the setup branch: the stack plan's entry for `.` names an adapter file and is `planned` (no manifest yet)
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^entry: \S+ adapter \S+\.toml status planned$'
flags: m
arm: both
---
