#!/bin/bash
SPFX="$EKIT_PARENT_DIR/fixtures"; source "$SPFX/lib.sh"
newrepo bad; put web/package.json '{}'; put api/pyproject.toml '[project]'; commit base; B0=$C
GOOD='[[stack]]
name = "web"
folder = "web"
adapter = "ts"
status = "current"'
# bad <label> <plan text> <stderr must contain>: the plan as a PR's own (plan-only) edit, and as a base plan
bad() { branch "$1" "$B0"; mkdir -p "$R/.ekit"; printf '%s\n' "$2" > "$R/.ekit/stack-plan.toml"; commit "$1"
  for refs in "$B0 $C" "$C $C"; do
    drift "$1 ($refs)" $refs 2
    has "$1: stderr names it" "$ERR" "$3"
    has "$1: stderr names the plan" "$ERR" ".ekit/stack-plan.toml at "
    eq "$1: D fails" "$(q .checks.D.status)" fail
    eq "$1: one CI entry" "$(q '[.entries[] | "\(.check) \(.class) \(.severity)"] | join("|")')" "CI adapter-fix fail"
    has "$1: the entry names it" "$(q '.entries[0].problem')" "$3"
    hasnt "$1: never pass" "$(q .summary)" "pass"
  done; }
bad status   "${GOOD/current/done}"                       'stack[0] `web`, field status: `done`: want planned, current or retiring'
bad nostatus "${GOOD/status = \"current\"/}"              'stack[0] `web`, field status: missing'
bad noname   "${GOOD/name = \"web\"/}"                    'field name: missing'
bad noadapter "${GOOD/adapter = \"ts\"/}"                 'stack[0] `web`, field adapter: missing'
bad nofolder "${GOOD/folder = \"web\"/}"                  'stack[0] `web`, field folder: missing'
bad tos      "$GOOD"$'\ntarget-os = "Linux"'              'stack[0] `web`, field target-os: `Linux`: want linux, macos or windows'
bad tosdarwin "$GOOD"$'\ntarget-os = "darwin"'            'field target-os: `darwin`'
bad unknown  "$GOOD"$'\ncolour = "red"'                   'stack[0] `web`, field colour: unknown key'
bad typo     "${GOOD/adapter = \"ts\"/adapter = \"typescript\"}" 'stack[0] `web`, field adapter: `typescript`'
bad outside  "${GOOD/folder = \"web\"/folder = \"../web\"}" 'stack[0] `web`, field folder: `../web`'
bad fixture  "${GOOD/folder = \"web\"/folder = \"tests/web\"}" 'stack[0] `web`, field folder: `tests/web`'
bad ignored  $'ignore = ["web"]\n'"$GOOD"                 'stack[0] `web`, field folder'
bad dot      $'ignore = ["."]\n'"$GOOD"                   'ignore[0]'
bad ignorestr $'ignore = "samples"\n'"$GOOD"              'ignore: want a list'
bad notoml   'this is [[[ not toml'                       'not valid TOML'
bad dupname  "$GOOD"$'\n\n'"${GOOD/folder = \"web\"/folder = \"api\"}" 'stack[1] `web`, field name'
bad dupstack "$GOOD"$'\n\n'"${GOOD/name = \"web\"/name = \"web2\"}" 'stack[1] `web2`, field folder'
bad second   "$GOOD"$'\n\n[[stack]]\nname = "api"\nfolder = "api"\nadapter = "python"\nstatus = "Current"' 'stack[1] `api`, field status: `Current`'
bad missingfile "${GOOD/adapter = \"ts\"/adapter = \".ekit/adapters/web.toml\"}" 'stack[0] `web`, field adapter'

# a bad base plan judges nothing: a PR that does not touch the plan still fails D (never clean)
branch base-bad "$B0"; mkdir -p "$R/.ekit"; printf '%s\n' "${GOOD/current/done}" > "$R/.ekit/stack-plan.toml"; commit base-bad; BB=$C
branch other "$BB"; put README.md 'hi'; commit other
drift "other PR on a bad base plan" "$BB" "$C" 2
eq "other PR: D fails" "$(q .checks.D.status)" fail
# the PR that fixes it edits only the plan: its own plan judges, and it passes
branch fixit "$BB"; printf '%s\n' "$GOOD" > "$R/.ekit/stack-plan.toml"; stack api api python current; commit fixit
drift "fix PR" "$BB" "$C" 0
eq "fix PR: D pass" "$(q .checks.D.status)" pass

# an odd but valid plan: CRLF line ends
branch crlf "$B0"; mkdir -p "$R/.ekit"; printf '%s\n\n[[stack]]\nname = "api"\nfolder = "api"\nadapter = "python"\nstatus = "current"\n' "$GOOD" | sed 's/$/\r/' > "$R/.ekit/stack-plan.toml"; commit crlf
drift crlf "$C" "$C" 0
eq "crlf: D pass" "$(q .checks.D.status)" pass
# misuse of the command itself: a ref that does not exist is a git error, nothing on stdout
drift "unknown ref" nosuchref "$C" 2
eq "unknown ref: stdout empty" "$OUT" ""
mkdir -p plain; drift "not a repo" HEAD HEAD 2 --repo "$PWD/plain"
eq "not a repo: stdout empty" "$OUT" ""
echo "stack-plan/malformed ok"
