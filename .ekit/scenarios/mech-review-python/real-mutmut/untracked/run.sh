#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_PARENT_DIR/fixtures/mutmut.sh"

mk_py_repo
# a test that needs local.cfg; the file sits in the checkout but was never committed
printf 'from pathlib import Path\n\n\ndef test_local_cfg():\n    assert (Path(__file__).resolve().parent.parent / "local.cfg").read_text() == "mode=x\\n"\n' > "$R/tests/test_local.py"
git -C "$R" add tests/test_local.py; git -C "$R" commit -qm "test reads local.cfg"; BASE=$(git -C "$R" rev-parse HEAD)
printf 'mode=x\n' > "$R/local.cfg"
(cd "$R" && python3 -m pytest -q -p no:cacheprovider >/dev/null) || fail "tests should pass in the checkout with the untracked file"
head_both
before=$(git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD)
eq "untracked before" "$(git -C "$R" status --porcelain)" "?? local.cfg"

# misuse: R3 must not pick up the untracked file; the baseline fails and says so, mutants not run
out=$(mutants_run "$BASE" "$HEAD_BOTH"); rc=$?
eq "untracked exit" "$rc" 1
eq "untracked R3" "$(jq -r .checks.R3.status <<<"$out")" fail
eq "untracked note" "$(jq -r .checks.R3.note <<<"$out")" "baseline tests fail at head: mutants not run"
eq "untracked entries" "$(jq -r '[.entries[] | "\(.check):\(.class):\(.problem)"] | join(" | ")' <<<"$out")" "R3:agent-fixable:baseline tests fail at head: mutants not run"
has "untracked log names the test" "$(cat mr.err)" "test_local_cfg"
eq "checkout untouched" "$(git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD)" "$before"
eq "untracked file kept" "$(cat "$R/local.cfg")" "mode=x"

# once local.cfg is tracked (a top-level entry), it reaches the copy and the mutants run
git -C "$R" add local.cfg; git -C "$R" commit -qm "track local.cfg"; TRACKED=$(git -C "$R" rev-parse HEAD)
out=$(mutants_run "$BASE" "$TRACKED"); rc=$?
check_missed "$out" "$rc" "$TRACKED" "tracked"
echo "untracked file stays out ok"
