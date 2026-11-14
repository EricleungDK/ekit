#!/bin/bash
# Run the skill evals: evals/run.sh [claude plugin eval options], e.g. evals/run.sh --case 'triage-*' -j 4
# macOS: /usr/bin/git is a shim that asks xcrun for the real binary, and xcrun cannot write its cache inside the eval
# sandbox ("Failed to locate 'git'"). The real git's directory goes first on PATH, so no case needs the shim.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $(uname) == Darwin ]] && real="$(xcrun --find git 2>/dev/null)"; then
  PATH="$(dirname "$real"):$PATH"
fi
exec claude plugin eval . --judge-model claude-opus-5-5 --scaffold --allow-tools Bash Edit Write "$@"
