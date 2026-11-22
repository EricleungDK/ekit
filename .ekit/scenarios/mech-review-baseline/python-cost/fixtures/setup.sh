# shared setup for the python shard-count scenarios (sourced after lib.sh; not a scenario). cwd = the scenario's temp dir.
# The kit as a user gets it (a clone); a fake mutmut + pytest (fake_mutmut.py, see its header) as MECH_TEST_STUB.
PCFX="$EKIT_REPO/.ekit/scenarios/mech-review-baseline/python-cost/fixtures"
git -C "$EKIT_REPO" diff HEAD --quiet -- scripts || fail "the kit has uncommitted changes under scripts/: commit them, then run again"
KIT="$PWD/kit"; git clone -q "$EKIT_REPO" "$KIT" || fail "git clone of the kit failed"
MR="$KIT/scripts/mech-review.py"
STUB="$PWD/fake-mutmut"; cp "$PCFX/fake_mutmut.py" "$STUB"; chmod +x "$STUB"
export FAKE_ARGV="$PWD/argv"

# the user's repo: src/calc/core.py holds f1..f8 (`return n+K`), src/calc/{a,b,c,d}.py one function each
R="$PWD/repo"; mkdir -p "$R/src/calc" "$R/tests"; git -C "$R" init -q -b main
printf '[project]\nname = "calc"\nversion = "0.0.1"\n\n[tool.pytest.ini_options]\npythonpath = ["src"]\n' > "$R/pyproject.toml"
: > "$R/src/calc/__init__.py"
for k in 1 2 3 4 5 6 7 8; do printf 'def f%s(n):\n    return n+%s\n\n\n' "$k" "$k"; done > "$R/src/calc/core.py"
for m in a b c d; do printf 'def %s(n):\n    return n+1\n' "$m" > "$R/src/calc/$m.py"; done
printf 'from calc.core import f1\n\n\ndef test_all():\n    assert f1(1) == 2\n' > "$R/tests/test_core.py"
git -C "$R" add -A; git -C "$R" commit -qm base; B=$(git -C "$R" rev-parse HEAD)
# a head from base: pr_head <branch> <how many of core's functions change> [other modules that change...]; sets H
pr_head() { local br="$1" n="$2" k m; shift 2; git -C "$R" checkout -q -b "$br" "$B"
  for ((k = 1; k <= n; k++)); do sed -i.bak "s/return n+$k\$/return n + $k/" "$R/src/calc/core.py"; done
  for m in "$@"; do printf 'def %s(n):\n    return n + 1\n' "$m" > "$R/src/calc/$m.py"; done
  rm -f "$R"/src/calc/*.bak; git -C "$R" add -A; git -C "$R" commit -qm "$br"; H=$(git -C "$R" rev-parse HEAD); }

bl() { MECH_TEST_STUB="$STUB" python3 -I "$MR" baseline --repo "$R" --base "$B" --head "$H" --stack python --test-paths 'tests/**' "$@"; }
mut() { MECH_TEST_STUB="$STUB" python3 -I "$MR" mutants --repo "$R" --base "$B" --head "$H" --stack python --test-paths 'tests/**' "$@"; }
mrg() { python3 -I "$MR" merge --repo "$R" --base "$B" --head "$H" --stack python "$@"; }
note() { jq -r .checks.R3.note <<<"$1"; }
# a baseline run into bl.json, failing on a non-zero exit or a traceback: blj [env...] [-- flags...]; prints
# "run count mutants"
blj() { local e=() rc; while [[ $# -gt 0 && $1 != -- ]]; do e+=("$1"); shift; done; [[ $# -gt 0 ]] && shift
  env "${e[@]}" MECH_TEST_STUB="$STUB" python3 -I "$MR" baseline --repo "$R" --base "$B" --head "$H" --stack python \
    --test-paths 'tests/**' "$@" > bl.json 2>err.txt; rc=$?; [[ $rc == 0 ]] || fail "baseline exit $rc: $(cat err.txt)"
  hasnt "baseline traceback" "$(cat err.txt)" "Traceback"; jq -r '"\(.run) \(.count) \(.mutants)"' bl.json; }
# run the N shards of a baseline result as CI does, then merge: shards_merge <baseline.json> [env...] [-- flags...]
# (flags go to every shard, as the workflow passes max-mutants to each); sets MOUT, MRC; ./ran lists each mutant run
shards_merge() { local blf="$1" n k e=() f=() envs=(); shift
  while [[ $# -gt 0 && $1 != -- ]]; do e+=("$1"); shift; done; [[ $# -gt 0 ]] && shift; f=("$@")
  n=$(jq -r .count "$blf"); : > ran
  for ((k = 0; k < n; k++)); do
    env "${e[@]}" FAKE_RAN="$PWD/ran" MECH_TEST_STUB="$STUB" python3 -I "$MR" mutants --repo "$R" --base "$B" --head "$H" \
      --stack python --test-paths 'tests/**' --shard "$k/$n" "${f[@]}" > "shard$k.json" 2>"shard$k.err"
    hasnt "shard $k/$n traceback" "$(cat "shard$k.err")" "Traceback"; envs+=(--envelope "$k=shard$k.json")
  done
  MOUT=$(mrg --baseline "$blf" --shards "$n" "${envs[@]}"); MRC=$?; }
