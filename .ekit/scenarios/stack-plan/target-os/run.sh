#!/bin/bash
SPFX="$EKIT_PARENT_DIR/fixtures"; source "$SPFX/lib.sh"
# resolve <label> <base> <head> <want exit> [args...]: the workflow's stack job; OUT, ERR
resolve() { local l=$1 b=$2 h=$3 want=$4; shift 4
  OUT=$(python3 -I "$MR" resolve --repo "$R" --base "$b" --head "$h" "$@" 2>err); local rc=$?; ERR=$(cat err)
  hasnt "$l traceback" "$ERR" "Traceback"; eq "$l exit" "$rc" "$want"; }
row() { jq -c '[.stack, .project_dir, .target_os]' <<<"$OUT"; }
# kt.toml with a target-os line: adapter_os <os> <dest>
adapter_os() { mkdir -p "$(dirname "$2")"; sed "s/^manifests = .*/&\ntarget-os = \"$1\"/" "$SPFX/kt.toml" > "$2"; }

# a plan entry's own target-os for a built-in stack
newrepo builtin; put web/package.json '{}'; stack web web ts current 'target-os = "windows"'; commit base; B=$C
resolve "built-in + entry windows" "$B" "$B" 0; eq "auto: entry's windows" "$(row)" '["ts","web","windows"]'
resolve "explicit stack" "$B" "$B" 0 --stack ts --project-dir web; eq "explicit: entry's windows" "$(row)" '["ts","web","windows"]'
resolve "no entry for the dir" "$B" "$B" 0 --stack ts; eq "project dir . has no entry: linux" "$(row)" '["ts",".","linux"]'

# an adapter file with macos: the entry with no target-os takes the adapter's; one with its own wins
newrepo file; put mob/build.gradle.kts ''; adapter_os macos "$R/.ekit/adapters/kt.toml"
stack mob mob .ekit/adapters/kt.toml current; commit base; B=$C
resolve "adapter macos" "$B" "$B" 0 --stack kt --project-dir mob --adapter "$R/.ekit/adapters/kt.toml"
eq "entry without target-os: the adapter's macos" "$(row)" '["kt","mob","macos"]'
sed -i 's/^status = "current"/&\ntarget-os = "windows"/' "$R/.ekit/stack-plan.toml"; commit entry-os; B2=$C
resolve "entry windows over adapter macos" "$B2" "$B2" 0 --stack kt --project-dir mob --adapter "$R/.ekit/adapters/kt.toml"
eq "the entry's target OS wins" "$(row)" '["kt","mob","windows"]'
sed -i 's/target-os = "windows"/target-os = "linux"/' "$R/.ekit/stack-plan.toml"; commit entry-linux; B3=$C
resolve "entry linux over adapter macos" "$B3" "$B3" 0 --stack kt --project-dir mob --adapter "$R/.ekit/adapters/kt.toml"
eq "an entry's linux wins too" "$(row)" '["kt","mob","linux"]'

# the base branch's plan decides: a PR that changes the target OS does not pick its own runner
branch pr "$B2"; sed -i 's/target-os = "windows"/target-os = "linux"/' "$R/.ekit/stack-plan.toml"; commit pr
resolve "PR flips the OS" "$B2" "$C" 0 --stack kt --project-dir mob --adapter "$R/.ekit/adapters/kt.toml"
eq "base plan's windows" "$(row)" '["kt","mob","windows"]'

# a migration: a retiring and a current entry in one folder; current's target OS applies
newrepo mig; put app/package.json '{}'; stack old app ts retiring 'target-os = "macos"'; stack new app ts current 'target-os = "windows"'; commit base; B=$C
resolve "current before retiring" "$B" "$B" 0; eq "current's windows" "$(row)" '["ts","app","windows"]'

# misuse: a base plan with a bad target-os never stops resolve, and stderr says what applied
newrepo badbase; put web/package.json '{}'; stack web web ts current 'target-os = "Windows"'; commit base; B=$C
resolve "bad base plan" "$B" "$B" 0; eq "bad plan: no entry, linux" "$(row)" '["ts","web","linux"]'
has "bad plan: stderr names the field" "$ERR" "target-os"
has "bad plan: stderr says what applied" "$ERR" "linux"
# its drift check fails D (the entry and the field named)
drift "bad base plan drift" "$B" "$B" 2; has "drift names target-os" "$ERR" 'stack[0] `web`, field target-os: `Windows`'
# the PR that fixes it (plan-only) gets its own plan's target OS
branch fix "$B"; sed -i 's/"Windows"/"windows"/' "$R/.ekit/stack-plan.toml"; commit fix
resolve "fix PR" "$B" "$C" 0; eq "fix PR: its own windows" "$(row)" '["ts","web","windows"]'
echo "stack-plan/target-os ok"
