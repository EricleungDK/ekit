#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
MR="$EKIT_REPO/scripts/mech-review.py"
FX="${EKIT_SCENARIO_DIR}/fixtures"
cp "$FX/ktspec.toml" ./ktspec.toml; AD="$PWD/ktspec.toml"
R="$PWD/repo"; cp -R "$FX/base" "$R"; git -C "$R" init -q -b main; git -C "$R" add -A; git -C "$R" commit -qm base
BASE=$(git -C "$R" rev-parse HEAD); F="$R/tests/CalcTest.kt"
# mkhead <branch> <edit command...>: a commit from base, its sha in H
mkhead() { local b=$1; shift; git -C "$R" checkout -q -B "$b" "$BASE"; "$@"; git -C "$R" add -A; git -C "$R" commit -qm "$b"; H=$(git -C "$R" rev-parse HEAD); }
py_edit() { python3 -I -c "import sys,re;p=sys.argv[1];s=open(p).read();s=re.sub(sys.argv[2],sys.argv[3],s,count=1,flags=re.S);open(p,'w').write(s)" "$F" "$1" "$2"; }
# r2 <label> <exit> <n entries>: OUT, problems in P
r2() { OUT=$(python3 "$MR" r2 --repo "$R" --base "$BASE" --head "$H" --stack ktspec --adapter "$AD" --test-paths 'tests/**' 2>err); local rc=$?
  hasnt "$1 traceback" "$(cat err)" "Traceback"; eq "$1 exit" "$rc" "$2"
  eq "$1 entries" "$(jq '.entries | length' <<<"$OUT")" "$3"
  P=$(jq -r '[.entries[] | .severity + " " + .class + " " + .file + ": " + .problem] | join(" | ")' <<<"$OUT"); }

mkhead honest py_edit '    \}\)\n\}\)' '    })\n    test("subs", {\n        assertEquals(1, add(2, -1))\n    })\n})'
r2 honest 0 0; eq "honest summary" "$(jq -r .summary <<<"$OUT")" "pass $H (0 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)"

mkhead xtest sed -i 's/test("keeps"/xtest("keeps"/' "$F"; r2 xtest 1 1
eq "xtest entry" "$P" "fail agent-fixable tests/CalcTest.kt: test \`Calc / keeps\` disabled with an x prefix"
eq "xtest summary" "$(jq -r .summary <<<"$OUT")" "fail $H (1 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)"

mkhead xcontext sed -i 's/^context("Calc"/xcontext("Calc"/' "$F"; r2 xcontext 1 2
has "xcontext adds" "$P" "test \`Calc / adds\` disabled with an x prefix"; has "xcontext keeps" "$P" "test \`Calc / keeps\` disabled with an x prefix"

mkhead deleted py_edit '    test\("keeps".*?\n    \}\)\n' ''; r2 deleted 1 1
eq "deleted entry" "$P" "fail agent-fixable tests/CalcTest.kt: test fn \`Calc / keeps\` removed"

mkhead expected sed -i 's/assertEquals(3, add(1, 2))/assertEquals(4, add(1, 2))/' "$F"; r2 expected 0 1
eq "expected entry" "$P" "confirm agent-fixable tests/CalcTest.kt: expected value changed in \`Calc / adds\`: was 3, now 4"
eq "expected line" "$(jq '.entries[0].line' <<<"$OUT")" 4

mkhead dropped sed -i '/assertTrue/d' "$F"; r2 dropped 1 1
eq "dropped entry" "$P" "fail agent-fixable tests/CalcTest.kt: assertions in test \`Calc / keeps\` dropped from 2 to 1"

mkhead lint sed -i 's|^context|// ktlint-disable-next-line max-line-length\ncontext|' "$F"; r2 "lint no reason" 1 1
eq "lint entry" "$P" "fail agent-fixable tests/CalcTest.kt: \`ktlint-disable-next-line max-line-length\` added without a reason"
mkhead lint-ok sed -i 's|^context|// ktlint-disable-next-line max-line-length -- long names\ncontext|' "$F"; r2 "lint reasoned" 0 0

mkhead pitest sed -i 's|^fun add|// pitest off\nfun add|' "$R/src/Calc.kt"; r2 pitest 1 1
eq "pitest entry" "$P" "fail needs-human src/Calc.kt: mutation skip added: \`pitest off\` hides this code from R3"

# A4: does not balance -> needs-human, never a pass
mkhead unbalanced sed -i 's/assertEquals(4, add(2, 2))/assertEquals(4, add(2, 2)/' "$F"; r2 unbalanced 1 1
has "unbalanced entry" "$P" "fail needs-human tests/CalcTest.kt: file does not parse"
mkhead unterminated sh -c "echo 'val s = \"\"\"abc' >> '$F'"; r2 unterminated 1 1
has "unterminated entry" "$P" "fail needs-human tests/CalcTest.kt: file does not parse: unterminated raw string"
echo "mech-review adapter-file ok"
