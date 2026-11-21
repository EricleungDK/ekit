source "$(dirname "$0")/lib.sh"
# The hooks.json command as Claude Code runs it with sh (macOS, Linux, Git Bash on Windows): the plugin dir in the
# CLAUDE_PLUGIN_ROOT env var, the interpreters on PATH fakes. Its PowerShell part runs in tests/windows-smoke.py.
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT  # physical path: macOS temp dirs sit behind a symlink
PY="$(command -v python3 || command -v python)"
W="$(cd "$T" && { pwd -W 2>/dev/null || pwd -P; })"  # Git Bash: C:/... (a native Python cannot read /tmp/...)
KIT="$W/my kit's \$HOME"; mkdir -p "$KIT/scripts"  # a ' a $ and a space: none may break the command
cat > "$KIT/scripts/probe.py" <<'EOF'
import os, sys
print("ran", os.environ.get("EKIT_PY"), sys.argv[1:], repr(sys.stdin.read()))
sys.exit(2)
EOF
CMD="$("$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); import launcher; print(launcher.hook_command("probe.py", "--hook"))' "$ROOT/scripts")"
B="$T/bin"; mkdir -p "$B"
fake() {  # fake <name> old|new: old fails the version check, new runs the real Python (py drops its -3)
  if [[ $2 == old ]]; then printf '#!/bin/sh\nexit 1\n' > "$B/$1"
  else printf '#!/bin/sh\n[ "$1" = -3 ] && shift\nexec "%s" "$@"\n' "$PY" > "$B/$1"; fi
  chmod +x "$B/$1"
}
# the root as Claude Code gives it to sh: Git Bash gets /c/... (MSYS does not convert an argument holding a ' for a
# native Python), with Git's usr/bin on PATH, where cygpath is
CYG="$(command -v cygpath)"
ROOTV="$KIT"; HP="$B"
[[ -n $CYG ]] && { ROOTV="$(cygpath -u "$KIT")"; HP="$B:$(dirname "$CYG")"; }
hook() { printf '{"a": 1}' | PATH="$HP" CLAUDE_PLUGIN_ROOT="$ROOTV" "$SH" -c "$CMD" 2>"$T/err"; }
SH="$(command -v sh)"

fake python3 old; fake py new; fake python new
out="$(hook)"; eq "$?" "2" "sh: the script's exit code comes through"
eq "$out" "ran py -3 ['--hook'] '{\"a\": 1}'" "sh: python3 too old → py -3, stdin and args kept"
rm "$B/py"
eq "$(hook)" "ran python ['--hook'] '{\"a\": 1}'" "sh: no py → python"
rm "$B/python"
out="$(hook)"; eq "$?" "1" "sh: no Python 3.9+ → exit 1"
has "$(cat "$T/err")" "[ekit] no Python 3.9+ found: tried python3, py -3, python" "sh: one clear message"
done_tests
