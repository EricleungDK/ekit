#!/bin/bash
source "$EKIT_PARENT_DIR/fixtures/lib.sh"
# hookev <event> <session> [last assistant message] [prompt]: the clone's hook for the event, as Claude Code fires it
hookev() { local p; p=$(jq -nc --arg e "$1" --arg s "$2" --arg c "$R" --arg m "${3-}" --arg q "${4-}" \
  '{hook_event_name: $e, session_id: $s, cwd: $c, stop_hook_active: false}
   + (if $m == "" then {} else {last_assistant_message: $m} end) + (if $q == "" then {} else {prompt: $q} end)')
  (cd "$R" && printf '%s' "$p" | CLAUDE_PLUGIN_ROOT="$KIT" bash -c "$(hookcmd "$1")"); }
stop_done() { hookev Stop "$1" "$REPORT"; }
# run_shown <cmd>: the agent runs the context's line for a default, exactly as shown, from the repo; its exit in RUN_RC
run_shown() { local l; l=$(shown "$1"); [[ -n $l ]] || fail "no run line shown for \`$1\`: $VD"
  (cd "$R" && bash -c "$l" >/dev/null 2>&1); RUN_RC=$?; }

# a repo whose one stack (an adapter file, in app/) names a build, a lint and a test; the test is red until the fix
newrepo app; put app/build.gradle.kts 'x'; put app/src.kt 'bad'
tool_adapter tool $'[commands]\ninstall = "touch INSTALLED"\nbuild = "test -f build.gradle.kts"\nlint = "test -s src.kt"\ntest = "grep -q ok src.kt"'
stack app app .ekit/adapters/tool.toml current; commit base
start "$R" g1
DEFS=$'cd app && grep -q ok src.kt\ncd app && test -f build.gradle.kts\ncd app && test -s src.kt'
eq "defaults declared" "$(declared g1)" "$DEFS"
hookev UserPromptSubmit g1 "" "/ekit:orchestrate-agent fix the app" >/dev/null || fail "arm hook failed"
# the agent's own per-task command, declared as before; a resumed session keeps it beside the defaults
OWN="python3 -c pass"
(cd "$R" && CLAUDE_CODE_SESSION_ID=g1 python3 -I "$TV" declare -- "$OWN" >/dev/null 2>&1) || fail "declare own command"
SRC=resume start "$R" g1
eq "own command stays alongside the defaults" "$(declared g1)" "$(printf '%s\n' "$DEFS" "$OWN" | sort)"
hasnt "resume: no install" "$CTX" "INSTALLED"

# work, then the finish report: held until each default and the own command ran green on the files as they are
put app/notes.txt 'work'
out=$(stop_done g1); has "nothing run: held" "$out" '"decision": "block"'
while IFS= read -r c; do has "nothing run: names \`$c\`" "$out" "$c"; done <<<"$DEFS"
(cd "$R" && python3 -I "$TV" run -- "$OWN" >/dev/null 2>&1) || fail "own command red"
out=$(stop_done g1); has "own only: held" "$out" '"decision": "block"'; has "own only: names the test" "$out" "cd app && grep -q ok src.kt"
hasnt "own only: own is not asked for" "$out" "$OWN"
# each default run with its shown line: build and lint green, test red -> held on the test alone
run_shown "cd app && test -f build.gradle.kts"; eq "build green" "$RUN_RC" 0
run_shown "cd app && test -s src.kt"; eq "lint green" "$RUN_RC" 0
run_shown "cd app && grep -q ok src.kt"; [[ $RUN_RC != 0 ]] || fail "the red test ran green through its shown line"
out=$(stop_done g1); has "test red: held" "$out" '"decision": "block"'; has "test red: names it" "$out" "cd app && grep -q ok src.kt"
hasnt "test red: build not asked" "$out" "cd app && test -f build.gradle.kts"
# the fix: the earlier passes are for other files, so every default and the own command run again
put app/src.kt 'ok'
out=$(stop_done g1); has "after the fix, stale: held" "$out" '"decision": "block"'
run_shown "cd app && test -f build.gradle.kts"; run_shown "cd app && test -s src.kt"
run_shown "cd app && grep -q ok src.kt"; eq "test green after the fix" "$RUN_RC" 0
out=$(stop_done g1); has "defaults green, own stale: held" "$out" '"decision": "block"'; has "names own" "$out" "$OWN"
(cd "$R" && python3 -I "$TV" run -- "$OWN" >/dev/null 2>&1) || fail "own command red"
eq "every default and the own command green: the report is taken" "$(stop_done g1)" ""
echo "stack-plan/session-start/verify-defaults/gate ok"
