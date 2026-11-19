#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
MR="$EKIT_REPO/scripts/mech-review.py"
FX="$(dirname "$EKIT_PARENT_DIR")/fixtures"
R="$PWD/repo"; cp -R "$FX/base" "$R"; git -C "$R" init -q -b main; git -C "$R" add -A; git -C "$R" commit -qm base
BASE=$(git -C "$R" rev-parse HEAD); printf '\n// note\n' >> "$R/tests/CalcTest.kt"; git -C "$R" commit -qam note; HEAD=$(git -C "$R" rev-parse HEAD)
sed 's/^brackets = .*/brackets = ["(]", "[]", "{}"]/' "$FX/ktspec.toml" > with-shapes.toml
sed '/^\[functions\]/,/^shapes/d' with-shapes.toml > no-shapes.toml
for f in with-shapes.toml no-shapes.toml; do
  o=$(python3 "$MR" r2 --repo "$R" --base "$BASE" --head "$HEAD" --stack ktspec --adapter "$f" --test-paths 'tests/**' 2>err); rc=$?
  hasnt "$f traceback" "$(cat err)" "Traceback"
  eq "$f exit (got: $(jq -r '[.entries[].problem] | join(" | ")' <<<"$o" 2>/dev/null) $(cat err))" "$rc" 2
  eq "$f stdout" "$o" ""
  has "$f names the field" "$(cat err)" "lexer.brackets"
done
echo "bracket-pair ok"
