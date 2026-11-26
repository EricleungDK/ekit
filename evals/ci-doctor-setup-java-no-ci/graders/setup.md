---
type: regex
# the verdict script at the setup branch (arm.sh, run after every ref move): as ci-doctor-setup-java's, and a new job (no ekit
# call, in any workflow file) runs the adapter's [commands] test
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^setup: yes$'
flags: m
arm: both
---
