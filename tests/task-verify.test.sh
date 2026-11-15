source "$(dirname "$0")/lib.sh"
# The task hook as Claude Code runs it: a real process, the payload on stdin, the answer in the exit code and stderr.
TV="$ROOT/scripts/task-verify.py"
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT  # physical path: macOS temp dirs sit behind a symlink
export EKIT_STATE="$T/state"

R="$T/repo"; mkdir -p "$R/sub"; git -C "$R" init -q; echo a > "$R/a.txt"; git -C "$R" add -A; git -C "$R" commit -q -m init
# task <event> <description> [task id]: prints stderr, returns the hook's exit code
task() { jq -nc --arg e "$1" --arg d "$2" --arg t "${3:-t1}" --arg c "$R" '{hook_event_name:$e,session_id:"s1",cwd:$c,task_id:$t,task_subject:"Unit auth",task_description:$d}' | python3 -I "$TV" --hook 2>&1 >/dev/null; }
DESC=$'Build the login check.\nVerify: `test -f a.txt`'

for e in TaskCreated TaskCompleted; do
  has "$(jq -c ".hooks.$e" "$ROOT/hooks/hooks.json")" 'task-verify.py\" --hook' "hooks.json: $e runs the task hook"
done

out="$(task TaskCompleted "no line here")"; eq "$?" "0" "no Verify line → completes"; eq "$out" "" "no Verify line → silent"

out="$(task TaskCreated "$DESC")"; eq "$?" "0" "created → never blocked"
out="$(task TaskCompleted "$DESC")"; eq "$?" "2" "no run → exit 2 (the code that keeps the task open)"
has "$out" "no run recorded" "block says what is missing"
has "$out" "$TV run -- test -f a.txt" "block gives the command to run"

(cd "$R/sub" && python3 -I "$TV" run -- test -f a.txt 2>/dev/null); eq "$?" "0" "run from a subdir: repo root is the cwd"
out="$(task TaskCompleted "$DESC")"; eq "$?" "0" "passing run → completes"
ls "$EKIT_STATE"/verify/*/verify.json >/dev/null 2>&1 && ok "record under EKIT_STATE" || fail "record under EKIT_STATE"
eq "$(git -C "$R" status --porcelain)" "" "run leaves the worktree clean"

echo b >> "$R/a.txt"
out="$(task TaskCompleted "$DESC")"; eq "$?" "2" "edit after the pass → blocked"
has "$out" "changed since" "block names the stale pass"

python3 -I "$TV" --repo "$R" run -- 'echo out; exit 4' >"$T/o" 2>"$T/e"; eq "$?" "4" "run exits with the command's code"
has "$(cat "$T/o")" "out" "run passes the command's output through"
out="$(task TaskCompleted $'Verify: `echo out; exit 4`' t2)"; eq "$?" "2" "failing run → blocked"
has "$out" "exited 4" "block names the exit code"

python3 -I "$TV" run 2>/dev/null; eq "$?" "2" "run without a command → usage error"
done_tests
