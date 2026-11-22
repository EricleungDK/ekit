#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_REPO/.ekit/scenarios/mech-review-ts/cap/fixtures/setup.sh"
# a Stryker run the budget stops (0.05 min): run <env...> -> $out, $rc
run() { out=$(env "$@" python3 -I "$MR" mutants --repo "$R" --base "$B" --head "$H" --stack ts --test-paths 'tests/**' \
    --mutants-cmd "$STRYKER" --mutation-budget 0.05 ${CAP:+--max-mutants "$CAP"} 2>err.txt); rc=$?
  hasnt "no traceback" "$(cat err.txt)" "Traceback"; }
summary() { jq -r .summary <<<"$out"; }

for CAP in 5 ""; do
  # 1. stopped before Stryker wrote its report: partial with the listed total, tested unknown, no MISSED (even with
  # every mutant set to survive), never pass
  run FAKE_HANG=before FAKE_SURVIVE=.
  eq "before report ($CAP) exit" "$rc" 0
  eq "before report ($CAP) R3" "$(r3 "$out")" partial
  eq "before report ($CAP) total" "$(jq -r .checks.R3.total <<<"$out")" 14
  eq "before report ($CAP) no MISSED" "$(nmissed "$out")" 0
  has "before report ($CAP) summary partial" "$(summary)" "ran: R3; partial: R3"
  hasnt "before report ($CAP) never all pass" "$(summary)" "all pass"

  # 2. stopped after a report with 2 mutants done, the rest Pending: the 12 unreached are untested, no MISSED,
  # partial (2/14)
  run FAKE_HANG=after FAKE_DONE=2
  eq "pending ($CAP) exit" "$rc" 0
  eq "pending ($CAP) R3" "$(r3 "$out")" partial
  has "pending ($CAP) summary" "$(summary)" "partial: R3 (2/14)"
  eq "pending ($CAP) no MISSED" "$(nmissed "$out")" 0
  has "pending ($CAP) untested entry" "$(jq -r '[.entries[].problem] | join("|")' <<<"$out")" "R3 partial: 12/14 mutants untested"

  # 3. the same with every string and condition set to survive: only a mutant that really ran and survived is
  # MISSED (capped: grade:6's ConditionalExpression ran second; uncapped: grade:2's string ran first), the Pending
  # ones (util:2, util:3, grade:6 uncapped) never are
  run FAKE_HANG=after FAKE_DONE=2 FAKE_SURVIVE='ConditionalExpression|StringLiteral'
  eq "pending survivors ($CAP) exit" "$rc" 1
  eq "pending survivors ($CAP) R3" "$(r3 "$out")" fail
  eq "pending survivors ($CAP) MISSED" "$(jq -r '[.entries[] | select(.problem | startswith("MISSED")) | .problem] | join("|")' <<<"$out")" \
    "$(if [[ -n $CAP ]]; then echo 'MISSED mutant src/grade.ts:6: ConditionalExpression `n > 10` -> `false`'
       else echo 'MISSED mutant src/grade.ts:2: StringLiteral `"pts"` -> `""`'; fi)"
done
# with the cap, the note still names the mutants past it
CAP=5 run FAKE_HANG=after FAKE_DONE=2
has "pending capped note" "$(note "$out")" "9 past the cap (max-mutants 5): untested"

# a Stryker run that makes more mutants on the picked lines than its instrumenter listed there (a repo setting that
# changes parsing does this) did not keep the cap: n/a (env), never pass, no MISSED
jq '. + [{"file":"src/grade.ts","start":6,"end":6,"mutator":"EqualityOperator","from":"n > 10","replacement":"n < 10"}]' \
  "$FAKE_TABLE" > extra.json
printf '#!/bin/bash\n[[ "$1" == --version ]] || export FAKE_TABLE=%q\nexec %q "$@"\n' "$PWD/extra.json" "$STRYKER" > "$SI/node_modules/.bin/stryker-extra"
chmod +x "$SI/node_modules/.bin/stryker-extra"
out=$(python3 -I "$MR" mutants --repo "$R" --base "$B" --head "$H" --stack ts --test-paths 'tests/**' \
  --mutants-cmd "$SI/node_modules/.bin/stryker-extra" --max-mutants 3 2>err.txt); rc=$?
eq "cap not kept exit" "$rc" 0
eq "cap not kept R3" "$(r3 "$out")" n/a
has "cap not kept note" "$(note "$out")" "the cap was not kept"
has "cap not kept summary" "$(summary)" "n/a: R3"
hasnt "cap not kept never pass" "$(jq -r .checks.R3.status <<<"$out")" pass
eq "checkout clean" "$(git -C "$R" status --porcelain)" ""
echo "mech-review-ts/cap/budget ok"
