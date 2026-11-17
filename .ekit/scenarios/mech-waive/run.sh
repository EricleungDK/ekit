#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
MR="$EKIT_REPO/scripts/mech-review.py"
MC="$EKIT_REPO/scripts/mech-comment.py"
RR="$EKIT_REPO/scripts/mech-rerun.py"
FAKE="$EKIT_REPO/.ekit/scenarios/mech-waive/fixtures/fake_github.py"

# a PR that deletes a test: one R2 fail entry
R="$PWD/repo"; mkdir -p "$R/tests"; git -C "$R" init -q -b main
printf 'def test_adds():\n    assert 1 + 1 == 2\n\n\ndef test_keeps():\n    assert 2 + 2 == 4\n' > "$R/tests/test_math.py"
git -C "$R" add -A; git -C "$R" commit -qm base; BASE=$(git -C "$R" rev-parse HEAD)
printf 'def test_adds():\n    assert 1 + 1 == 2\n' > "$R/tests/test_math.py"
git -C "$R" commit -qam cheat; HEAD_SHA=$(git -C "$R" rev-parse HEAD)
python3 "$MR" r2 --repo "$R" --base "$BASE" --head "$HEAD_SHA" --stack python --test-paths 'tests/**' > r2.json
ID=$(jq -r '.entries[0].id' r2.json)
has "the entry" "$ID" "R2-"

# a fake GitHub: the PR's head, its comments, one finished mech-review run
STATE="$PWD/state.json"; LOG="$PWD/writes.log"; : > "$LOG"
jq -n --arg h "$HEAD_SHA" '{head: $h, comments: [],
  runs: [{id: 77, head_sha: $h, event: "pull_request", status: "completed", created_at: "2026-01-01T00:00:00Z"}],
  jobs: {"77": [{id: 501, name: "mech-review / mech-review guard (R2)"}, {id: 502, name: "mech-review / mech-review report"}]}}' > "$STATE"
python3 "$FAKE" "$STATE" "$LOG" "$PWD/port" & SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
for _ in $(seq 50); do [[ -s $PWD/port ]] && break; sleep 0.1; done
export GITHUB_API_URL="http://127.0.0.1:$(cat "$PWD/port")" GITHUB_REPOSITORY=o/r GITHUB_TOKEN=t
report() { python3 "$MC" --pr 1 --head "$HEAD_SHA" --envelope r2="$PWD/r2.json" 2>/dev/null; }
sticky() { jq -r '.comments[] | select(.user.type == "Bot") | .body' "$STATE"; }
# a person comments: say <login> <association> <body> [edited]
say() { local up="2026-01-02T00:00:00Z"; [[ ${4:-} == edited ]] && up="2026-01-02T00:05:00Z"
  jq --arg l "$1" --arg a "$2" --arg b "$3" --arg u "$up" \
    '.comments += [{id: (100 + (.comments | length)), user: {login: $l, type: "User"}, author_association: $a, body: $b,
       created_at: "2026-01-02T00:00:00Z", updated_at: $u, html_url: "https://github.test/c/x"}]' "$STATE" > s.tmp && mv s.tmp "$STATE"; }
unsay() { jq '.comments |= map(select(.user.type == "Bot"))' "$STATE" > s.tmp && mv s.tmp "$STATE"; }

# 1. the failing comment offers the line to post
report; eq "fail exit" "$?" 1
LINE=$(sticky | grep -m1 '^/mech-waive ')
eq "ready-made line" "$LINE" "/mech-waive $ID <why this is OK>"

# 2. posted as is: the placeholder is no reason
say owner OWNER "$LINE"
report; eq "placeholder exit" "$?" 1
has "placeholder named" "$(sticky)" "Waiver ignored: $ID by \`owner\`"

# 3. a real reason, in a comment edited after posting: not a waiver
unsay; say owner OWNER "/mech-waive $ID test moved to the e2e suite" edited
report; eq "edited exit" "$?" 1
has "edited named" "$(sticky)" "edited after posting"

# 4. an outsider's waiver: nothing
unsay; say rando NONE "/mech-waive $ID trust me"
report; eq "outsider exit" "$?" 1
hasnt "outsider not shown as waived" "$(sticky)" "Waived:"

# 5. the copied line with a reason, unedited: waived, the check passes
unsay; say owner OWNER "${LINE/<why this is OK>/test moved to the e2e suite}"
report; eq "waived exit" "$?" 0
has "waiver shown" "$(sticky)" "Waived: $ID by \`owner\`: test moved to the e2e suite"
hasnt "no lines once waived" "$(sticky)" "<why this is OK>"
eq "one sticky comment" "$(jq '[.comments[] | select(.user.type == "Bot")] | length' "$STATE")" 1

# 6. the comment re-runs the finished report job, not the guard
: > "$LOG"
python3 "$RR" --pr 1 2>rerun.err; eq "rerun exit" "$?" 0
eq "rerun call" "$(jq -r '"\(.method) \(.path)"' "$LOG")" "POST /repos/o/r/actions/jobs/502/rerun"

# 7. a run still going: nothing re-run, its report reads the comment
jq '.runs[0].status = "in_progress"' "$STATE" > s.tmp && mv s.tmp "$STATE"; : > "$LOG"
python3 "$RR" --pr 1 2>rerun.err; eq "running exit" "$?" 0
eq "nothing re-run" "$(cat "$LOG")" ""
has "running said" "$(cat rerun.err)" "in_progress"
echo "mech-waive ok"
