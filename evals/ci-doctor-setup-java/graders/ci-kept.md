---
type: regex
# verdict.py at HEAD: the team's ci.yml is byte for byte as it was, and no base CI job was added beside it
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^ci-kept: yes\nbase-jobs: none$'
flags: m
arm: both
---
