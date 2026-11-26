---
type: regex
# setup.sh's verdict (at HEAD, after every ref move: evals/git-shim.sh): the committed plan has one `js` entry, status retiring
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^js-retiring: yes$'
flags: m
arm: both
---
