# Minimal test helpers. Source from tests/*.test.sh.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILS=0
# The repos the tests build are throwaway: the machine's git config (commit signing, hooks, templates, default branch)
# must not reach them, and they need an identity of their own.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

# fakebin <dir> <tool...>: dir with symlinks to real tools only, for PATH isolation
fakebin() {
  local d="$1"; shift
  mkdir -p "$d"
  for t in bash sh env cat grep sed head tail tr cut dirname basename ls mkdir rm mktemp date sort timeout test printf wc stat sha1sum find "$@"; do
    local p; p="$(command -v "$t" 2>/dev/null)" && ln -sf "$p" "$d/$t"
  done
}

# stub <dir> <name> <script body>: fake executable
stub() { printf '#!/bin/bash\n%s\n' "$3" > "$1/$2"; chmod +x "$1/$2"; }

ok()   { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAILS=$((FAILS+1)); }
skip() { printf '  skip %s: %s\n' "$1" "$2"; }  # could not run here; never counted as ok

has()  { grep -qF -- "$2" <<<"$1" && ok "$3" || { fail "$3"; printf '       want: %s\n       got:\n%s\n' "$2" "$1"; }; }
lacks(){ grep -qF -- "$2" <<<"$1" && { fail "$3"; printf '       unwanted: %s\n' "$2"; } || ok "$3"; }
eq()   { [[ "$1" == "$2" ]] && ok "$3" || { fail "$3"; printf '       want: %s\n       got:  %s\n' "$2" "$1"; }; }

done_tests() { exit $(( FAILS > 0 )); }
