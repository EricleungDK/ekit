---
type: regex
# the verdict's `app-code:` line (ci-doctor-setup-java/arm.sh, run after every ref move): no pom.xml or src/ at the
# repo's root in any new commit (any ref, worktree HEAD or reflog) nor in the main checkout's working tree as the last
# verdict saw it. A known limit: a file written and removed again between two ref moves, written after the last one,
# or in a linked worktree's tree, is not seen; the R0 fixtures under .ekit/adapters/<name>.r0/ are not at the root
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^app-code: none$'
flags: m
arm: both
---
