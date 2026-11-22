---
type: regex
# setup.sh's post-commit hook: the kit's drift check on HEAD exits 0, check D pass, no entry (no uncovered manifest)
target: {source: file, path: .git/ekit-eval-verdict.txt}
pattern: '^drift: clean '
flags: m
arm: both
---
