source "$(dirname "$0")/lib.sh"
SS="$ROOT/scripts/session-start.py"; FG="$ROOT/scripts/finish-gate.py"
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT  # physical path: macOS temp dirs sit behind a symlink
export EKIT_STATE="$T/state"
# The verify commands have their own section at the end; until then a stand-in answers "all green".
printf 'raise SystemExit(0)\n' > "$T/greenverify"; export EKIT_TASK_VERIFY_PY="$T/greenverify"

R="$T/repo"; mkdir -p "$R"; git -C "$R" init -q; git -C "$R" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
start() { jq -nc --arg c "$1" --arg s "$2" '{hook_event_name:"SessionStart",session_id:$s,cwd:$c,source:"startup"}' | python3 -I "$SS"; }
arm()   { jq -nc --arg c "$1" --arg s "$2" --arg p "${3:-/ekit:orchestrate-agent do x}" '{hook_event_name:"UserPromptSubmit",session_id:$s,cwd:$c,prompt:$p}' | python3 -I "$FG" --arm; }
# stop <cwd> <session> [stop_hook_active] [event] [last assistant message]
stop()  { jq -nc --arg c "$1" --arg s "$2" --argjson a "${3:-false}" --arg e "${4:-Stop}" --arg m "${5:-}" '{hook_event_name:$e,session_id:$s,cwd:$c,stop_hook_active:$a} + (if $m == "" then {} else {last_assistant_message:$m} end)' | python3 -I "$FG"; }
REPORT=$'Work is in.\n\n## Finish: done\n| Criterion | Status | Evidence |'
BLOCKED=$'## Finish: blocked\nBlocker: no token'
commit() { git -C "$1" add -A; git -C "$1" -c user.email=t@t -c user.name=t commit -q -m "${2:-c}"; }

# session start: pointers + guardrails injected; finish/taste-it are orchestrate-only
out="$(start "$R" s1)"; arm "$R" s1 >/dev/null
c="$(jq -r .hookSpecificOutput.additionalContext <<<"$out")"
has "$c" "failure-triage" "start → triage pointer"
lacks "$c" "finish skill" "start → no always-on finish rule"
lacks "$c" "taste-it" "start → no always-on taste-it rule"
has "$c" "Same blocker 3×" "start → blocker guardrail"
has "$c" "exact command" "start → rephrase guardrail"

# not armed (no /ekit:orchestrate-agent) → gate silent even with changes
start "$R" n1 >/dev/null; echo n > "$R/n.txt"
eq "$(stop "$R" n1)" "" "unarmed + change → allow"
eq "$(stop "$R" n1 false SubagentStop)" "" "unarmed SubagentStop → allow"
arm "$R" n1 "why does /ekit:orchestrate-agent run?" >/dev/null
eq "$(stop "$R" n1)" "" "mention mid-prompt doesn't arm"
arm "$R" n1 "/ekit:taste-it" >/dev/null
eq "$(stop "$R" n1)" "" "other skill doesn't arm"
eq "$(arm "$R" n1 "/ekit:orchestrate-agent fix #3")" "" "arm prints nothing"
eq "$(jq -r .decision <<<"$(stop "$R" n1)")" "block" "armed (/ekit:orchestrate-agent) → block"
start "$R" n2 >/dev/null; arm "$R" n2 "  /orchestrate-agent x" >/dev/null; echo m >> "$R/n.txt"
eq "$(jq -r .decision <<<"$(stop "$R" n2)")" "block" "armed (cloud /orchestrate-agent) → block"
start "$R" n3 >/dev/null; arm "$R" n3 "<command-name>/ekit:orchestrate-agent</command-name>" >/dev/null; echo k >> "$R/n.txt"
eq "$(jq -r .decision <<<"$(stop "$R" n3)")" "block" "armed (command-name tag) → block"
rm -f "$R/n.txt"

# clean tree → allow stop
eq "$(stop "$R" s1)" "" "clean tree → allow"

