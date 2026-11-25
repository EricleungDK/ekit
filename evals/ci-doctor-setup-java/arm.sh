# Sourced by each ci-doctor-setup-* setup.sh after its scaffold commit (#23). Arms the grader support: whenever HEAD or
# a ref moves (commit, reset, checkout, merge, rebase), verdict.py (beside this file, copied into .git/ekit-eval/) reads
# the end state at HEAD of the main checkout and writes .git/ekit-eval/verdict.txt, which the regex graders read.
# $1: the case's expect.json (verdict.py's header). The kit's path is data in a file, never shell text.
arm_verdict() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  mkdir -p .git/ekit-eval
  printf '%s' "$(cd "$here/../.." && pwd -P)" > .git/ekit-eval/kit
  printf '%s\n' "$1" > .git/ekit-eval/expect.json
  git rev-parse HEAD > .git/ekit-eval/start
  cp "$here/verdict.py" .git/ekit-eval/verdict.py
  # reference-transaction: every ref update; post-checkout: a switch of HEAD alone. Never fails the model's git command
  printf '#!/bin/sh\n[ "$1" = committed ] || exit 0\npython3 -I "$(git rev-parse --path-format=absolute --git-common-dir)/ekit-eval/verdict.py" >/dev/null 2>&1\nexit 0\n' > .git/hooks/reference-transaction
  printf '#!/bin/sh\npython3 -I "$(git rev-parse --path-format=absolute --git-common-dir)/ekit-eval/verdict.py" >/dev/null 2>&1\nexit 0\n' > .git/hooks/post-checkout
  chmod +x .git/hooks/reference-transaction .git/hooks/post-checkout
  python3 -I .git/ekit-eval/verdict.py  # the start state's verdict
}
