#!/bin/bash
# Run the skill evals: evals/run.sh [claude plugin eval options], e.g. evals/run.sh --case 'triage-*' -j 4
# macOS: /usr/bin/git is a shim that asks xcrun for the real binary, and xcrun cannot write its cache inside the eval
# sandbox ("Failed to locate 'git'"). The real git's directory goes first on PATH, so no case needs the shim.
# Linux: the harness makes each run's scaffold under os.tmpdir()/claude-eval-*, and its Bash sandbox denies writes under
# /tmp, /var/tmp and /dev/shm, so the agent under test cannot commit in its own repo. TMPDIR goes to a root outside
# them (~/.cache/ekit-eval/tmp, made if missing) unless the caller's TMPDIR is outside them already. The sandbox also
# denies reads of that whole root, so nothing the agent must run lives there.
set -euo pipefail
cache="${XDG_CACHE_HOME:-$HOME/.cache}/ekit-eval"
if [[ $(uname) == Linux ]]; then
  tmp="$(CDPATH= cd "${TMPDIR:-/tmp}" 2>/dev/null && pwd -P || true)"
  case "$tmp/" in
    / | // | /tmp/* | /var/tmp/* | /dev/shm/*) tmp="$cache/tmp"; mkdir -p "$tmp" ;;
  esac
  export TMPDIR="$tmp"
fi
cd "$(dirname "$0")/.."
if [[ $(uname) == Darwin ]] && real="$(xcrun --find git 2>/dev/null)"; then
  PATH="$(dirname "$real"):$PATH"
  export xcrun_nocache=1  # a shell profile may put /usr/bin first again: then the shim at least skips its cache
fi
exec claude plugin eval . --judge-model claude-opus-5-5 --scaffold --allow-tools Bash Edit Write "$@"
