#!/bin/bash
# fixture: the kit's Java fixture repo (tests/fixtures/java/base) with no CI at all. As
# ci-doctor-setup-java, and the setup also writes base CI jobs from the adapter's commands, its test command among
# them (#23). The grader support is that case's (arm.sh).
set -e
here="$(cd "$(dirname "$0")" && pwd -P)"
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n.m2/\n' >> .git/info/exclude  # sandbox HOME files: not the work
cp -R "$here/../../tests/fixtures/java/base/." .
git add -A; git commit -qm "calc: maven project"
source "$here/../ci-doctor-setup-java/arm.sh"
arm_verdict '{"status": "current", "folder": ".", "target_os": "linux", "ci": "write",
  "tests": ["CalcTest.adds", "CalcTest.negates", "CalcTest.subtracts"], "test_files": ["src/test"], "test_paths": "src/test/**"}'
