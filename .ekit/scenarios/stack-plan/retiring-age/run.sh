#!/bin/bash
SPFX="$EKIT_PARENT_DIR/fixtures"; source "$SPFX/lib.sh"
# at <days ago> <msg>: commit everything with author and committer dates that many days back
at() { local d; d=$(python3 -c 'import sys,time; print("@%d +0000" % (time.time() - float(sys.argv[1]) * 86400))' "$1")
  GIT_AUTHOR_DATE="$d" GIT_COMMITTER_DATE="$d" commit "$2"; }
setstatus() { python3 -I -c 'import re,sys; p=sys.argv[1]; s=open(p).read()
s=re.sub(r"(name = \"old\"\nfolder = \"old\"\nadapter = \"ts\"\nstatus = )\"\w+\"", lambda m: m.group(1) + "\"" + sys.argv[2] + "\"", s)
open(p,"w").write(s)' "$R/.ekit/stack-plan.toml" "$1"; grep -q "status = \"$1\"" "$R/.ekit/stack-plan.toml" || fail "setstatus $1"; }
msg() { q '.checks.D.messages | join("\n")'; }

# a JS to TS style migration: `old` (ts) moves to `new` (python); the plan's history dates it
newrepo mig; put old/package.json '{}'; put new/pyproject.toml '[project]'
stack old old ts current; stack new new python current; at 90 "plan"

# retiring for 31 days: the reminder
setstatus retiring; at 31 "old retires"; R31=$C
drift "31 days" "$C" "$C" 0
has "31 days: retiring message" "$(msg)" "retiring stack \`old\`"
has "31 days: reminder" "$(msg)" "retiring for 31 days"
has "31 days: says finish or drop" "$(msg)" "finish the migration or drop it"
eq "31 days: never a fail" "$(q '.entries | length')" 0
# a later plan edit elsewhere does not reset the count
sed -i '1i ignore = ["samples"]' "$R/.ekit/stack-plan.toml"; at 5 "unrelated plan edit"
drift "unrelated edit" "$C" "$C" 0
has "unrelated edit: still 31 days" "$(msg)" "retiring for 31 days"
# a PR on top of it sees the same (the base's history)
branch pr "$C"; put new/y.txt; commit pr
drift "pr" "$R31" "$C" 0
has "pr: reminder" "$(msg)" "retiring for 31 days"

# retiring for 29 days: the message, no reminder
newrepo young; put old/package.json '{}'; put new/pyproject.toml '[project]'
stack old old ts current; stack new new python current; at 90 "plan"
setstatus retiring; at 29 "old retires"
drift "29 days" "$C" "$C" 0
has "29 days: retiring message" "$(msg)" "retiring stack \`old\`"
hasnt "29 days: no reminder" "$(msg)" "retiring for"

# retiring 60 days ago, current again 40, retiring again 10: counts from the last time it became retiring
newrepo again; put old/package.json '{}'; put new/pyproject.toml '[project]'
stack old old ts current; stack new new python current; at 90 "plan"
setstatus retiring; at 60 "retire"; setstatus current; at 40 "un-retire"; setstatus retiring; at 10 "retire again"
drift "re-retired" "$C" "$C" 0
has "re-retired: message" "$(msg)" "retiring stack \`old\`"
hasnt "re-retired: no reminder" "$(msg)" "retiring for"

# a side branch merged in does not reset the count: retired 45 days ago on main, a side branch's old commit merged
newrepo side; put old/package.json '{}'; put new/pyproject.toml '[project]'
stack old old ts current; stack new new python current; at 90 "plan"; P=$C
setstatus retiring; at 45 "retire"
branch side "$P"; put side.txt; setstatus retiring; at 3 "side retires too"
git -C "$R" checkout -q main; GIT_COMMITTER_DATE="@$(date +%s) +0000" git -C "$R" merge -q --no-edit -X theirs side 2>/dev/null || fail "merge"
C=$(git -C "$R" rev-parse HEAD)
drift "merged side" "$C" "$C" 0
has "merged side: 45 days" "$(msg)" "retiring for 45 days"
echo "stack-plan/retiring-age ok"
