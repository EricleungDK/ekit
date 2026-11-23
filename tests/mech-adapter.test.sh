#!/bin/bash
# Adapter files (#16): TS described by the shipped adapter file passes every TS R2 suite with its assertions unchanged
# (mech-ts.test.sh: adapter unit section and the CLI R2 cases; the ts cases of mech-mutation-skip.test.sh), and a file
# that does not balance is needs-human there (agent-fixable with the built-in ts adapter).
source "$(dirname "$0")/lib.sh"
MR="$ROOT/scripts/mech-review.py"
TS_FILE="$ROOT/scripts/mech_review/adapters/ts.toml"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

for suite in mech-ts mech-mutation-skip; do
  out=$(MECH_ADAPTER_TS="$TS_FILE" bash "$ROOT/tests/$suite.test.sh" 2>&1); rc=$?
  eq "$rc" 0 "$suite passes with TS from the adapter file"
  (( rc == 0 )) || grep -E 'FAIL|Traceback|Error' <<<"$out" | head -20
done

# the hook is live: a broken adapter file path makes the suite fail, so a pass above is the file's, not the built-in's
MECH_ADAPTER_TS="$T/none.toml" bash "$ROOT/tests/mech-ts.test.sh" >/dev/null 2>&1; rc=$?
eq "$rc" 1 "mech-ts fails when MECH_ADAPTER_TS names no file (the hook reaches the suite)"

# ...and reaches each suite's CLI cases: a copy of the file that words a skip differently fails mech-ts's CLI skip case
# (its unit section does not read that text); one that does not know Stryker's marker fails mech-mutation-skip's ts case
sed 's/^skipped_text = .*/skipped_text = "test `{name}` parked"/' "$TS_FILE" > "$T/reworded.toml"
out=$(MECH_ADAPTER_TS="$T/reworded.toml" bash "$ROOT/tests/mech-ts.test.sh" 2>&1)
has "$out" "FAIL it.skip says skipped" "mech-ts CLI cases read the adapter file (skip wording)"
has "$out" "ok   ts adapter: classify" "mech-ts unit section still passes on the reworded file"
grep -v '^skip_comments' "$TS_FILE" > "$T/no-stryker.toml"
out=$(MECH_ADAPTER_TS="$T/no-stryker.toml" bash "$ROOT/tests/mech-mutation-skip.test.sh" 2>&1)
has "$out" "FAIL ts Stryker disable: exit 1" "mech-mutation-skip ts cases read the adapter file (Stryker marker)"
has "$out" "ok   rust skip: exit 1" "mech-mutation-skip rust cases stay on the built-in"

# parity: a function named like a test call (`function test(`, `function it(`) declares, it is not a test
R="$T/decl"; mkdir -p "$R/tests"; git -C "$R" init -q -b main
cat > "$R/tests/a.test.ts" <<'EOF'
export async function test(a, b) {
  expect(a).toBe(b)
}
export function it(n, f) { f() }
it("x", () => { test(1, 1) })
EOF
git -C "$R" add -A; git -C "$R" commit -qm base; B=$(git -C "$R" rev-parse HEAD)
printf 'it("x", () => { expect(1).toBe(1) })\n' > "$R/tests/a.test.ts"
git -C "$R" commit -qam head; H=$(git -C "$R" rev-parse HEAD)
ents() { python3 -I "$MR" r2 --repo "$R" --base "$B" --head "$H" --stack ts --test-paths 'tests/**' "$@" \
  | jq -r '[.entries[] | [.severity, .line, .problem] | join("|")] | join(";")'; }
built=$(ents); file=$(ents --adapter "$TS_FILE")
lacks "$built" 'test fn `a` removed' "declared fns, built-in: \`function test(a, b)\` is not a test"
lacks "$built" 'test fn `n` removed' "declared fns, built-in: \`function it(n, f)\` is not a test"
eq "$file" "$built" "declared fns: the adapter file gives the built-in's entries"

# unbalanced file: needs-human from the adapter file, agent-fixable from the built-in
R="$T/unbalanced"; mkdir -p "$R/tests"; git -C "$R" init -q -b main
printf 'it("a", () => {\n  expect(1).toBe(1);\n});\n' > "$R/tests/a.test.ts"
git -C "$R" add -A; git -C "$R" commit -qm base; B=$(git -C "$R" rev-parse HEAD)
printf 'it("a", () => {\n  expect(1).toBe(1);\n' > "$R/tests/a.test.ts"
git -C "$R" commit -qam head; H=$(git -C "$R" rev-parse HEAD)
r2() { python3 -I "$MR" r2 --repo "$R" --base "$B" --head "$H" --stack ts --test-paths 'tests/**' "$@"; }
out=$(r2 --adapter "$TS_FILE"); rc=$?
eq "$rc" 1 "unbalanced, adapter file: exit 1"
eq "$(jq -r '[.entries[] | [.severity, .class, .line, .problem] | join("|")] | join(";")' <<<"$out")" \
   "fail|needs-human|1|file does not parse: \`{\` is never closed (line 1)" "unbalanced, adapter file: needs-human fail"
out=$(r2)
eq "$(jq -r '.entries[0].class' <<<"$out")" agent-fixable "unbalanced, built-in ts: agent-fixable as before"

# repo-defined adapter (#17): a repo with only a pom.xml and .ekit/adapters/maven.toml for it resolves to that adapter
# (its target-os too), and `r2 --stack maven` judges with the base's file, no --adapter
R="$T/repo-adapter"; cp -R "$ROOT/tests/fixtures/repo-adapter" "$R"; git -C "$R" init -q -b main
git -C "$R" add -A; git -C "$R" commit -qm base; B=$(git -C "$R" rev-parse HEAD)
out=$(python3 -I "$MR" resolve --repo "$R" --base "$B" --head "$B"); rc=$?
eq "$rc" 0 "repo adapter: resolve exit 0"
eq "$out" '{"stack": "maven", "project_dir": ".", "error": null, "target_os": "macos"}' "repo adapter: auto finds it by pom.xml"
python3 - "$R/tests/calc.mini" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace('  test("subtracts", {\n    assertTrue(sub(3, 1) == 2)\n  })\n', ""))
PY
sed -i 's/cases = \["test", "xtest"\]/cases = ["xtest"]/' "$R/.ekit/adapters/maven.toml"  # the PR's own file sees no test
git -C "$R" commit -qam head; H=$(git -C "$R" rev-parse HEAD)
out=$(python3 -I "$MR" r2 --repo "$R" --base "$B" --head "$H" --stack maven --test-paths 'tests/**'); rc=$?
eq "$rc" 1 "repo adapter: r2 --stack maven exit 1"
eq "$(jq -r '[.entries[] | [.severity, .file, .problem] | join("|")] | join(";")' <<<"$out")" \
   'fail|tests/calc.mini|test fn `Calc / subtracts` removed' "repo adapter: r2 judges with the base's adapter file"
out=$(python3 -I "$MR" resolve --repo "$R" --base "$H" --head "$H" --stack gradle); rc=$?
eq "$rc:$(jq -r .error <<<"$out")" "1:stack gradle: want auto, maven, python, rust or ts" "repo adapter: explicit names list it"

done_tests
