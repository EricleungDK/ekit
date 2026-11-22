---
type: regex
# setup.sh's ref hooks (at HEAD, after every commit, reset, checkout): a TS entry, `js` retiring and the kit's drift
# check clean (exit 0, D pass, no entry), all three in the one end state
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^migrated: yes$'
flags: m
arm: both
---
