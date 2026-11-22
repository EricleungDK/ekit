#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_REPO/.ekit/scenarios/mech-review-ts/cap/fixtures/setup.sh"
export FAKE_ARGV="$PWD/argv"
# run with the cap: capped <max-mutants> [env...] -> $out, $rc, $ran (the lines the Stryker run mutated)
capped() { local c="$1"; shift; : > argv; out=$(env "$@" python3 -I "$MR" mutants --repo "$R" --base "$B" --head "$H" \
    --stack ts --test-paths 'tests/**' --mutants-cmd "$STRYKER" ${c:+--max-mutants "$c"} 2>err.txt); rc=$?
  hasnt "no traceback (cap $c)" "$(cat err.txt)" "Traceback"; ran=$(lines_of "$(cat argv)"); }
G=src/grade.ts; U=src/util.ts

# 1. over the cap, riskiest first. 14 mutants on the changed lines (table.json): branch conditions grade:6 (two),
# grade:10, grade:13, util:2; returns grade:5 (true->false), grade:9 (arrow); arithmetic grade:3, grade:11;
# the rest grade:4, grade:6-8 (block), grade:12; strings grade:2, util:3 last.
capped 3
eq "cap 3 exit" "$rc" 0
eq "cap 3 R3" "$(r3 "$out")" partial
eq "cap 3 summary" "$(jq -r .summary <<<"$out")" "pass $H (0 fail, 1 confirm; ran: R3; partial: R3 (3/14); skipped: R1 R2 R4)"
has "cap 3 note" "$(note "$out")" "11 past the cap (max-mutants 3): untested"
eq "cap 3 the two branch lines of grade" "$ran" "$G:6 $G:10"
capped 5
eq "cap 5 summary" "$(jq -r .summary <<<"$out")" "pass $H (0 fail, 1 confirm; ran: R3; partial: R3 (5/14); skipped: R1 R2 R4)"
eq "cap 5 every branch condition, nothing else" "$ran" "$G:6 $G:10 $G:13 $U:2"
capped 7
eq "cap 7 then the returns" "$ran" "$G:5 $G:6 $G:9 $G:10 $G:13 $U:2"
capped 9
eq "cap 9 then arithmetic" "$ran" "$G:3 $G:5 $G:6 $G:9 $G:10 $G:11 $G:13 $U:2"
capped 11
eq "cap 11 then the rest (the block brings its lines)" "$ran" "$G:3 $G:4 $G:5 $G:6 $G:7 $G:8 $G:9 $G:10 $G:11 $G:13 $U:2"
capped 13
eq "cap 13 strings last" "$ran" "$G:2 $G:3 $G:4 $G:5 $G:6 $G:7 $G:8 $G:9 $G:10 $G:11 $G:12 $G:13 $U:2"
eq "cap 13 summary" "$(jq -r .summary <<<"$out")" "pass $H (0 fail, 1 confirm; ran: R3; partial: R3 (13/14); skipped: R1 R2 R4)"
# a cap below the riskiest line's own mutants (grade:6 holds two) tests none, and is never pass
capped 1
eq "cap 1 R3" "$(r3 "$out")" partial
has "cap 1 summary" "$(jq -r .summary <<<"$out")" "partial: R3 (0/14)"

# 2. the same pick on every run, whatever order the instrumenter lists the mutants in
capped 5; first="$(cat argv)"
capped 5; eq "cap 5 again: same argv" "$(cat argv)" "$first"
for seed in 1 2; do capped 5 FAKE_SHUFFLE=$seed
  eq "cap 5 shuffled listing $seed: same argv" "$(cat argv)" "$first"
  eq "cap 5 shuffled $seed summary" "$(jq -r .summary <<<"$out")" "pass $H (0 fail, 1 confirm; ran: R3; partial: R3 (5/14); skipped: R1 R2 R4)"
done

# 3. a survivor in the pick is MISSED (fail); one only past the cap is untested, no MISSED
capped 5 FAKE_SURVIVE="$G:10-10"
eq "survivor in pick exit" "$rc" 1
eq "survivor in pick R3" "$(r3 "$out")" fail
eq "survivor in pick MISSED" "$(jq -r '[.entries[] | select(.problem | startswith("MISSED")) | .problem] | join("|")' <<<"$out")" \
  'MISSED mutant src/grade.ts:10: LogicalOperator `ok && pick.length` -> `ok || pick.length`'
