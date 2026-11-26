#!/bin/bash
# fixture: a one-file repo; the prompt carries the run's state (rounds used, CI's mech-review entries: R0's runtime
# half failed for the repo's maven adapter, and an R4 entry R0 blocks, as ci-doctor-repair-java-runner's mech.json has
# them). Nothing to build: the answer routes the adapter-fix entry to ci-doctor's repair mode, never to the unit (#24).
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n__pycache__/\n' >> .git/info/exclude  # sandbox HOME files: not the work, keep the finish gate quiet
printf 'package com.example;\n\npublic final class Calc {\n    public static int mul(int a, int b) {\n        return a * b;\n    }\n}\n' > Calc.java
git add -A; git commit -qm "calc"
