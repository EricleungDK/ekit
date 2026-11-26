---
type: regex
# the verdict script (ci-doctor-repair-java-runner/arm.sh's ref hooks) at the repair branch: cut from main, main and
# claude/web as they were, no `mech:` line, the plan covering or ignoring web/, drift clean there and on claude/web
# merged onto it (the original PR, re-run on the fixed plan)
target: {source: file, path: .git/ekit-eval/verdict.txt}
pattern: '^repair: yes$'
flags: m
arm: both
---
