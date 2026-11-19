#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_REPO/.ekit/scenarios/mech-review-mutants/fixtures/cap.sh"

# shard count = min(4, mutants under the cap, ceil(estimated min / (budget / 2))), estimate = capped count x the
# baseline's measured build + test seconds (the fake writes FAKE_BL_BUILD / FAKE_BL_TEST into outcomes.json)
count() { local o; o=$(bl "$@" 2>err.txt) || fail "baseline exit $?: $(cat err.txt)"
  hasnt "baseline traceback" "$(cat err.txt)" "Traceback"; jq -r '"\(.run) \(.count)"' <<<"$o"; }

# small PR: 40 (capped) x 2 s = 1.3 min, budget 10 -> 1 shard
eq "small PR one shard" "$(FAKE_BL_BUILD=1 FAKE_BL_TEST=1 count)" "true 1"
# the same with the workflow's 4-shard ceiling passed in: still 1
eq "small PR --shards 4" "$(FAKE_BL_BUILD=1 FAKE_BL_TEST=1 count --shards 4)" "true 1"
# mid: 40 x 15 s = 10 min / 5 -> 2
eq "mid PR two shards" "$(FAKE_BL_BUILD=10 FAKE_BL_TEST=5 count)" "true 2"
# large: 40 x 120 s = 80 min / 5 = 16 -> at most 4
eq "large PR four shards" "$(FAKE_BL_BUILD=60 FAKE_BL_TEST=60 count)" "true 4"
eq "huge PR never more than 4" "$(FAKE_BL_BUILD=600 FAKE_BL_TEST=600 count)" "true 4"
eq "huge PR --shards 4" "$(FAKE_BL_BUILD=600 FAKE_BL_TEST=600 count --shards 4)" "true 4"
# a bigger budget needs fewer shards: 80 min / 30 -> 3
eq "large PR budget 60" "$(FAKE_BL_BUILD=60 FAKE_BL_TEST=60 count --mutation-budget 60)" "true 3"
# never more shards than mutants under the cap
eq "cap 3 large" "$(FAKE_BL_BUILD=60 FAKE_BL_TEST=60 count --max-mutants 3)" "true 2"
eq "cap 1 large" "$(FAKE_BL_BUILD=60 FAKE_BL_TEST=60 count --max-mutants 1)" "true 1"
python3 "$CAPFX/gen_list.py" 1 | jq '.[0:2]' > list2.json
eq "2 mutants huge" "$(FAKE_LIST="$PWD/list2.json" FAKE_BL_BUILD=600 FAKE_BL_TEST=600 count)" "true 2"

# the large PR's 4 shards, run as CI runs them: none empty, the 40 picked mutants once each
: > ran
for k in 0 1 2 3; do
  : > ran$k
  FAKE_RAN="$PWD/ran$k" mut --shard "$k/4" > "s$k.json" 2>/dev/null; eq "large shard $k exit" "$?" 0
  [[ $(lines < ran$k) -gt 0 ]] || fail "large shard $k ran no mutant"
  cat ran$k >> ran
done
eq "large shards ran 40" "$(lines < ran)" 40
eq "large shards no mutant twice" "$(sort ran | uniq -d | lines)" 0
out=$(mrg --shards 4 --envelope 0=s0.json --envelope 1=s1.json --envelope 2=s2.json --envelope 3=s3.json); rc=$?
eq "large merge exit" "$rc" 0
eq "large merge summary" "$(jq -r .summary <<<"$out")" "pass $H (0 fail, 1 confirm; ran: R3; partial: R3 (40/60); skipped: R1 R2 R4)"
echo "mech-review-baseline/shard-count ok"
