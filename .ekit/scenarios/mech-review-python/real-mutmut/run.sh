#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_REPO/.ekit/scenarios/mech-review-python/real-mutmut/fixtures/mutmut.sh"

mk_py_repo
head_both
before=$(git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD)

# 1, 3: tests that read docs/ and load scripts/ by path pass in mutmut's copy; the weak change is MISSED with file and line
out=$(mutants_run "$BASE" "$HEAD_BOTH"); rc=$?
check_missed "$out" "$rc" "$HEAD_BOTH" "both"
eq "both summary" "$(jq -r .summary <<<"$out")" "fail $HEAD_BOTH (2 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)"

# text format: the same result, summary first
txt=$(mutants_run "$BASE" "$HEAD_BOTH" --format text); rc=$?
eq "text exit" "$rc" 1
eq "text first line" "$(head -1 <<<"$txt")" "fail $HEAD_BOTH (2 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)"
has "text names location" "$txt" "src/calc/core.py:6"

# 3: a well-tested change is caught: R3 pass, no entries (mutated sources were not overwritten by the copy)
git -C "$R" checkout -q -b good "$BASE"
printf 'def add(a, b):\n    return b + a\n\n\ndef is_positive(n):\n    return n > 0\n' > "$R/src/calc/core.py"
git -C "$R" commit -qam good; GOOD=$(git -C "$R" rev-parse HEAD)
out=$(mutants_run "$BASE" "$GOOD"); rc=$?
eq "good exit" "$rc" 0
eq "good R3" "$(jq -r .checks.R3.status <<<"$out")" pass
has "good note" "$(jq -r .checks.R3.note <<<"$out")" "0 missed in the diff"
has "good caught" "$(jq -r .checks.R3.note <<<"$out")" "caught"
eq "good entries" "$(jq -r '.entries | length' <<<"$out")" 0
eq "good summary" "$(jq -r .summary <<<"$out")" "pass $GOOD (0 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)"

# flat layout (package at the repo root, tests read docs/): a well-tested change is caught too
R="$PWD/flat"; mkdir -p "$R/calc" "$R/tests" "$R/docs"; git -C "$R" init -q -b main
printf '[project]\nname = "calc"\nversion = "0.0.1"\n' > "$R/pyproject.toml"
: > "$R/calc/__init__.py"; printf 'def add(a, b):\n    return a + b\n' > "$R/calc/core.py"
printf 'adds numbers\n' > "$R/docs/about.md"
printf 'from pathlib import Path\n\nfrom calc.core import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n    assert add(-1, 1) == 0\n\n\ndef test_docs():\n    assert (Path(__file__).resolve().parent.parent / "docs" / "about.md").read_text() == "adds numbers\\n"\n' > "$R/tests/test_core.py"
git -C "$R" add -A; git -C "$R" commit -qm base; FB=$(git -C "$R" rev-parse HEAD)
sed -i.bak 's/a + b/b + a/' "$R/calc/core.py"; rm "$R/calc/core.py.bak"; git -C "$R" commit -qam h; FH=$(git -C "$R" rev-parse HEAD)
out=$(mutants_run "$FB" "$FH"); rc=$?
eq "flat exit" "$rc" 0
eq "flat R3" "$(jq -r .checks.R3.status <<<"$out")" pass
eq "flat summary" "$(jq -r .summary <<<"$out")" "pass $FH (0 fail, 0 confirm; ran: R3; skipped: R1 R2 R4)"

R="$PWD/repo"
eq "checkout untouched" "$(git -C "$R" checkout -q both && git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD)" "$before"
echo "mech-review python real mutmut ok"
