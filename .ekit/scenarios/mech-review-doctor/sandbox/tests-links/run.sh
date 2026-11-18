#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_PARENT_DIR/fixtures/sandbox.sh"

# a fresh repo whose tests/ holds one tracked link: link_repo <name> <link path under tests/> <target>; sets R
n=0
link_repo() { n=$((n + 1)); R="$PWD/r$n-$1"; py_repo "$R"; mkdir -p "$(dirname "$R/tests/$2")"; ln -s "$3" "$R/tests/$2"; commit "$R" base
  [[ "$(git -C "$R" ls-files -s "tests/$2" | cut -c1-6)" == 120000 ]] || fail "$1: tests/$2 is not a tracked link"
  plain_ok "$R" "$1"; }

# 2. links mutmut's copy cannot follow: prompt, named, no hang
bad_link() { link_repo "$1" "$2" "$3"; local s=$SECONDS
  doc "$1" "$R"; sandbox_fail "$1"
  (( SECONDS - s < 30 )) || fail "$1: doctor took $((SECONDS - s))s, want a prompt answer"
  has "$1 copy fails" "$PROBLEM" "sandbox cannot be built"
  has "$1 names the link" "$PROBLEM" "\`tests/$2\`"; }
bad_link up up ..
bad_link nested sub/root ../..
bad_link dangling gone nowhere/data.txt

# 3. links to existing paths outside the repo are fine
link_repo hosts hosts /etc/hosts; doc hosts "$R"; sandbox_ok hosts
mkdir -p "$PWD/elsewhere"; echo data > "$PWD/elsewhere/data.txt"
link_repo outside-dir ext "$PWD/elsewhere"; doc outside-dir "$R"; sandbox_ok outside-dir
echo "doctor tests-links ok"
