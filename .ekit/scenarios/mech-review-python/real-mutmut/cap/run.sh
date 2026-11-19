#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_PARENT_DIR/fixtures/mutmut.sh"
# no __pycache__ in the checkout, so "untouched" compares the user's files only (see real-mutmut/untracked)
export PYTHONDONTWRITEBYTECODE=1

mk_py_repo
# head adds classify (14 mutants: 5 in its `if` condition, 2 in `return total > 5`, 2 strings, 5 arithmetic),
# called by a test that asserts nothing, so mutmut misses every one
git -C "$R" checkout -q -b cap "$BASE"
cat >> "$R/src/calc/core.py" <<'PY'


def classify(n):
    if n > 10 and n < 100:
        return "mid"
    total = n * 2 + 1
    return total > 5
PY
printf '\n\ndef test_classify_runs():\n    from calc.core import classify\n    classify(50)\n' >> "$R/tests/test_core.py"
git -C "$R" commit -qam cap; H=$(git -C "$R" rev-parse HEAD)
before=$(git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD)
lines_of() { jq -r '[.entries[] | select(.check=="R3") | .line] | unique | map(tostring) | join(",")' <<<"$1"; }
nmissed() { jq -r '[.entries[] | select(.check=="R3" and (.problem | startswith("MISSED")))] | length' <<<"$1"; }

# 1. over the cap (3 of 14): the riskiest, the `if` condition on line 10; still MISSED (they ran), the rest untested
out=$(mutants_run "$BASE" "$H" --max-mutants 3); rc=$?
eq "cap 3 exit" "$rc" 1
eq "cap 3 R3" "$(jq -r .checks.R3.status <<<"$out")" fail
eq "cap 3 MISSED" "$(nmissed "$out")" 3
eq "cap 3 lines" "$(lines_of "$out")" 10
has "cap 3 note" "$(jq -r .checks.R3.note <<<"$out")" "3/14 tested"
has "cap 3 note names the cap" "$(jq -r .checks.R3.note <<<"$out")" "11 past the cap (max-mutants 3): untested"
# same pick on the next run
out2=$(mutants_run "$BASE" "$H" --max-mutants 3)
eq "cap 3 same pick" "$(jq -c '[.entries[].problem] | sort' <<<"$out2")" "$(jq -c '[.entries[].problem] | sort' <<<"$out")"
# 6 of 14: the branch conditions: the five in the `if` and the comparison operator of `return total > 5`
out=$(mutants_run "$BASE" "$H" --max-mutants 6); rc=$?
eq "cap 6 MISSED" "$(nmissed "$out")" 6
eq "cap 6 lines" "$(lines_of "$out")" "10,13"
has "cap 6 comparison" "$(jq -r '[.entries[].problem] | join(" | ")' <<<"$out")" "return total > 5 -> return total >= 5"
# 10 of 14: the two string mutants of `return "mid"` (line 11) come last, after the arithmetic
out=$(mutants_run "$BASE" "$H" --max-mutants 10); rc=$?
eq "cap 10 MISSED" "$(nmissed "$out")" 10
hasnt "cap 10 strings last" "$(lines_of "$out")" "11"

# 2. shards over the cap: 4 shards share 3 mutants; each runs once, the 4th is empty (declared python limit); merge counts once
for k in 0 1 2 3; do mutants_run "$BASE" "$H" --max-mutants 3 --shard "$k/4" > "s$k.json"; done
has "empty python shard" "$(jq -r .checks.R3.note s3.json)" "0 mutants in this shard"
out=$(python3 -I "$MR" merge --repo "$R" --base "$BASE" --head "$H" --stack python --shards 4 \
  --envelope 0=s0.json --envelope 1=s1.json --envelope 2=s2.json --envelope 3=s3.json); rc=$?
eq "merge exit" "$rc" 1
eq "merge MISSED once each" "$(nmissed "$out")" 3
eq "merge same as unsharded" "$(jq -c '[.entries[].problem] | sort' <<<"$out")" "$(jq -c '[.entries[].problem] | sort' <<<"$out2")"
# the baseline step: python measures nothing, one shard per changed production file
eq "python baseline count" "$(python3 -I "$MR" baseline --repo "$R" --base "$BASE" --head "$H" --stack python --test-paths 'tests/**' --shards 4 2>/dev/null | jq -r .count)" 1

# 3. B2: a mutant mutmut reports missed waits for its whole-suite retry; the budget ends before any retry finishes
#    (a test sleeps when the source on disk is mutated, as `mutmut apply` leaves it) -> untested, no MISSED, partial
git -C "$R" checkout -q -b slow "$H"
cat > "$R/tests/test_slow.py" <<'PY'
import time
from pathlib import Path


def test_slow_when_mutated():
    src = (Path(__file__).resolve().parent.parent / "src" / "calc" / "core.py").read_text()
    if "if n > 10 and n < 100:" not in src:
        time.sleep(90)
PY
git -C "$R" add -A; git -C "$R" commit -qm slow; HS=$(git -C "$R" rev-parse HEAD)
out=$(mutants_run "$BASE" "$HS" --max-mutants 3 --mutation-budget 0.5); rc=$?
eq "retry cut exit" "$rc" 0
eq "retry cut R3" "$(jq -r .checks.R3.status <<<"$out")" partial
eq "retry cut no MISSED" "$(nmissed "$out")" 0
has "retry cut note" "$(jq -r .checks.R3.note <<<"$out")" "whole-suite retry not reached at budget: untested"
hasnt "retry cut never all pass" "$(jq -r .summary <<<"$out")" "all pass"

git -C "$R" checkout -q cap
eq "checkout untouched" "$(git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD)" "$before"
echo "mech-review-python/real-mutmut/cap ok"
