#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
mk_repo; install_kit; add_scn ok 0; commit_all s
hook SessionStart sess1 >/dev/null || fail "session start hook failed"
echo "u=1" >> "$SAMPLE/app.py"; eq "unarmed -> allow" "$(hook Stop sess1)" ""; git -C "$SAMPLE" checkout -q app.py
arm sess1 || fail "arm hook failed"
eq "no work -> allow" "$(hook Stop sess1)" ""
echo "x=1" >> "$SAMPLE/app.py"
out=$(hook Stop sess1)
has block "$out" '"decision": "block"'; has block "$out" "Scenarios not green"; has block "$out" "scenarios.py"
eq "subagent still running -> wait, allow" "$(hook Stop sess1 false "" "$RUNNING")" ""
has "subagent finished -> block again" "$(hook Stop sess1 false "" '{"background_tasks":[]}')" "Scenarios not green"
eq "loop guard" "$(hook Stop sess1 true)" ""
python3 "$RUNNER" --repo "$SAMPLE" run >/dev/null || fail "runner not green"
out=$(hook Stop sess1); has "green, no report" "$out" '"decision": "block"'; has "green, no report" "$out" "## Finish: done"
hasnt "green, no report" "$out" "Scenarios not green"
echo "y=2" >> "$SAMPLE/app.py"; python3 "$RUNNER" --repo "$SAMPLE" run >/dev/null || fail "runner not green"
eq "fresh PASS + report -> allow" "$(hook Stop sess1 false "$REPORT")" ""
commit_all work
eq "commit after PASS + report -> allow" "$(hook Stop sess1)" ""
[[ $(jq -r '.hooks | has("SubagentStop")' "$SAMPLE/.claude/settings.json") == false ]] || fail "SubagentStop gate installed"
echo "gate ok"
