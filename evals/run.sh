#!/bin/bash
# Run the skill evals: evals/run.sh [claude plugin eval options], e.g. evals/run.sh --case 'triage-*' -j 4
# macOS: /usr/bin/git is a shim that asks xcrun for the real binary, and xcrun cannot write its cache inside the eval
# sandbox ("Failed to locate 'git'"). The real git's directory goes first on PATH, so no case needs the shim.
# Linux: the harness makes each run's scaffold under os.tmpdir()/claude-eval-*, and its Bash sandbox denies writes under
# /tmp, /var/tmp and /dev/shm, so the agent under test cannot commit in its own repo. TMPDIR goes to a root outside
# them (~/.cache/ekit-eval/tmp, made if missing) unless the caller's TMPDIR is outside them already. The sandbox also
# denies reads of that whole root, so nothing the agent must run lives there.
# Git hooks: the sandbox turns every one off (core.hooksPath=/dev/null and hook.<name>.enabled=false at command-line
# scope; seen on Linux, CLI 2.1.332, macOS not checked), so a scaffold's ref hooks would never write the verdict its
# regex graders read. On every OS evals/git-shim.sh goes first on PATH as `git` (in ~/.cache/ekit-eval/bin, outside the
# temp root): it runs the real git, then the case's verdict script whenever a ref moved (its header).
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
mkdir -p "$cache/bin"
bin="$(cd "$cache/bin" && pwd -P)"
case "$bin/" in
  "${TMPDIR:-/nonexistent}"/*) echo "evals/run.sh: TMPDIR ($TMPDIR) holds $bin, which the sandbox then cannot read" >&2
    exit 2 ;;
esac
cp evals/git-shim.sh "$bin/git.new" && chmod +x "$bin/git.new" && mv -f "$bin/git.new" "$bin/git"
PATH="$bin:$PATH"
if [[ -x /nix/var/nix/profiles/default/bin/git ]]; then  # the agent's shell PATH starts with it (CLI 2.1.332)
  echo "evals/run.sh: warning: /nix/var/nix/profiles/default/bin/git runs ahead of the git shim: verdicts go stale" >&2
fi
exec claude plugin eval . --judge-model claude-opus-5-5 --scaffold --allow-tools Bash Edit Write "$@"
