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

done_tests
