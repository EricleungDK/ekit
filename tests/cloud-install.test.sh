source "$(dirname "$0")/lib.sh"
IN="$ROOT/cloud/install.sh"
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT  # physical path: macOS temp dirs sit behind a symlink
R="$T/repo"; mkdir -p "$R/.claude"; git -C "$R" init -q
echo '{"permissions":{"allow":["Bash(ls)"]},"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo mine"}]}]}}' > "$R/.claude/settings.json"
git -C "$R" add .; git -C "$R" -c user.email=t@t -c user.name=t commit -qm init

bash "$IN" "$R" >/dev/null
S="$R/.claude/settings.json"
for s in failure-triage finish orchestrate-agent taste-it; do
  [[ -f $R/.claude/skills/$s/SKILL.md ]] && ok "skill $s copied" || fail "skill $s copied"
done
[[ -f $R/.claude/skills/failure-triage/flaky.md ]] && ok "sibling files copied" || fail "sibling files copied"
eq "$(jq -r '.permissions.allow[0]' "$S")" "Bash(ls)" "existing settings kept"
has "$(jq -c '.hooks.Stop' "$S")" "echo mine" "existing hook kept"
has "$(jq -c '.hooks.Stop' "$S")" "$ROOT/scripts/finish-gate.py" "kit Stop hook added, absolute path"
has "$(jq -c '.hooks.SessionStart' "$S")" "session-start.py" "SessionStart added"
has "$(jq -c '.hooks.PostToolUseFailure' "$S")" "failure-match.py" "PostToolUseFailure added"
eq "$(jq -c '.hooks.SubagentStop' "$S")" "null" "no SubagentStop gate"
has "$(jq -c '.hooks.UserPromptSubmit' "$S")" "finish-gate.py\\\" --arm" "UserPromptSubmit arm added"
[[ -f $R/.claude/skills/taste-it/drivers.md ]] && ok "taste-it sibling copied" || fail "taste-it sibling copied"
lacks "$(cat "$S")" "CLAUDE_PLUGIN_ROOT" "no unresolved plugin var"

bash "$IN" "$R" >/dev/null
eq "$(jq '.hooks.Stop | length' "$S")" "2" "idempotent: no duplicate hooks"

eq "$(git -C "$R" status --porcelain)" "" "kit files hidden from git status"

# repo without .claude/
R2="$T/repo2"; mkdir -p "$R2"; git -C "$R2" init -q
bash "$IN" "$R2" >/dev/null
has "$(jq -c .hooks.Stop "$R2/.claude/settings.json")" "finish-gate.py" "creates settings when absent"
eq "$(git -C "$R2" status --porcelain)" "" "new settings hidden from git status"

# existing repo skill with same name is not overwritten
R3="$T/repo3"; mkdir -p "$R3/.claude/skills/finish"; echo mine > "$R3/.claude/skills/finish/SKILL.md"; git -C "$R3" init -q
bash "$IN" "$R3" >/dev/null
eq "$(cat "$R3/.claude/skills/finish/SKILL.md")" "mine" "repo's own skill wins"

# setup.sh: fetches the kit at EKIT_REF from EKIT_REPO_URL into ~/.ekit, installs it into the repos it finds
SRC="$T/kitsrc"; mkdir -p "$SRC"; cp -R "$ROOT/cloud" "$ROOT/skills" "$ROOT/hooks" "$ROOT/scripts" "$SRC/"
git -C "$SRC" init -q -b main; git -C "$SRC" add -A; git -C "$SRC" -c user.email=t@t -c user.name=t commit -qm one
git -C "$SRC" tag v0
echo "# later" >> "$SRC/cloud/setup.sh"; git -C "$SRC" -c user.email=t@t -c user.name=t commit -qam two
H="$T/cloudhome"; W="$H/work"; mkdir -p "$W"; git -C "$W" init -q
setup() { (cd "$W" && HOME="$H" EKIT_REPO_URL="file://$SRC" "$@" bash "$ROOT/cloud/setup.sh" 2>&1); }
out="$(setup env)"
has "$out" "ekit installed into $W" "setup: installs into the repo it runs in"
eq "$(git -C "$H/.ekit" rev-parse HEAD)" "$(git -C "$SRC" rev-parse main)" "setup: default ref is main"
has "$(jq -c .hooks.Stop "$W/.claude/settings.json")" "$H/.ekit/scripts/finish-gate.py" "setup: hooks point at the fetched kit"
out="$(setup env EKIT_REF=v0)"
eq "$(git -C "$H/.ekit" rev-parse HEAD)" "$(git -C "$SRC" rev-parse v0)" "setup: EKIT_REF pins a tag, also over an existing kit"
out="$(setup env EKIT_REF=no-such-ref)"; rc=$?
eq "$rc" "0" "setup: a ref that cannot be fetched does not fail the environment setup"
has "$out" "cannot fetch no-such-ref" "setup: says which ref could not be fetched"
eq "$(git -C "$H/.ekit" rev-parse HEAD)" "$(git -C "$SRC" rev-parse v0)" "setup: keeps the kit it had"

done_tests
