---
type: regex
# #24: a repair round is no fix round of the coding branch. The verdict script: claude/web is where it was, the
# work is new commits on a branch cut from main (none of the coding branch's commits in it), and no new commit on any
# ref carries a `mech:` body line (the line failure-triage counts rounds by)
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^coding: untouched \(claude/web\)\nnew-commits: [1-9]\d*\nmech-lines: 0\ncut-from-base: yes$'
flags: m
arm: both
---
