#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_PARENT_DIR/fixtures/sandbox.sh"

# 1. tests read docs/usage.md; docs/html -> ../_build/html, _build/ gitignored: dangling in a fresh checkout
R="$PWD/link"; py_repo "$R"; docs_test "$R"; printf '_build/\n' > "$R/.gitignore"; ln -s ../_build/html "$R/docs/html"; commit "$R" base
[[ "$(git -C "$R" ls-files -s docs/html | cut -c1-6)" == 120000 ]] || fail "docs/html is not a tracked link"
plain_ok "$R" link
check_link() {
  doc "$1" "$R"; sandbox_fail "$1"
  has "$1 names the file" "$PROBLEM" 'docs/usage.md'
  has "$1 names the link" "$PROBLEM" 'docs/html'
  has "$1 hint: track the target" "$HINT" 'track its target'
  has "$1 hint: or remove the link" "$HINT" 'remove the link'; }
check_link dangling

# 2. the target built in the user's checkout (ignored): doctor reads HEAD, still a problem
mkdir -p "$R/_build/html"; echo built > "$R/_build/html/index.html"
check_link "built locally"

# 3. control: no link, the same docs test passes in the sandbox
C="$PWD/nolink"; py_repo "$C"; docs_test "$C"; commit "$C" base
doc nolink "$C"; sandbox_ok nolink
echo "doctor docs-link ok"
