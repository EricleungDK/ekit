#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_PARENT_DIR/fixtures/mutmut.sh"

mk_py_repo
# the repo already configures mutmut itself
printf '\n[tool.mutmut]\nsource_paths = ["src"]\nalso_copy = ["docs", "scripts"]\n' >> "$R/pyproject.toml"
git -C "$R" commit -qam "own mutmut config"; BASE=$(git -C "$R" rev-parse HEAD)
head_both
before=$(git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD; cat "$R/pyproject.toml")

out=$(mutants_run "$BASE" "$HEAD_BOTH"); rc=$?
eq "own-config exit" "$rc" 0
eq "own-config R3" "$(jq -r .checks.R3.status <<<"$out")" "n/a"
has "own-config note names the table" "$(jq -r .checks.R3.note <<<"$out")" "[tool.mutmut]"
has "own-config note is env" "$(jq -r .checks.R3.note <<<"$out")" "(env)"
eq "own-config entries" "$(jq -r '.entries | length' <<<"$out")" 0
eq "own-config summary" "$(jq -r .summary <<<"$out")" "pass $HEAD_BOTH (0 fail, 0 confirm; ran: none; skipped: R1 R2 R4; n/a: R3)"
eq "checkout untouched" "$(git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD; cat "$R/pyproject.toml")" "$before"
echo "own mutmut config n/a ok"
