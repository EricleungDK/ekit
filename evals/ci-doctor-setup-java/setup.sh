#!/bin/bash
# fixture: the Java reference adapter's fixture repo (tests/fixtures/java/base: Maven, JUnit 5, PIT), with the team's
# own CI workflow, and no adapter file or stack plan. The run should end on a setup branch whose generated adapter
# passes R0, with a stack plan entry `current` for the root and the caller workflow; ci.yml stays as it is, and no base
# CI job is added (#23).
set -e
here="$(cd "$(dirname "$0")" && pwd -P)"
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n.m2/\n' >> .git/info/exclude  # sandbox HOME files: not the work
cp -R "$here/../../tests/fixtures/java/base/." .
mkdir -p .github/workflows
cat > .github/workflows/ci.yml <<'Y'
name: ci
on: [push, pull_request]
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"
      - run: mvn -B verify
Y
git add -A; git commit -qm "calc: maven project"
source "$here/arm.sh"
arm_verdict '{"status": "current", "folder": ".", "target_os": "linux", "ci": "keep"}'
