#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_PARENT_DIR/fixtures/mutmut.sh"
export MR_LIMIT=120

# repo whose docs/ holds a tracked symlink; tests load scripts/tool.py by path and do not read docs/
# links_repo <label> <link name> <link target> [gitignore line]
links_repo() { mk_py_repo 0
  [[ -n "${4:-}" ]] && printf '%s\n' "$4" > "$R/.gitignore"
  ln -s "$3" "$R/docs/$2"
  git -C "$R" add -A; git -C "$R" commit -qm "docs link $2"; BASE=$(git -C "$R" rev-parse HEAD)
  [[ -L "$R/docs/$2" ]] || fail "$1: link not in checkout"
  [[ "$(git -C "$R" ls-files -s "docs/$2" | cut -c1-6)" == 120000 ]] || fail "$1: link not tracked"
  head_both
  local before s; before=$(git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD); s=$SECONDS
  out=$(mutants_run "$BASE" "$HEAD_BOTH"); rc=$?
  [[ $rc != 124 ]] || fail "$1: mech-review hung (killed after ${MR_LIMIT}s)"
  hasnt "$1 no traceback" "$(cat mr.err)" "Traceback (most recent call last):
  File \"$MR\""
  check_missed "$out" "$rc" "$HEAD_BOTH" "$1"
  eq "$1 checkout untouched" "$(git -C "$R" status --porcelain; git -C "$R" rev-parse HEAD)" "$before"
  echo "$1: R3 done in $((SECONDS - s))s"; }

# dangling: the target is a gitignored build dir, absent at head
links_repo dangling html ../_build/html "_build/"
# same, with the gitignored target present in the user's checkout
mkdir -p "$R/_build/html"; echo x > "$R/_build/html/index.html"
out=$(mutants_run "$BASE" "$HEAD_BOTH"); rc=$?
[[ $rc != 124 ]] || fail "dangling+local target: mech-review hung"
check_missed "$out" "$rc" "$HEAD_BOTH" "dangling+local target"
# a link to a parent dir (a copy that follows it never ends)
links_repo parent up ..
# a link to the repo root by absolute-free path two levels up from a nested docs dir
mk_py_repo 0; mkdir -p "$R/docs/api"; ln -s ../.. "$R/docs/api/root"; git -C "$R" add -A; git -C "$R" commit -qm nested; BASE=$(git -C "$R" rev-parse HEAD)
head_both
out=$(mutants_run "$BASE" "$HEAD_BOTH"); rc=$?
[[ $rc != 124 ]] || fail "nested parent link: mech-review hung"
check_missed "$out" "$rc" "$HEAD_BOTH" "nested parent link"
echo "docs symlinks ok"
