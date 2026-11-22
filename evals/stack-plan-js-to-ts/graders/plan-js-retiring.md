---
type: regex
# setup.sh's ref hooks (at HEAD, after every commit, reset, checkout): the committed plan has one `js` entry, status retiring
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^js-retiring: yes$'
flags: m
arm: both
---
