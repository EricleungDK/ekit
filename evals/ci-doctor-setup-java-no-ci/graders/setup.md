---
type: regex
# verdict.py at HEAD (arm.sh's ref hooks): as ci-doctor-setup-java's, and a new workflow (not a caller) runs the
# adapter's [commands] test
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^setup: yes$'
flags: m
arm: both
---
