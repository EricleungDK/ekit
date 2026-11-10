#!/bin/bash
# The python unit tests (tests/py, stdlib unittest; pytest collects them too, which is how mech-review's R1/R4 run them).
source "$(dirname "$0")/lib.sh"
out="$(cd "$ROOT" && python3 -m unittest discover -s tests/py 2>&1)"; rc=$?
eq "$rc" "0" "tests/py: unittest discover"
(( rc == 0 )) || printf '%s\n' "$out"
ran="$(grep -o '^Ran [0-9]* tests' <<<"$out")"
[[ $ran =~ ^Ran\ [1-9] ]] && ok "tests/py: $ran" || fail "tests/py: no tests ran"
done_tests