# work without a finish report → block once per tree, then allow the same tree
echo x > "$R/a.txt"
out="$(stop "$R" s1)"
eq "$(jq -r .decision <<<"$out")" "block" "work, no report → block"
has "$(jq -r .reason <<<"$out")" "## Finish: done" "block reason names the report header"
lacks "$(jq -r .reason <<<"$out")" "Scenarios not green" "plain repo: no scenario reason"
eq "$(stop "$R" s1)" "" "same tree → allow (no loop)"
echo y >> "$R/a.txt"
eq "$(jq -r .decision <<<"$(stop "$R" s1)")" "block" "further change → block again"

# the finish report in the last message → allow, and the reported tree stays allowed
echo y2 >> "$R/a.txt"
eq "$(stop "$R" s1 false Stop "$REPORT")" "" "work + finish report → allow"
eq "$(stop "$R" s1 false Stop "just answering a question")" "" "reported tree, later turn → allow"
echo y3 >> "$R/a.txt"
eq "$(jq -r .decision <<<"$(stop "$R" s1 false Stop "no report here; Finish: done mid-sentence")")" "block" "header must open a line"
echo y4 >> "$R/a.txt"
eq "$(stop "$R" s1 false Stop "$BLOCKED")" "" "work + blocked report → allow"

# committed work counts: a commit with no report still blocks; the commit of a reported tree does not
start "$R" c1 >/dev/null; arm "$R" c1 >/dev/null
echo c > "$R/c.txt"; commit "$R"
eq "$(jq -r .decision <<<"$(stop "$R" c1)")" "block" "all work committed, no report → block"
echo d > "$R/d.txt"
eq "$(stop "$R" c1 false Stop "$REPORT")" "" "report on the dirty tree → allow"
commit "$R"
eq "$(stop "$R" c1)" "" "commit of the reported tree → still allowed"

# the report read from the transcript when the payload has no last_assistant_message
start "$R" t1 >/dev/null; arm "$R" t1 >/dev/null; echo t > "$R/t.txt"
TR="$T/transcript.jsonl"
jq -nc '{type:"user",message:{role:"user",content:"/ekit:orchestrate-agent do x"}}' > "$TR"
jq -nc '{type:"assistant",message:{role:"assistant",content:[{type:"text",text:"## Finish: done\nold report"}]}}' >> "$TR"
jq -nc '{type:"user",message:{role:"user",content:[{type:"tool_result",content:"ok"}]}}' >> "$TR"
jq -nc '{type:"assistant",message:{role:"assistant",content:[{type:"text",text:"still working"}]}}' >> "$TR"
tstop() { jq -nc --arg c "$R" --arg s "$1" --arg t "$TR" '{hook_event_name:"Stop",session_id:$s,cwd:$c,stop_hook_active:false,transcript_path:$t}' | python3 -I "$FG"; }
eq "$(jq -r .decision <<<"$(tstop t1)")" "block" "transcript: report before the last tool result does not count"
echo t2 >> "$R/t.txt"
jq -nc '{type:"assistant",message:{role:"assistant",content:[{type:"text",text:"Summary first."}]}}' >> "$TR"
jq -nc '{type:"assistant",message:{role:"assistant",content:[{type:"text",text:"## Finish: blocked\nBlocker: x"}]}}' >> "$TR"
eq "$(tstop t1)" "" "transcript: report in the final message → allow"

# stop_hook_active → always allow
echo z >> "$R/a.txt"
eq "$(stop "$R" s1 true)" "" "stop_hook_active → allow"

# pre-existing dirt at session start → not gated
start "$R" s2 >/dev/null; arm "$R" s2 >/dev/null
eq "$(stop "$R" s2)" "" "dirt present at session start → allow"

# a subagent's stop is never gated: the orchestrator owns the report (a stale install may still register the event)
echo w > "$R/b.txt"
eq "$(stop "$R" s2 false SubagentStop)" "" "SubagentStop → allow"
eq "$(jq -r '.hooks | has("SubagentStop")' "$ROOT/hooks/hooks.json")" "false" "hooks.json: no SubagentStop gate"

# non-git dir → allow
mkdir -p "$T/plain"; start "$T/plain" s3 >/dev/null
eq "$(stop "$T/plain" s3)" "" "non-git → allow"

