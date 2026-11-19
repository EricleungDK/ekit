#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_PARENT_DIR/fixtures/cap.sh"

# usage error: exit 2, nothing on stdout, the message on stderr, no traceback: usage <label> <stderr text> <cmd...>
usage() { local label="$1" want="$2"; shift 2
  local o; o=$("$@" 2>err.txt); local rc=$?
  eq "$label exit" "$rc" 2
  eq "$label stdout" "$o" ""
  has "$label message" "$(cat err.txt)" "$want"
  hasnt "$label traceback" "$(cat err.txt)" "Traceback"; }
# an honest result: never pass, never a traceback: honest <label> <want status> <json>
honest() { eq "$1 R3" "$(r3 "$3")" "$2"; hasnt "$1 traceback" "$(cat err.txt)" "Traceback"
  hasnt "$1 never all pass" "$(jq -r .summary <<<"$3")" "all pass"; }

# 1. bad --max-mutants, on a shard run and on the baseline step
for v in 0 -1 abc '' 1.5; do
  usage "mutants --max-mutants '$v'" "want a whole number >= 1" mut --max-mutants "$v"
  usage "baseline --max-mutants '$v'" "want a whole number >= 1" bl --max-mutants "$v"
done
# 2. a budget that is not a finite number of minutes
for v in nan inf NaN; do
  usage "mutants --mutation-budget $v" "finite number" mut --max-mutants 5 --mutation-budget "$v"
  usage "baseline --mutation-budget $v" "finite number" bl --mutation-budget "$v"
done
# 3. a shard index past the count
for v in 3/3 5/3 0/0 a/b; do usage "--shard $v" "want K/N with 0 <= K < N" mut --max-mutants 12 --shard "$v"; done
usage "baseline --shards 0" "want N >= 1" bl --shards 0

# 4. examine_re in .cargo/mutants.toml: cargo-mutants runs mutants past the pick -> n/a (env) naming examine_re, never pass
out=$(FAKE_EXTRA='replace \+ with -' mut --max-mutants 5 2>err.txt); rc=$?
eq "examine_re exit" "$rc" 0
honest "examine_re" "n/a" "$out"
has "examine_re named" "$(note "$out")" "examine_re"
has "examine_re env" "$(note "$out")" "(env)"
has "examine_re summary" "$(jq -r .summary <<<"$out")" "n/a: R3"
out=$(FAKE_EXTRA='in f9$' mut --max-mutants 6 --shard 1/2 2>err.txt); rc=$?
honest "examine_re shard" "n/a" "$out"
has "examine_re shard named" "$(note "$out")" "examine_re"
# a whole n/a shard keeps the merge from reading pass
mut --max-mutants 6 --shard 0/2 > s0.json 2>/dev/null
printf '%s\n' "$out" > s1.json
out=$(mrg --shards 2 --envelope 0=s0.json --envelope 1=s1.json 2>err.txt)
hasnt "examine_re merge not pass" "$(r3 "$out")" "pass"

# 5. the listing fails: n/a (env), never pass; the baseline step too
out=$(FAKE_LIST_RC=1 mut --max-mutants 5 2>err.txt); rc=$?
eq "list fails exit" "$rc" 0
honest "list fails" "n/a" "$out"
has "list fails note" "$(note "$out")" "--list failed (env)"
out=$(FAKE_LIST_RC=1 mut --max-mutants 5 --shard 1/2 2>err.txt)
honest "list fails shard" "n/a" "$out"
out=$(FAKE_LIST_RC=1 bl 2>err.txt); rc=$?
eq "list fails baseline exit" "$rc" 0
honest "list fails baseline" "n/a" "$out"
eq "list fails baseline no shards" "$(jq -r .run <<<"$out")" false

# 6. more shards than picked mutants (misconfigured matrix): an empty share says so, adds nothing; never reads as tested
: > ran
out=$(FAKE_RAN="$PWD/ran" mut --max-mutants 5 --shard 9/10 2>err.txt); rc=$?
eq "empty share exit" "$rc" 0
has "empty share note" "$(note "$out")" "0 mutants in this shard"
eq "empty share ran nothing" "$(lines < ran)" 0

# 7. a budget of 0 minutes: nothing tested, never pass
out=$(mut --max-mutants 5 --mutation-budget 0 2>err.txt); rc=$?
hasnt "budget 0 not pass" "$(r3 "$out")" "pass"
hasnt "budget 0 traceback" "$(cat err.txt)" "Traceback"

eq "caller checkout untouched" "$(git -C "$R" status --porcelain | lines)" 0
echo "mech-review-mutants/cap-misuse ok"
