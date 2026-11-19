#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
MR="$EKIT_REPO/scripts/mech-review.py"
AD="$EKIT_REPO/scripts/mech_review/adapters/ts.toml"
[[ -f $AD ]] || fail "shipped adapter file missing: scripts/mech_review/adapters/ts.toml"

R="$PWD/repo"; mkdir -p "$R/src" "$R/tests"; git -C "$R" init -q -b main
printf '{"name":"calc"}\n' > "$R/package.json"
printf 'export function add(a: number, b: number): number {\n  return a+b;\n}\n' > "$R/src/calc.ts"
cat > "$R/tests/calc.test.ts" <<'EOF'
import { describe, it, expect } from "vitest";
import { add } from "../src/calc";

describe("Calc", () => {
  it("adds", () => {
    expect(add(1, 2)).toBe(3);
    expect(add(0, 0)).not.toBe(1);
  });
  it("keeps", () => {
    expect(add(2, 2)).toEqual(4);
    expect(add(2, 2)).toBeGreaterThan(1);
  });
});
EOF
git -C "$R" add -A; git -C "$R" commit -qm base; BASE=$(git -C "$R" rev-parse HEAD)
F="$R/tests/calc.test.ts"
# mkhead <branch> <edit command...>: a commit from base, its sha in H
mkhead() { local b=$1; shift; git -C "$R" checkout -q -B "$b" "$BASE"; "$@"; git -C "$R" add -A; git -C "$R" commit -qm "$b"; H=$(git -C "$R" rev-parse HEAD); }
# both: run r2 built-in (B, RB) and through the adapter file (A, RA)
both() {
  B=$(python3 "$MR" r2 --repo "$R" --base "$BASE" --head "$H" --stack ts --test-paths 'tests/**' 2>berr); RB=$?
  A=$(python3 "$MR" r2 --repo "$R" --base "$BASE" --head "$H" --stack ts --adapter "$AD" --test-paths 'tests/**' 2>aerr); RA=$?
  hasnt "$1 traceback" "$(cat berr aerr)" "Traceback"
}
# same <label> <exit> <n entries> [problem substring]: adapter output is the built-in's, byte for byte
same() { both "$1"
  eq "$1 adapter exit" "$RA" "$2"; eq "$1 builtin exit" "$RB" "$2"
  eq "$1 same JSON" "$A" "$B"
  eq "$1 entries" "$(jq '.entries | length' <<<"$A")" "$3"
  [[ -z ${4:-} ]] || has "$1 problem" "$(jq -r '[.entries[].problem] | join(" | ")' <<<"$A")" "$4"
  eq "$1 summary sha" "$(jq -r .summary <<<"$A" | cut -d' ' -f2)" "$H"; }
py_edit() { python3 -I -c "import sys,re;p=sys.argv[1];s=open(p).read();s=re.sub(sys.argv[2],sys.argv[3],s,count=1,flags=re.S);open(p,'w').write(s)" "$F" "$1" "$2"; }

mkhead honest py_edit '  \}\);\n\}\);' '  });\n  it("subs", () => {\n    expect(add(5, -2)).toBe(3);\n  });\n});'
same honest 0 0
eq "honest summary" "$(jq -r .summary <<<"$A")" "pass $H (0 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)"

mkhead skip sed -i 's/it("keeps"/it.skip("keeps"/' "$F"; same "it.skip" 1 1 "test \`Calc > keeps\` marked skipped"
eq "skip class" "$(jq -r '.entries[0] | .severity + " " + .class' <<<"$A")" "fail agent-fixable"
mkhead xit sed -i 's/it("keeps"/xit("keeps"/' "$F"; same xit 1 1 "test \`Calc > keeps\` marked skipped"
mkhead deleted py_edit '  it\("keeps".*?\n  \}\);\n' ''; same deleted 1 1 "test fn \`Calc > keeps\` removed"
mkhead expected sed -i 's/toBe(3)/toBe(4)/' "$F"; same "expected value" 0 1 "expected value changed in \`Calc > adds\`: was 3, now 4"
eq "expected severity" "$(jq -r '.entries[0].severity' <<<"$A")" confirm
mkhead dropped sed -i '/toBeGreaterThan/d' "$F"; same "dropped assert" 1 1 "assertions in test \`Calc > keeps\` dropped from 2 to 1"
mkhead lint sed -i 's|^import { add }|// eslint-disable-next-line no-unused-vars\nimport { add }|' "$F"; same "eslint no reason" 1 1 "\`eslint-disable-next-line no-unused-vars\` added without a reason"
mkhead lint-ok sed -i 's|^import { add }|// eslint-disable-next-line no-unused-vars -- fixture\nimport { add }|' "$F"; same "eslint reasoned" 0 0
mkhead tsignore sed -i 's|^import { add }|// @ts-ignore\nimport { add }|' "$F"; same "ts-ignore" 1 1 "\`@ts-ignore\` added without a reason"
mkhead stryker sed -i 's|^export function|// Stryker disable all\nexport function|' "$R/src/calc.ts"; same "Stryker disable" 1 1 "mutation skip added: \`Stryker disable all\`"
eq "stryker class" "$(jq -r '.entries[0].class' <<<"$A")" needs-human
mkhead only sed -i 's/it("adds"/it.only("adds"/' "$F"; same "it.only" 1 1 "test \`Calc > adds\` marked only"

# A4: a test file that does not balance is needs-human through the adapter file, agent-fixable built in
for c in unbalanced template; do
  if [[ $c == unbalanced ]]; then mkhead $c sed -i 's/toBe(3);/toBe(3;/' "$F"; else mkhead $c sh -c "echo 'const s = \`abc' >> '$F'"; fi
  both "$c"
  eq "$c adapter exit" "$RA" 1; eq "$c builtin exit" "$RB" 1
  eq "$c adapter entries" "$(jq '.entries | length' <<<"$A")" 1
  eq "$c adapter entry" "$(jq -r '.entries[0] | .check + " " + .severity + " " + .class + " " + .file' <<<"$A")" "R2 fail needs-human tests/calc.test.ts"
  has "$c adapter problem" "$(jq -r '.entries[0].problem' <<<"$A")" "file does not parse"
  eq "$c builtin class" "$(jq -r '.entries[0].class' <<<"$B")" agent-fixable
  eq "$c rest same" "$(jq -S 'del(.entries[0].class, .entries[0].hint)' <<<"$A")" "$(jq -S 'del(.entries[0].class, .entries[0].hint)' <<<"$B")"
done
echo "mech-review-ts adapter-file ok"
