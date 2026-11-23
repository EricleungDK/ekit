#!/bin/bash
SPFX="$EKIT_PARENT_DIR/fixtures"; source "$SPFX/lib.sh"
MC="$KIT/scripts/mech-comment.py"; FAKE="$KIT/tests/fixtures/mech-waive/fake_github.py"
[[ -f $FAKE ]] || fail "the kit clone has no fake GitHub at tests/fixtures/mech-waive/fake_github.py"

# a PR adding two manifests the base plan does not cover, while a retiring stack is still there
newrepo repo; put web/package.json '{}'; put old/package.json '{}'
stack web web ts current; stack old old ts retiring; commit base; B=$C
branch pr "$B"; put api/pyproject.toml '[project]'; put cli/Cargo.toml '[package]'; commit pr; H=$C
drift pr "$B" "$H" 1; cp /dev/stdin drift.json <<<"$OUT"
ID=$(q '.entries[0].id'); has "drift id" "$ID" "D-"
python3 -I "$MR" r2 --repo "$R" --base "$B" --head "$H" --stack python --test-paths 'tests/**' > r2.json 2>/dev/null

# the fake GitHub the comment tool talks to (as in the mech-waive scenario)
STATE="$PWD/state.json"; LOG="$PWD/writes.log"; : > "$LOG"
jq -n --arg h "$H" '{head: $h, comments: [], runs: [], jobs: {}}' > "$STATE"
python3 "$FAKE" "$STATE" "$LOG" "$PWD/port" & SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
for _ in $(seq 50); do [[ -s $PWD/port ]] && break; sleep 0.1; done
export GITHUB_API_URL="http://127.0.0.1:$(cat "$PWD/port")" GITHUB_REPOSITORY=o/r GITHUB_TOKEN=t
# report <drift file>: the report job's comment step, with the drift result
report() { python3 "$MC" --pr 1 --head "$H" --envelope r2="$PWD/r2.json" --envelope drift="$1" 2>/dev/null; }
sticky() { jq -r '.comments[] | select(.user.type == "Bot") | .body' "$STATE"; }
say() { jq --arg l "$1" --arg a "$2" --arg b "$3" \
    '.comments += [{id: (100 + (.comments | length)), user: {login: $l, type: "User"}, author_association: $a, body: $b,
       created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", html_url: "https://github.test/c/x"}]' "$STATE" > s.tmp && mv s.tmp "$STATE"; }
unsay() { jq '.comments |= map(select(.user.type == "Bot"))' "$STATE" > s.tmp && mv s.tmp "$STATE"; }

# 1. the drift entry fails the check and the comment offers its waiver line
report "$PWD/drift.json"; eq "drift fails the check" "$?" 1
has "headline names D" "$(sticky)" "ran: R2 D"
has "entry in the table" "$(sticky)" "| $ID | fail |"
has "the table names both manifests" "$(sticky)" "api/pyproject.toml, cli/Cargo.toml"
LINE=$(sticky | grep -m1 "^/mech-waive $ID ")
eq "ready-made line" "$LINE" "/mech-waive $ID <why this is OK>"
has "Stack plan line for the message" "$(sticky)" "Stack plan:"
has "Stack plan line text" "$(sticky)" "retiring stack \`old\`"

# 2. an owner posts the line with a reason: waived, the check passes
say owner OWNER "${LINE/<why this is OK>/the plan entries land in the next PR}"
report "$PWD/drift.json"; eq "waived exit" "$?" 0
has "waiver shown" "$(sticky)" "Waived: $ID by \`owner\`: the plan entries land in the next PR"
has "summary counts it" "$(sticky)" "1 waived"
hasnt "never all pass over a waiver" "$(sticky)" "all pass"

# 3. a third uncovered manifest: a new id, the old waiver no longer holds
branch pr2 "$H"; put tool/package.json '{}'; commit pr2; H=$C
drift pr2 "$B" "$H" 1; cp /dev/stdin drift2.json <<<"$OUT"
ID2=$(q '.entries[0].id'); [[ $ID2 != "$ID" ]] || fail "the id did not change with the set of manifests: $ID2"
jq --arg h "$H" '.head = $h' "$STATE" > s.tmp && mv s.tmp "$STATE"
python3 -I "$MR" r2 --repo "$R" --base "$B" --head "$H" --stack python --test-paths 'tests/**' > r2.json 2>/dev/null
report "$PWD/drift2.json"; eq "old waiver lapses" "$?" 1
has "new id offered" "$(sticky)" "/mech-waive $ID2 <why this is OK>"

# 4. a bad plan's CI entry cannot be waived
unsay; branch bad "$B"; sed -i 's/status = "current"/status = "done"/' "$R/.ekit/stack-plan.toml"; commit bad; H=$C
drift bad "$H" "$H" 2; cp /dev/stdin drift3.json <<<"$OUT"
CID=$(q '.entries[0].id'); has "bad plan id" "$CID" "CI-"
jq --arg h "$H" '.head = $h' "$STATE" > s.tmp && mv s.tmp "$STATE"
python3 -I "$MR" r2 --repo "$R" --base "$H" --head "$H" --stack python --test-paths 'tests/**' > r2.json 2>/dev/null
say owner OWNER "/mech-waive $CID the plan is fine"
report "$PWD/drift3.json"; eq "CI entry not waivable" "$?" 1
hasnt "CI entry not shown waived" "$(sticky)" "Waived: $CID"
echo "stack-plan/waive ok"
