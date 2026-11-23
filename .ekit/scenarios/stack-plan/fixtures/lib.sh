# shared setup for the stack-plan scenarios (sourced; not a scenario). cwd = the scenario's temp dir;
# the caller sets SPFX to this fixtures dir (from EKIT_SCENARIO_DIR or EKIT_PARENT_DIR).
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
# the install: a clone of the kit, as a user (or the workflow's ekit checkout) gets it
KIT="$PWD/kit"
git -c advice.detachedHead=false clone -q "$EKIT_REPO" "$KIT" 2>/dev/null || fail "git clone of the kit failed"
MR="$KIT/scripts/mech-review.py"
# newrepo <dir>: an empty user repo in R
newrepo() { R="$PWD/$1"; rm -rf "$R"; mkdir -p "$R"; git -C "$R" init -q -b main; }
# put <path> [content]: write a file in R
put() { mkdir -p "$(dirname "$R/$1")"; printf '%s\n' "${2-}" > "$R/$1"; }
# stack <name> <folder> <adapter> <status> [extra line]: one [[stack]] table, appended to R's plan
stack() { mkdir -p "$R/.ekit"; printf '\n[[stack]]\nname = "%s"\nfolder = "%s"\nadapter = "%s"\nstatus = "%s"\n%s\n' \
  "$1" "$2" "$3" "$4" "${5-}" >> "$R/.ekit/stack-plan.toml"; }
# commit <msg>: commit everything (manifests under node_modules/build too), sha in C
commit() { git -C "$R" add -A -f; git -C "$R" commit -qm "$1" || fail "commit $1"; C=$(git -C "$R" rev-parse HEAD); }
# branch <name> <from>: a PR branch
branch() { git -C "$R" checkout -q -B "$1" "$2"; }
# drift <label> <base> <head> <want exit> [--format text]: as the guard job runs it; OUT, ERR
drift() { local l=$1 b=$2 h=$3 want=$4; shift 4
  OUT=$(python3 -I "$MR" drift --repo "$R" --base "$b" --head "$h" "$@" 2>"$PWD/drift.err"); local rc=$?
  ERR=$(cat "$PWD/drift.err"); hasnt "$l traceback" "$ERR" "Traceback"; eq "$l exit" "$rc" "$want"; }
# fields of OUT (JSON)
q() { jq -r "$1" <<<"$OUT"; }
