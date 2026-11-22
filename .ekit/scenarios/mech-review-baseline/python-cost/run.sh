#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_REPO/.ekit/scenarios/mech-review-baseline/python-cost/fixtures/setup.sh"
# shard count = min(4, mutants under the cap, ceil(mutants x the suite's test time in minutes / (budget / 2)));
# the fake pytest writes the session time FAKE_SUITE_S into the JUnit XML the baseline asks for

# a one-file PR whose 8 changed functions make 8 mutants on changed lines (budget 10 -> 5 min per shard)
pr_head all8 8
# 1. small: 8 x 0.5 s -> 1 shard; the measured time is in the JSON
eq "small PR" "$(blj FAKE_SUITE_S=0.5 -- --shards 4)" "true 1 8"
eq "small PR measured time" "$(jq -r .checks.R3.timing.baseline_test_s bl.json)" "0.5"
has "small PR note" "$(jq -r .checks.R3.note bl.json)" "8 mutants on changed lines"
eq "per-mutant timeout stays mutmut's" "$(jq -r .timeout bl.json)" "null"
# 2. costly, from the measured time alone (the same one file): 8 min -> 2; 12 -> 3; 16 -> 4; 80 -> 4 (never more)
eq "8 min" "$(blj FAKE_SUITE_S=60 -- --shards 4)" "true 2 8"
eq "8 min measured time" "$(jq -r .checks.R3.timing.baseline_test_s bl.json)" "60.0"
has "8 min note names the estimate" "$(jq -r .checks.R3.note bl.json)" "in 2 shard(s) (estimated 8.0 min"
eq "12 min" "$(blj FAKE_SUITE_S=90 -- --shards 4)" "true 3 8"
eq "16 min" "$(blj FAKE_SUITE_S=120 -- --shards 4)" "true 4 8"
eq "80 min never more than 4" "$(blj FAKE_SUITE_S=600 -- --shards 4)" "true 4 8"
eq "80 min, no --shards" "$(blj FAKE_SUITE_S=600)" "true 4 8"
eq "80 min measured time" "$(jq -r .checks.R3.timing.baseline_test_s bl.json)" "600.0"
# a bigger budget needs fewer shards: 16 min / 30 -> 1
eq "budget 60" "$(blj FAKE_SUITE_S=120 -- --shards 4 --mutation-budget 60)" "true 1 8"
# 3. never more shards than mutants: the cap, or a PR with fewer mutants
eq "cap 2" "$(blj FAKE_SUITE_S=600 -- --shards 4 --max-mutants 2)" "true 2 8"
eq "cap 1" "$(blj FAKE_SUITE_S=600 -- --shards 4 --max-mutants 1)" "true 1 8"
git -C "$R" checkout -q main; pr_head three 3
eq "3 mutants, 80 min" "$(blj FAKE_SUITE_S=1600 -- --shards 4)" "true 3 3"
# no mutant on a changed line (a comment-only change): no shard, R3 pass
git -C "$R" checkout -q -b comment "$B"; printf '# notes\n' >> "$R/src/calc/core.py"; git -C "$R" commit -qam comment; H=$(git -C "$R" rev-parse HEAD)
eq "no mutant on a changed line" "$(blj FAKE_SUITE_S=600 -- --shards 4)" "false 0 0"
eq "no mutant R3" "$(jq -r .checks.R3.status bl.json)" pass

# 4. merge accepts the shards the measured baseline asked for: each mutant runs in exactly one shard, the merge
# counts each once, adds the baseline's test time once, and a survivor is one MISSED entry
git -C "$R" checkout -q all8; H=$(git -C "$R" rev-parse HEAD)
eq "large baseline" "$(blj FAKE_SUITE_S=120 -- --shards 4)" "true 4 8"; cp bl.json bl4.json
shards_merge bl4.json
eq "4 shards merge exit" "$MRC" 0
eq "4 shards merge summary" "$(jq -r .summary <<<"$MOUT")" "pass $H (0 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)"
eq "4 shards tested" "$(jq -r '"\(.checks.R3.tested)/\(.checks.R3.total)"' <<<"$MOUT")" "8/8"
eq "4 shards no CI entry" "$(jq -r '[.entries[] | select(.class=="ci" or .class=="env")] | length' <<<"$MOUT")" 0
eq "4 shards baseline time once" "$(jq -r .checks.R3.timing.baseline_test_s <<<"$MOUT")" "120.0"
eq "4 shards each mutant once" "$(sort ran | uniq | lines) $(lines < ran)" "8 8"
for k in 0 1 2 3; do has "shard $k ran a share" "$(jq -r .checks.R3.note "shard$k.json")" "2/2 tested"; done
shards_merge bl4.json FAKE_SURVIVE='x_f5__'
eq "survivor merge exit" "$MRC" 1
eq "survivor merge MISSED" "$(jq -r '[.entries[] | select(.problem | startswith("MISSED")) | .problem] | join("|")' <<<"$MOUT")" \
  "MISSED mutant src/calc/core.py:18: return n + 5 -> return n - 5"
# with the cap passed to baseline and shards alike: 5 of 8 over 2 shards, partial (5/8), each once
eq "capped baseline" "$(blj FAKE_SUITE_S=90 -- --shards 4 --max-mutants 5)" "true 2 8"; cp bl.json blc.json
shards_merge blc.json -- --max-mutants 5
eq "capped merge exit" "$MRC" 0
has "capped merge summary" "$(jq -r .summary <<<"$MOUT")" "partial: R3 (5/8)"
eq "capped each once" "$(sort ran | uniq | lines) $(lines < ran)" "5 5"

eq "checkout clean" "$(git -C "$R" status --porcelain)" ""
echo "mech-review-baseline/python-cost ok"
