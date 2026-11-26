---
type: regex
# the verdict script at the repair branch: web/ gets a plan entry whose adapter lists package.json, or its folder in
# `ignore` (the entry's status is the criteria's: `planned`)
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^plan: (covers web \(entry \S+ adapter \S+ status \S+\)|ignores web \(.*\))$'
flags: m
arm: both
---
