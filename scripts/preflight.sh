#!/bin/bash
# Environment preflight: one line per problem, with fallback. Checks are gated on project markers.
# Usage: preflight.sh [--quiet] [dir]   (--quiet: print problems only)
quiet=0; [[ $1 == --quiet ]] && { quiet=1; shift; }
dir="${1:-$PWD}"
have() { command -v "$1" >/dev/null 2>&1; }
warn() { echo "⚠ $1"; }
good() { (( quiet )) || echo "ok $1"; }
in_file() { [[ -f "$dir/$1" ]] && grep -q "$2" "$dir/$1"; }
# to <secs> <cmd...>: bounded where the host can bound it. macOS ships no `timeout` (coreutils has gtimeout; perl is there).
to() {
  local s="$1"; shift
  if have timeout; then timeout "$s" "$@"
  elif have gtimeout; then gtimeout "$s" "$@"
  elif have perl; then perl -e 'alarm shift; exec @ARGV' "$s" "$@"
  else "$@"; fi
}

have python && good python || warn "python: missing → use python3"
have jq && good jq || warn "jq: missing → python3 -c 'import json'"
have rg && good rg || warn "rg: missing → grep -rn / find"

# a python project with dependencies to install; a pyproject.toml that only configures tools (pytest, ruff) is not one
if [[ -f $dir/requirements.txt ]] || in_file pyproject.toml '^\[project\]\|^\[tool\.poetry\|^\[tool\.uv\|^\[build-system\]'; then
  [[ -d $dir/.venv ]] && good venv || warn "venv: no .venv → uv sync, then uv run <cmd> (or python3 -m venv .venv)"
fi

if [[ -f $dir/Cargo.toml ]]; then
  have cargo && good cargo || warn "cargo: missing → Cargo.toml present; rust build/test can't run here"
fi

if [[ -f $dir/package.json ]]; then
  want="$(grep -o '"node"[[:space:]]*:[[:space:]]*"[^"]*"' "$dir/package.json" | sed 's/.*:[[:space:]]*"//;s/"$//')"
  if [[ -n $want ]]; then
    if ! have node; then warn "node: missing → engines $want"
    else
      v="$(node -v)"; need="$(grep -o '[0-9]\+' <<<"$want" | head -1)"; got="$(grep -o '[0-9]\+' <<<"$v" | head -1)"
      (( got >= need )) && good node || warn "node: $v < engines $want → nvm use $need"
    fi
  fi
fi

if compgen -G "$dir/Dockerfile" >/dev/null || compgen -G "$dir/*compose*.y*ml" >/dev/null; then
  if ! have docker; then warn "docker: missing → container tests → verification debt"
  elif err="$(to 5 docker ps 2>&1 >/dev/null)"; then good docker
  else warn "docker: unusable (${err:0:80}) → container tests → verification debt"
  fi
fi

# scenario drivers: only the tools this repo's scenarios run (their scripts; SCENARIO.md prose does not count)
sdir=""; for d in .ekit/scenarios .ek/scenarios; do [[ -d $dir/$d ]] && { sdir="$dir/$d"; break; }; done
uses() { [[ -n $sdir ]] && grep -rqsw --exclude='*.md' -- "$1" "$sdir"; }
# runs <tool>: the tool in command position (line start, after ; | & ( ` or a shell keyword), so the word in a string
# or in another language's code (`expect(x)` in a JS fixture) is not a use. A miss here only costs the early warning.
runs() {
  [[ -n $sdir ]] && grep -rqsE --exclude='*.md' \
    -e "(^|[;|&(\`]|(^|[[:space:]])(if|while|until|then|do|else|exec|!))[[:space:]]*$1([[:space:]]|\$)" "$sdir"
}

for t in tmux expect curl; do
  if runs "$t"; then
    have "$t" && good "$t" || warn "$t: missing → scenarios needing $t can't run here → human verdict / verification debt"
  fi
done

if uses playwright || in_file package.json playwright || in_file pyproject.toml playwright || in_file requirements.txt playwright; then
  found=0; [[ -x ${CHROME_BIN:-} ]] && found=1
  # Playwright's browser cache: Linux, macOS, or wherever PLAYWRIGHT_BROWSERS_PATH points
  for c in "${PLAYWRIGHT_BROWSERS_PATH:-}" "$HOME/.cache/ms-playwright" "$HOME/Library/Caches/ms-playwright"; do
    [[ -n $c ]] && compgen -G "$c/chromium*" >/dev/null && found=1
  done
  if (( found )); then good playwright
  else warn "playwright: no chromium in the ms-playwright cache or \$CHROME_BIN → npx playwright install chromium"
  fi
fi

if have gh; then
  to 5 gh auth status >/dev/null 2>&1 && good gh || warn "gh: not authed → user runs: ! gh auth login"
  (( quiet )) || echo "note gh issue view: always pass --json (plain output errors on Projects classic)"
fi

if [[ -d $dir/.git ]]; then
  [[ -w $dir/.git ]] && good git || warn "git: .git read-only (sandbox) → commits need unsandboxed run"
fi

if have python3; then
  python3 -c "import socket;socket.socket().bind(('127.0.0.1',0))" 2>/dev/null && good loopback \
    || warn "loopback: bind 127.0.0.1 blocked (sandbox) → server/e2e tests need unsandboxed run"
fi
exit 0
