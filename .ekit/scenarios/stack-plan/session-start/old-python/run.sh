#!/bin/bash
SPFX="$EKIT_PARENT_DIR/../fixtures"; source "$SPFX/lib.sh"
# a python older than 3.11, found without network: uv's installed ones (offline), else one on PATH
OLDPY=""
for v in 3.10 3.9; do
  p=$(HOME="$OLDHOME" UV_OFFLINE=1 uv python find --offline --no-project "$v" 2>/dev/null) && [[ -x $p ]] && { OLDPY=$p; break; }
  p=$(command -v "python$v") && { OLDPY=$p; break; }
done
[[ -n $OLDPY ]] || fail "unrunnable here: no python 3.9 or 3.10 (uv python install 3.9, or python3.9 on PATH)"
VER=$("$OLDPY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
"$OLDPY" -c 'import sys; sys.exit(sys.version_info >= (3, 11))' || fail "$OLDPY is not older than 3.11"
HERR="$PWD/hook.err"
# start <dir>: the SessionStart hook run by the old python; CTX, HRC
start() { P=$(jq -nc --arg c "$1" '{cwd: $c, session_id: "s1", hook_event_name: "SessionStart", source: "startup"}')
  RAW=$(cd "$1" && printf '%s' "$P" | CLAUDE_PLUGIN_ROOT="$KIT" "$OLDPY" "$KIT/scripts/session-start.py" 2>"$HERR"); HRC=$?
  hasnt "hook traceback" "$(cat "$HERR")" "Traceback"; eq "hook exit" "$HRC" 0
  CTX=$(jq -er .hookSpecificOutput.additionalContext <<<"$RAW") || fail "no additionalContext: $RAW"; }
sp() { grep '^\[ekit\] Stack plan' <<<"$CTX"; }

# a plan that is behind (an uncovered manifest), one that is clean, one that does not read: one line each time
for kind in behind clean bad; do
  newrepo "$kind"; put web/package.json '{}'
  case $kind in behind) put api/pyproject.toml '[project]'; stack web web ts current ;;
    clean) stack web web ts current ;; bad) stack web web ts done ;; esac
  commit base; start "$R"
  eq "$kind: one Stack plan line" "$(sp | lines)" 1
  has "$kind: needs 3.11" "$(sp)" "3.11"
  has "$kind: names this python" "$(sp)" "$VER"
  has "$kind: CI still runs it" "$(sp)" "CI still runs the drift check"
  hasnt "$kind: no drift lines" "$CTX" "drift at HEAD"; hasnt "$kind: no manifest line" "$CTX" "unchecked manifest"
  eval "CTX_$kind=\$CTX"
done
# the other session lines are unchanged: the same as a repo with no plan, which adds nothing
newrepo none; put web/package.json '{}'; put api/pyproject.toml '[project]'; commit base; start "$R"
hasnt "no plan: nothing" "$CTX" "Stack plan"
eq "other lines unchanged" "$(grep -v '^\[ekit\] Stack plan' <<<"$CTX_behind" | sed "s#$PWD/behind#REPO#g")" "$(sed "s#$PWD/none#REPO#g" <<<"$CTX")"
# the drift command itself on this python: a usage error that says so, never clean
newrepo cli; put web/package.json '{}'; stack web web ts current; commit base
OUT=$("$OLDPY" -I "$MR" drift --repo "$R" --base "$C" --head "$C" 2>err); rc=$?
eq "drift on $VER: exit" "$rc" 2; has "drift on $VER: says 3.11" "$(cat err)" "3.11"; hasnt "drift traceback" "$(cat err)" "Traceback"
hasnt "drift on $VER: never pass" "$(jq -r .summary <<<"$OUT" 2>/dev/null)" "pass"
echo "stack-plan/session-start/old-python ok ($VER)"
