source "$(dirname "$0")/lib.sh"
# preflight.py as the SessionStart hook and the finish skill run it: a real process, PATH as the host has it.
# The cases (each check, its fallback, the install line per OS, the noreply warning) are in tests/py/test_preflight.py.
PY="$(command -v python3)"; PF="$ROOT/scripts/preflight.py"
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT  # physical path: macOS temp dirs sit behind a symlink
unset CHROME_BIN PLAYWRIGHT_BROWSERS_PATH EKIT_SHELL
case "$(uname -s)" in Darwin) os=macOS; jq_line="brew install jq";; MINGW*|MSYS*|CYGWIN*) os=Windows; jq_line="winget install jqlang.jq";; *) os=Linux; jq_line="sudo apt install jq";; esac

# a PATH with python3 and no jq: the OS, the fallback and this OS's install line
B="$T/b1"; fakebin "$B" python3; P="$T/p1"; mkdir -p "$P"
out="$(PATH="$B" HOME="$T/home" "$PY" -I "$PF" "$P" 2>&1)"
eq "$(head -1 <<<"$out")" "os: $os" "the OS comes first"
has "$out" "jq: missing → python3 -c 'import json'; install: $jq_line" "jq missing → fallback and $os install line"
lacks "$out" "Traceback" "no traceback"

# --quiet prints the OS and problems only
out="$(PATH="$B" HOME="$T/home" "$PY" -I "$PF" --quiet "$P" 2>&1)"
lacks "$out" "ok " "--quiet: no ok lines"
has "$out" "os: $os" "--quiet: the OS line stays"

# --env: a probe of this process, and the shell it was run from (this suite's bash)
H="$T/envhome"; mkdir -p "$H"
eq "$(HOME="$H" XDG_CACHE_HOME= "$PY" -I "$PF" --env)" "Env: unsandboxed; shell: bash" "--env: unsandboxed, run from bash"
eq "$(ls "$H/.cache/ekit")" "" "--env: the probe file is removed"
eq "$(HOME="$T/none" XDG_CACHE_HOME=/dev/null/x "$PY" -I "$PF" --env)" "Env: sandboxed (no write outside the project); shell: bash" "--env: XDG_CACHE_HOME is the place probed"
done_tests
