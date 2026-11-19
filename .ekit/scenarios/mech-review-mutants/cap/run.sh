#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_PARENT_DIR/fixtures/cap.sh"

# expected picks, in risk order: branch conditions (by position), then returns
kind "$BRANCH" > branch.txt
kind 'replace f[0-9]+ -> bool with true$' > returns.txt
eq "listing has 60 mutants" "$(jq length "$FAKE_LIST")" 60
eq "listing has 30 branch conditions" "$(lines < branch.txt)" 30

# 1. over the cap: the 5 riskiest run (branch conditions of f0, then f1), the rest untested; partial, never pass
: > ran1
out=$(FAKE_RAN="$PWD/ran1" mut --max-mutants 5); rc=$?
eq "cap 5 exit" "$rc" 0
eq "cap 5 R3" "$(r3 "$out")" partial
eq "cap 5 summary" "$(jq -r .summary <<<"$out")" "pass $H (0 fail, 1 confirm; ran: R3; partial: R3 (5/60); skipped: R1 R2 R4)"
has "cap 5 note names the cap" "$(note "$out")" "55 past the cap (max-mutants 5): untested"
eq "cap 5 ran the 5 riskiest" "$(sort ran1)" "$(head -5 branch.txt | sort)"
hasnt "cap 5 never all pass" "$(jq -r .summary <<<"$out")" "all pass"

# 2. same pick on every run, whatever order the tool lists them in
: > ran2
out2=$(FAKE_SHUFFLE=7 FAKE_RAN="$PWD/ran2" mut --max-mutants 5); rc=$?
eq "shuffled exit" "$rc" 0
eq "shuffled same pick" "$(sort ran2)" "$(sort ran1)"
eq "shuffled same summary" "$(jq -r .summary <<<"$out2")" "$(jq -r .summary <<<"$out")"
: > ran3
FAKE_SHUFFLE=99 FAKE_RAN="$PWD/ran3" mut --max-mutants 5 >/dev/null
eq "second shuffle same pick" "$(sort ran3)" "$(sort ran1)"

# 3. default cap 40: all 30 branch conditions + the 10 returns; no arithmetic, nothing of the rest
: > ran4
out=$(FAKE_RAN="$PWD/ran4" mut); rc=$?
eq "default cap exit" "$rc" 0
eq "default cap R3" "$(r3 "$out")" partial
has "default cap summary" "$(jq -r .summary <<<"$out")" "partial: R3 (40/60)"
has "default cap note" "$(note "$out")" "20 past the cap (max-mutants 40): untested"
eq "default cap ran" "$(sort ran4)" "$(cat branch.txt returns.txt | sort)"
eq "default cap no arithmetic" "$(grep -c 'replace + with -' ran4)" 0
eq "default cap no match arm" "$(grep -c 'delete match arm' ran4)" 0

# 4. a picked mutant that survives is MISSED (fail); a survivor past the cap never runs, so it is untested, not MISSED
out=$(FAKE_MISS='replace > with ==' mut --max-mutants 5); rc=$?
eq "picked survivor exit" "$rc" 1
eq "picked survivor R3" "$(r3 "$out")" fail
eq "picked survivor entries" "$(jq -r '[.entries[] | select(.check=="R3") | .problem] | sort | join(" | ")' <<<"$out")" \
  "MISSED mutant src/lib.rs:1:7: replace > with == in f0 | MISSED mutant src/lib.rs:2:7: replace > with == in f1"
out=$(FAKE_MISS='replace \+ with -' mut --max-mutants 5); rc=$?
eq "unpicked survivor exit" "$rc" 0
eq "unpicked survivor R3" "$(r3 "$out")" partial
eq "unpicked survivor no MISSED" "$(nmissed "$out")" 0

# 5. within the cap: as before (B5): pass n/n, cargo-mutants' own argv (no --re, one run over its list)
: > argv
out=$(FAKE_ARGV="$PWD/argv" mut --max-mutants 60); rc=$?
eq "within cap exit" "$rc" 0
eq "within cap R3" "$(r3 "$out")" pass
eq "within cap summary" "$(jq -r .summary <<<"$out")" "pass $H (0 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)"
hasnt "within cap no cap note" "$(note "$out")" "past the cap"
hasnt "within cap no --re" "$(grep -v -- '--list' argv)" "--re"
out=$(FAKE_MISS='replace \+ with -' mut --max-mutants 60); rc=$?
eq "within cap MISSED exit" "$rc" 1
eq "within cap MISSED entries" "$(nmissed "$out")" 10

# 6. shards over the cap: each picked mutant runs once, in one shard; the merge counts each once; partial, never pass
: > ranS
for k in 0 1 2; do
  FAKE_RAN="$PWD/ranS" mut --max-mutants 12 --shard "$k/3" > "s$k.json"; eq "cap shard $k exit" "$?" 0
done
eq "cap shards ran 12" "$(lines < ranS)" 12
eq "cap shards no mutant twice" "$(sort ranS | uniq -d | lines)" 0
eq "cap shards ran the 12 riskiest" "$(sort ranS)" "$(head -12 branch.txt | sort)"
out=$(mrg --shards 3 --envelope 0=s0.json --envelope 1=s1.json --envelope 2=s2.json); rc=$?
eq "cap merge exit" "$rc" 0
eq "cap merge R3" "$(r3 "$out")" partial
eq "cap merge summary" "$(jq -r .summary <<<"$out")" "pass $H (0 fail, 1 confirm; ran: R3; partial: R3 (12/60); skipped: R1 R2 R4)"
eq "cap merge no CI entry" "$(jq -r '[.entries[] | select(.check=="CI")] | length' <<<"$out")" 0
# a survivor in shard 1 is one MISSED entry in the merge
FAKE_MISS='delete ! in f1$' mut --max-mutants 12 --shard 1/3 > s1m.json
out=$(mrg --shards 3 --envelope 0=s0.json --envelope 1=s1m.json --envelope 2=s2.json); rc=$?
eq "cap merge MISSED exit" "$rc" 1
eq "cap merge MISSED entries" "$(nmissed "$out")" 1

# 7. budget cut-off (B2): 3 of the 12 picked run, then the tool hangs until the budget kills it.
#    A survivor never reached (f3) is untested, no MISSED: partial. A reached survivor (f0) is still MISSED.
out=$(FAKE_MISS='in f3$' FAKE_HANG_AFTER=3 mut --max-mutants 12 --mutation-budget 0.05); rc=$?
eq "budget unreached exit" "$rc" 0
eq "budget unreached R3" "$(r3 "$out")" partial
eq "budget unreached no MISSED" "$(nmissed "$out")" 0
has "budget unreached summary" "$(jq -r .summary <<<"$out")" "partial: R3 (3/60)"
has "budget unreached note" "$(note "$out")" "budget hit"
out=$(FAKE_MISS='replace > with == in f[03]$' FAKE_HANG_AFTER=3 mut --max-mutants 12 --mutation-budget 0.05); rc=$?
eq "budget reached exit" "$rc" 1
eq "budget reached R3" "$(r3 "$out")" fail
eq "budget reached entries" "$(jq -r '[.entries[] | select(.check=="R3") | .problem] | join(" | ")' <<<"$out")" \
  "MISSED mutant src/lib.rs:1:7: replace > with == in f0"

eq "caller checkout untouched" "$(git -C "$R" status --porcelain | lines)" 0
echo "mech-review-mutants/cap ok"