# preflight warnings included, e.g. Cargo.toml without cargo (PATH stripped)
B="$T/bin"; fakebin "$B" python3 git jq; touch "$T/plain/Cargo.toml"
c="$(jq -nc --arg c "$T/plain" '{session_id:"s4",cwd:$c,source:"startup"}' | PATH="$B" python3 -I "$SS" | jq -r .hookSpecificOutput.additionalContext)"
has "$c" "cargo: missing" "start → preflight warnings"

# --- scenario repos: gate on fresh runner PASS ---
SC="$ROOT/scripts/scenarios.py"
mkrepo() { # mkrepo <dir> <run.sh exit code>
  mkdir -p "$1/.ekit/scenarios/x"; git -C "$1" init -q
  echo s > "$1/.ekit/scenarios/x/SCENARIO.md"; printf '#!/bin/bash\nexit %s\n' "$2" > "$1/.ekit/scenarios/x/run.sh"
  git -C "$1" add -A; git -C "$1" -c user.email=t@t -c user.name=t commit -q -m init
}
runsc() { python3 -I "$SC" --repo "$1" run >/dev/null; }
dec() { jq -r .decision <<<"$1"; }

P="$T/pass"; mkrepo "$P" 0
F="$T/fail"; mkrepo "$F" 1

# PASS current tree -> allow
start "$P" p1 >/dev/null; arm "$P" p1 >/dev/null; echo a > "$P/a.txt"; runsc "$P"
out="$(stop "$P" p1)"; eq "$(dec "$out")" "block" "scenarios PASS fresh, no report → block"
lacks "$(jq -r .reason <<<"$out")" "Scenarios not green" "green scenarios: the reason is the missing report"
echo a2 >> "$P/a.txt"; runsc "$P"
eq "$(stop "$P" p1 false Stop "$REPORT")" "" "scenarios PASS fresh + report → allow"
commit "$P"
eq "$(stop "$P" p1)" "" "commit after the PASS and report → still fresh, allow"
# PASS then edit -> stale block, keeps blocking
echo b >> "$P/a.txt"
out="$(stop "$P" p1)"; eq "$(dec "$out")" "block" "PASS then edit → block"
has "$(jq -r .reason <<<"$out")" "stale" "block reason has check reason"
has "$(jq -r .reason <<<"$out")" "scenarios.py" "block reason points to runner"
has "$(jq -r .reason <<<"$out")" "ekit:taste-it" "block reason points to taste-it"
has "$(jq -r .reason <<<"$out")" "finish" "block reason asks finish report"
eq "$(dec "$(stop "$P" p1)")" "block" "stale keeps blocking (no once-only)"
eq "$(dec "$(stop "$P" p1 false Stop "$REPORT")")" "block" "a done report does not excuse a stale PASS"
eq "$(stop "$P" p1 true)" "" "scenarios + stop_hook_active → allow"
eq "$(stop "$P" p1 false SubagentStop)" "" "scenarios SubagentStop → allow"
eq "$(stop "$P" p1 false Stop "$BLOCKED")" "" "a blocked report needs no PASS"

# no results -> block; failing results -> block
start "$F" f1 >/dev/null; arm "$F" f1 >/dev/null; echo a > "$F/a.txt"
out="$(stop "$F" f1)"; eq "$(dec "$out")" "block" "no results → block"
has "$(jq -r .reason <<<"$out")" "no results" "no-results reason"
runsc "$F"
out="$(stop "$F" f1)"; eq "$(dec "$out")" "block" "failing results → block"
has "$(jq -r .reason <<<"$out")" "FAIL" "fail reason"

# untouched since start -> allow (even with no results)
U="$T/untouched"; mkrepo "$U" 0
start "$U" u1 >/dev/null; arm "$U" u1 >/dev/null
eq "$(stop "$U" u1)" "" "scenario repo untouched → allow"

# commit after start without run -> block
echo c > "$U/c.txt"; git -C "$U" add -A; git -C "$U" -c user.email=t@t -c user.name=t commit -q -m c
eq "$(dec "$(stop "$U" u1)")" "block" "commit after start, no run → block"
runsc "$U"
eq "$(stop "$U" u1 false Stop "$REPORT")" "" "commit then run PASS + report → allow"

