---
type: regex
# the verdict script at the repair branch: web/ gets a plan entry whose adapter lists package.json, `planned` (its
# manifest lands with claude/web) or `current` (drift judges either clean), or its folder in `ignore`
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^plan: (covers web \(entry \S+ adapter \S+ status (planned|current)\)|ignores web \(.*\))$'
flags: m
arm: both
---
