# shared setup for the verify-defaults scenarios (#61; sourced, not a scenario). cwd = the scenario's temp dir.
# The install is stack-plan's: a clone of the kit ($KIT); every hook is fired as Claude Code fires it, the command
# read from the clone's hooks/hooks.json, the payload on stdin and CLAUDE_PLUGIN_ROOT = the clone.
VDFX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPFX="$VDFX/../../../fixtures"; source "$SPFX/lib.sh"
TV="$KIT/scripts/task-verify.py"
HERR="$PWD/hook.err"
hookcmd() { jq -er --arg e "$1" '.hooks[$e][0].hooks[0].command' "$KIT/hooks/hooks.json" || fail "no $1 hook in the kit"; }
# start <dir> <session|-> [wrapper...]: SessionStart (`-`: no session_id in the payload; SRC: its source, default
# startup); CTX, HRC, VD (its Verify lines)
start() { local d=$1 s=$2 p; shift 2
  p=$(jq -nc --arg c "$d" --arg s "$s" --arg src "${SRC:-startup}" '{cwd: $c, hook_event_name: "SessionStart", source: $src}
    + (if $s == "-" then {} else {session_id: $s} end)')
  RAW=$(cd "$d" && printf '%s' "$p" | CLAUDE_PLUGIN_ROOT="$KIT" "$@" bash -c "$(hookcmd SessionStart)" 2>"$HERR"); HRC=$?
  hasnt "hook traceback" "$(cat "$HERR")" "Traceback"; eq "hook exit" "$HRC" 0
  CTX=$(jq -er .hookSpecificOutput.additionalContext <<<"$RAW") || fail "no additionalContext: $RAW"
  VD=$(grep '^\[ekit\] Verify defaults' <<<"$CTX"); }
# declared <session>: the commands the session's store holds, read back with task-verify (before any run), sorted
declared() { (cd "$R" && python3 -I "$TV" --repo "$R" check "$1" 2>&1) | sed -n 's/^`\(.*\)`: no run recorded$/\1/p' | sort; }
# none_declared <label> <session>: task-verify finds no command declared for the session
none_declared() { local o; o=$(cd "$R" && python3 -I "$TV" --repo "$R" check "$2" 2>&1)
  has "$1: nothing declared" "$o" "no verify command was declared for this session"; }
# shown <cmd>: the run line the context gives for a declared command (the last backticked part of its line)
shown() { grep -F "[ekit] Verify defaults: \`$1\` (" <<<"$VD" | sed -E 's/.*\): `(.*)`$/\1/'; }
# adapter files a user writes. web_adapter <file>: ekit's ts.toml renamed `web`, with a build and a lint command
web_adapter() { mkdir -p "$(dirname "$R/$1")"
  sed -e 's/^name = "ts"/name = "web"/' -e 's/^build = "".*/build = "npm run build"/' -e 's/^lint = ""$/lint = "npx eslint ."/' \
    "$KIT/scripts/mech_review/adapters/ts.toml" > "$R/$1"; grep -q '^build = "npm run build"' "$R/$1" || fail "web adapter"; }
# tool_adapter <name> [commands table]: the kt fixture under .ekit/adapters/<name>.toml (manifest build.gradle.kts),
# no [run]; with the table text appended as given
tool_adapter() { mkdir -p "$R/.ekit/adapters"; sed "s/^name = \"kt\"/name = \"$1\"/" "$SPFX/kt.toml" > "$R/.ekit/adapters/$1.toml"
  [[ -n ${2-} ]] && printf '\n%s\n' "$2" >> "$R/.ekit/adapters/$1.toml"; return 0; }
