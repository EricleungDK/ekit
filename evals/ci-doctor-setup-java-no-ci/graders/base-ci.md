---
type: regex
# the verdict's `base-ci:` line at the setup branch (ci-doctor-setup-java/arm.sh, run after every ref move): the one job
# the setup added beside the callers runs the adapter's [commands] in order (install, build, lint, test, an empty one
# left out) on the target OS's runner (ubuntu-latest), with no step but those, checkout and toolchain setup actions
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^base-ci: yes '
flags: m
arm: both
---