# runner broken -> fail closed (stop_hook_active still allows)
printf 'import sys\nsys.stderr.write("boom\\n")\nsys.exit(3)\n' > "$T/badrunner"
E="$T/err"; mkrepo "$E" 0
EKIT_SCENARIOS_PY="$T/badrunner" start "$E" e1 >/dev/null; arm "$E" e1 >/dev/null
out="$(EKIT_SCENARIOS_PY="$T/badrunner" stop "$E" e1)"
eq "$(dec "$out")" "block" "runner error → block"
has "$(jq -r .reason <<<"$out")" "scenario runner error" "runner error reason"
has "$(jq -r .reason <<<"$out")" "boom" "runner error shows output"
eq "$(EKIT_SCENARIOS_PY="$T/badrunner" stop "$E" e1 true)" "" "runner error + stop_hook_active → allow"

# baseline is per repo within one session
A2="$T/a2"; B2="$T/b2"; mkrepo "$A2" 0; mkrepo "$B2" 0; echo b > "$B2/b.txt"
start "$A2" m1 >/dev/null; arm "$A2" m1 >/dev/null; start "$B2" m1 >/dev/null; arm "$B2" m1 >/dev/null
eq "$(stop "$B2" m1)" "" "second repo own baseline → allow"
eq "$(stop "$A2" m1)" "" "first repo own baseline → allow"

# --- verify commands: a done report stands only when each of the session's commands passed on the current files ---
unset EKIT_TASK_VERIFY_PY; TV="$ROOT/scripts/task-verify.py"
V="$T/verify"; mkdir -p "$V"; git -C "$V" init -q; git -C "$V" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
mktask() { jq -nc --arg c "$V" --arg d "$1" --arg t "$2" '{hook_event_name:"TaskCreated",session_id:"v1",cwd:$c,task_id:$t,task_description:$d}' | python3 -I "$TV" --hook; }
start "$V" v1 >/dev/null; arm "$V" v1 >/dev/null; echo a > "$V/a.txt"
out="$(stop "$V" v1 false Stop "$REPORT")"; eq "$(dec "$out")" "block" "done, no verify command in the session → block"
has "$(jq -r .reason <<<"$out")" "no verify command was declared for this session" "reason: no command declared"
has "$(jq -r .reason <<<"$out")" "CLAUDE_CODE_SESSION_ID=v1 python3 $TV --repo $V declare -- <command>" "reason gives the declare command with the session id"
CLAUDE_CODE_SESSION_ID=v1 python3 -I "$TV" --repo "$V" declare -- 'test -f a.txt' 2>/dev/null
out="$(stop "$V" v1 false Stop "$REPORT")"; has "$(jq -r .reason <<<"$out")" '`test -f a.txt`: no run recorded' "a declared command is asked for"
mktask 'Verify: `test -f a.txt`' 1; mktask 'Whole job. Verify: nothing on this line
Verify: `test -f a.txt && test ! -f broken`' 2
out="$(stop "$V" v1 false Stop "$REPORT")"; eq "$(dec "$out")" "block" "done, commands never run → block"
has "$(jq -r .reason <<<"$out")" '`test -f a.txt`: no run recorded' "reason names the command and what is missing"
has "$(jq -r .reason <<<"$out")" 'run -- <command>' "reason gives the runner"
python3 -I "$TV" --repo "$V" run -- test -f a.txt 2>/dev/null
eq "$(dec "$(stop "$V" v1 false Stop "$REPORT")")" "block" "one command of two green → block"
python3 -I "$TV" --repo "$V" run -- 'test -f a.txt && test ! -f broken' 2>/dev/null
eq "$(stop "$V" v1 false Stop "$REPORT")" "" "every command green on these files → allow"
echo b >> "$V/a.txt"
out="$(stop "$V" v1 false Stop "$REPORT")"; eq "$(dec "$out")" "block" "edit after the passes → block"
has "$(jq -r .reason <<<"$out")" "the files changed since the passing run" "reason: stale pass"
eq "$(stop "$V" v1 false Stop "$BLOCKED")" "" "a blocked report needs no green command"

done_tests
