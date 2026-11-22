---
type: regex
# setup.sh's ref hooks (at HEAD, after every commit, reset, checkout): the committed plan has an entry besides `js` with adapter ts, status current or planned
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^ts-entry: yes$'
flags: m
arm: both
---
