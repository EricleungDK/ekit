#!/bin/bash
# fixture: an empty repo (a README only) whose user says "a Java API". The run should end on a setup branch with a
# `planned` stack plan entry for the root naming an adapter file that passes R0 (its fixtures are standalone: no app
# code needed), the caller and base CI jobs (the repo has none) (#23). The grader support is ci-doctor-setup-java's.
set -e
here="$(cd "$(dirname "$0")" && pwd -P)"
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n.m2/\n' >> .git/info/exclude  # sandbox HOME files: not the work
printf '# orders\n\nThe orders API.\n' > README.md
git add -A; git commit -qm "readme"
source "$here/../ci-doctor-setup-java/arm.sh"
arm_verdict '{"status": "planned", "folder": ".", "target_os": "linux", "ci": "write"}'
