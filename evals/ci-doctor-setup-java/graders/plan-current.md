---
type: regex
# verdict.py at HEAD: the stack plan's entry for `.` names an adapter file and is `current` (the manifest is there)
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^entry: \S+ adapter \S+\.toml status current$'
flags: m
arm: both
---
