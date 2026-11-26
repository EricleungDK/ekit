---
type: regex
# the verdict's `by-git:` line (after every ref move: evals/git-shim.sh): the setup branch (main untouched and the branch choice: setup.md), and git moved
# it to its tip: the tip is the newest entry of the branch's own reflog (a ref written by hand leaves none)
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^by-git: yes$'
flags: m
arm: both
---
