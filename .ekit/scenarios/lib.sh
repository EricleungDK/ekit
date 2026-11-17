# shared helpers for ekit dogfood scenarios (sourced; not a scenario). Needs EKIT_REPO, cwd = temp dir.
set -u
fail() { echo "ASSERT FAILED: $*" >&2; exit 1; }
eq() { [[ "$2" == "$3" ]] || fail "$1: expected [$3] got [$2]"; }
has() { [[ "$2" == *"$3"* ]] || fail "$1: expected output to contain [$3], got [$2]"; }
# line count of stdin; BSD wc pads it with spaces, so strip them before eq
lines() { wc -l | tr -d '[:space:]'; }
hasnt() { [[ "$2" != *"$3"* ]] || fail "$1: output must not contain [$3], got [$2]"; }
export EKIT_STATE="$PWD/state"; mkdir -p "$EKIT_STATE"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
OLDHOME="$HOME"; export HOME="$PWD/home"; mkdir -p "$HOME"
RUNNER="$EKIT_REPO/scripts/scenarios.py"
# sample git repo, no kit yet
mk_repo() { SAMPLE="$PWD/sample"; rm -rf "$SAMPLE"; mkdir -p "$SAMPLE"; git -C "$SAMPLE" init -q -b main
  echo "print('hi')" > "$SAMPLE/app.py"; git -C "$SAMPLE" add -A; git -C "$SAMPLE" commit -qm init; }
# real user install (cloud installer) into the sample repo
install_kit() { bash "$EKIT_REPO/cloud/install.sh" "$SAMPLE" >/dev/null || fail "install.sh failed"
  [[ -f $SAMPLE/.claude/settings.json ]] || fail "no .claude/settings.json after install"; }
# add a scenario to the sample: add_scn <id> <exit-code> [documented=1]
add_scn() { local d="$SAMPLE/.ekit/scenarios/$1"; mkdir -p "$d"
  printf '#!/bin/bash\necho scenario-%s\nexit %s\n' "$1" "$2" > "$d/run.sh"
  [[ "${3:-1}" == 1 ]] && printf '# %s\n- story: s\n- covers: c\n- steps: x\n- expected: y\n' "$1" > "$d/SCENARIO.md"; return 0; }
commit_all() { git -C "$SAMPLE" add -A; git -C "$SAMPLE" commit -qm "${1:-c}"; }
# the installed hook command for an event, read from the sample's settings.json
hook_cmd() { jq -er --arg e "$1" '.hooks[$e][0].hooks[0].command' "$SAMPLE/.claude/settings.json" || fail "no $1 hook installed"; }
# run installed hook: hook <event> <session> [stop_hook_active] [last assistant message] [more payload fields, a JSON object]
# what the Finish gate asks before a done report: declare a verify command for the session, then run it green
# on the current files: verify <session> [command]
verify() { local tv="$EKIT_REPO/scripts/task-verify.py" c="${2:-python3 app.py}"
  (cd "$SAMPLE" && CLAUDE_CODE_SESSION_ID="$1" python3 -I "$tv" declare -- "$c" >/dev/null 2>&1) || fail "verify declare failed: $c"
  (cd "$SAMPLE" && python3 -I "$tv" run -- "$c" >/dev/null 2>&1) || fail "verify run failed: $c"; }
REPORT=$'## Finish: done\n| Criterion | Status | Evidence |'
# what Claude Code puts on a Stop payload while a subagent of the session still runs
RUNNING='{"background_tasks":[{"id":"a1","type":"subagent","status":"running","description":"unit","agent_type":"general-purpose"}]}'
hook() { local p x="${5:-}"; [[ -n $x ]] || x='{}'
  p=$(jq -nc --arg s "$2" --arg c "$SAMPLE" --argjson a "${3:-false}" --arg e "$1" --arg m "${4:-}" --argjson x "$x" '{session_id:$s,cwd:$c,hook_event_name:$e,stop_hook_active:$a} + (if $m == "" then {} else {last_assistant_message:$m} end) + $x')
  (cd "$SAMPLE" && printf '%s' "$p" | bash -c "$(hook_cmd "$1")"); }
# user types /orchestrate-agent (cloud install name): arm <session>
arm() { local p; p=$(jq -nc --arg s "$1" --arg c "$SAMPLE" '{session_id:$s,cwd:$c,hook_event_name:"UserPromptSubmit",prompt:"/orchestrate-agent do x"}')
  (cd "$SAMPLE" && printf '%s' "$p" | bash -c "$(hook_cmd UserPromptSubmit)"); }
