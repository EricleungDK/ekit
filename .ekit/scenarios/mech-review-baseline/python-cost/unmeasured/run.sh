#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_REPO/.ekit/scenarios/mech-review-baseline/python-cost/fixtures/setup.sh"
# a baseline that measured nothing keeps one shard per changed production file, at most 4, and its note says why;
# the suite time it was given (600 s, which would ask for 4 shards) is never used
unmeasured() { local why="$1" files="$2" n="$3"; shift 3
  eq "$why: count" "$(blj FAKE_SUITE_S=600 "$@" -- --shards 4)" "true $n null"
  has "$why: note" "$(jq -r .checks.R3.note bl.json)" "$files changed production file(s) in $n shard(s); test time not measured ("
  has "$why: note rule" "$(jq -r .checks.R3.note bl.json)" "): one shard per changed file"
  eq "$why: no measured time" "$(jq -r '.checks.R3.timing.baseline_test_s // "none"' bl.json)" none
  eq "$why: not a fail" "$(jq -r '[.entries[]] | length' bl.json)" 0; }

# two changed modules (one mutant each)
pr_head two 0 a b
unmeasured "no time in the JUnit XML" 2 2 FAKE_JUNIT=notime
has "no time: names the JUnit XML" "$(jq -r .checks.R3.note bl.json)" "wrote no session time in its JUnit XML"
unmeasured "no JUnit XML (-p no:junitxml)" 2 2 FAKE_JUNIT=none
unmeasured "red suite" 2 2 FAKE_SUITE_RC=1
has "red suite: names the exit" "$(jq -r .checks.R3.note bl.json)" "ended with 1"
SECONDS=0
eq "suite past the budget: count" "$(blj FAKE_SUITE_S=600 FAKE_SUITE_HANG=1 -- --shards 4 --mutation-budget 0.05)" "true 2 null"
has "suite past the budget: note" "$(jq -r .checks.R3.note bl.json)" "did not finish within mutation-budget (0.05 min)): one shard per changed file"
[[ $SECONDS -lt 60 ]] || fail "suite past the budget: the baseline took ${SECONDS}s"
unmeasured "mutmut not runnable" 2 2 FAKE_MUTMUT_BROKEN=1
has "mutmut not runnable: note" "$(jq -r .checks.R3.note bl.json)" "mutmut not runnable"
unmeasured "listing crashed" 2 2 FAKE_LIST_BROKEN=1
has "listing crashed: note" "$(jq -r .checks.R3.note bl.json)" "listing"
# a repo that configures mutmut itself
git -C "$R" checkout -q -b own two; printf '\n[tool.mutmut]\nsource_paths = ["src"]\n' >> "$R/pyproject.toml"
git -C "$R" commit -qam own; H=$(git -C "$R" rev-parse HEAD)
unmeasured "own [tool.mutmut]" 2 2
has "own config: note" "$(jq -r .checks.R3.note bl.json)" "[tool.mutmut]"

# five changed modules: at most 4 shards; one: 1
pr_head five 8 a b c d
unmeasured "five files" 5 4 FAKE_JUNIT=notime
pr_head one 0 a
unmeasured "one file" 1 1 FAKE_JUNIT=notime

# merge accepts the shards an unmeasured baseline asked for: 2 changed files, 2 shards, each mutant once
pr_head two-again 0 a b
unmeasured "merge base" 2 2 FAKE_JUNIT=notime; cp bl.json blu.json
shards_merge blu.json
eq "unmeasured merge exit" "$MRC" 0
eq "unmeasured merge summary" "$(jq -r .summary <<<"$MOUT")" "pass $H (0 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)"
eq "unmeasured merge no CI entry" "$(jq -r '[.entries[] | select(.class=="ci" or .class=="env")] | length' <<<"$MOUT")" 0
eq "unmeasured merge each mutant once" "$(sort ran | tr '\n' ' ')" "calc.a.x_a__mutmut_1 calc.b.x_b__mutmut_1 "
shards_merge blu.json FAKE_SURVIVE='x_b__'
eq "unmeasured survivor exit" "$MRC" 1
eq "unmeasured survivor MISSED" "$(jq -r '[.entries[] | select(.problem | startswith("MISSED")) | .problem] | join("|")' <<<"$MOUT")" \
  "MISSED mutant src/calc/b.py:2: return n + 1 -> return n - 1"
# a shard missing from the merge is an entry naming it, never pass
mo=$(mrg --baseline blu.json --shards 2 --envelope 0=shard0.json); rc=$?
eq "missing shard exit" "$rc" 1
has "missing shard named" "$(jq -r '[.entries[].problem] | join("|")' <<<"$mo")" "shard 1/2"

eq "checkout clean" "$(git -C "$R" status --porcelain)" ""
echo "mech-review-baseline/python-cost/unmeasured ok"