capped 5 FAKE_SURVIVE="$G:2-2|$U:3-3"
eq "survivor past cap exit" "$rc" 0
eq "survivor past cap R3" "$(r3 "$out")" partial
eq "survivor past cap no MISSED" "$(nmissed "$out")" 0

# 4. under the cap (14 fit in 14, and the default 40): every changed line runs, as before: one --mutate range per
# changed run of lines, Stryker's own argv, R3 pass n/n with no cap note; a survivor there is MISSED
for c in 14 ""; do capped "$c"
  eq "under cap ($c) exit" "$rc" 0
  eq "under cap ($c) argv" "$(cat argv)" "run --mutate $G:1-14,$U:1-4 --reporters json --allowConsoleColors false --timeoutMS 120000"
  eq "under cap ($c) summary" "$(jq -r .summary <<<"$out")" "pass $H (0 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)"
  has "under cap ($c) every mutant" "$(note "$out")" "14/14 tested"
  hasnt "under cap ($c) no cap note" "$(note "$out")" "past the cap"
done
capped "" FAKE_SURVIVE="$U:3-3"
eq "under cap survivor exit" "$rc" 1
eq "under cap survivor" "$(jq -r '[.entries[] | select(.problem | startswith("MISSED")) | .problem] | join("|")' <<<"$out")" \
  'MISSED mutant src/util.ts:3: StringLiteral `"none"` -> `""`'

# 5. shards (as the workflow runs them): baseline gives one shard per changed file; each shard runs the picked
# lines of its own files, none twice; the merge counts every mutant once and stays partial
bo=$(bl --max-mutants 5 --shards 4); eq "baseline exit" "$?" 0
eq "baseline count" "$(jq -r '"\(.run) \(.count)"' <<<"$bo")" "true 2"
: > ran
for k in 0 1; do : > ran$k
  FAKE_RAN="$PWD/ran$k" python3 -I "$MR" mutants --repo "$R" --base "$B" --head "$H" --stack ts --test-paths 'tests/**' \
    --mutants-cmd "$STRYKER" --max-mutants 5 --shard "$k/2" > "s$k.json" 2>/dev/null; eq "shard $k exit" "$?" 0
  cat ran$k >> ran
done
eq "shards ran the pick once each" "$(LC_ALL=C sort ran | tr '\n' ' ')" "src/grade.ts:10-10 LogicalOperator src/grade.ts:13-13 BooleanLiteral src/grade.ts:6-6 ConditionalExpression src/grade.ts:6-6 EqualityOperator src/util.ts:2-2 ConditionalExpression "
mo=$(mrg --shards 2 --envelope 0=s0.json --envelope 1=s1.json); rc=$?
eq "merge exit" "$rc" 0
eq "merge summary" "$(jq -r .summary <<<"$mo")" "pass $H (0 fail, 1 confirm; ran: R3; partial: R3 (5/14); skipped: R1 R2 R4)"
eq "merge no CI entry" "$(jq -r '[.entries[] | select(.class=="ci")] | length' <<<"$mo")" 0

# 6. a repo Stryker config in JSON is read as data: the mutators it excludes are not listed (the two
# ConditionalExpression ones), so the cap and total count what the run makes
git -C "$R" checkout -q -b cfg "$H"
printf '{"testRunner":"vitest","mutator":{"excludedMutations":["ConditionalExpression"]}}\n' > "$R/stryker.conf.json"
git -C "$R" add -A; git -C "$R" commit -qm cfg; H=$(git -C "$R" rev-parse HEAD)
capped 3
has "json config summary" "$(jq -r .summary <<<"$out")" "partial: R3 (3/12)"
eq "json config pick" "$ran" "$G:6 $G:10 $G:13"
# a config that is code cannot be read without running it: no cap, every changed line runs, the note says so
git -C "$R" rm -q stryker.conf.json; printf 'export default { testRunner: "vitest" };\n' > "$R/stryker.conf.mjs"
git -C "$R" add -A; git -C "$R" commit -qm cfgjs; H=$(git -C "$R" rev-parse HEAD)
capped 3
has "code config not applied" "$(note "$out")" "max-mutants not applied: "
has "code config every changed line" "$ran" "$G:1 $G:2 $G:3 $G:4 $G:5 $G:6 $G:7 $G:8 $G:9 $G:10 $G:11 $G:12 $G:13 $G:14"
hasnt "code config no cap count" "$(note "$out")" "past the cap"

# the user's checkout is untouched
eq "checkout clean" "$(git -C "$R" status --porcelain)" ""
echo "mech-review-ts/cap ok"
