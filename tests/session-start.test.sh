source "$(dirname "$0")/lib.sh"
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT  # physical path: macOS temp dirs sit behind a symlink
export EKIT_STATE_DIR="$T/state" XDG_STATE_HOME="$T/state" HOME="$T/home"; mkdir -p "$HOME"
R="$T/repo"; mkdir -p "$R"; git -C "$R" init -q

out="$(echo "{\"cwd\":\"$R\"}" | python3 -I "$ROOT/scripts/session-start.py")"
ctx="$(jq -r .hookSpecificOutput.additionalContext <<<"$out")"
has "$ctx" "[ekit] Scenario runner: python3 $ROOT/scripts/scenarios.py" "runner line, absolute path"
lacks "$ctx" "taste-it" "no always-on taste-it rule (orchestrate-only)"
has "$ctx" "failure-triage" "triage rule stays always-on"
lacks "$ctx" "Stack plan" "no commit, no plan: no stack plan line"

# stack plan (#57): the committed tree's drift against its plan, named in the context; a clean plan adds nothing
P="$T/planned"; mkdir -p "$P/web" "$P/api" "$P/.ekit"; git -C "$P" init -q
echo '{}' > "$P/web/package.json"; echo '[project]' > "$P/api/pyproject.toml"
printf '[[stack]]\nname = "web"\nfolder = "web"\nadapter = "ts"\nstatus = "retiring"\n' > "$P/.ekit/stack-plan.toml"
git -C "$P" add -A; git -C "$P" -c user.email=t@t -c user.name=t -c commit.gpgsign=false commit -qm plan
pctx="$(echo "{\"cwd\":\"$P\"}" | python3 -I "$ROOT/scripts/session-start.py" | jq -r .hookSpecificOutput.additionalContext)"
has "$pctx" "unchecked manifest api/pyproject.toml" "uncovered manifest named"
has "$pctx" "retiring stack \`web\` (web)" "retiring stack message"
printf '\n[[stack]]\nname = "api"\nfolder = "api"\nadapter = "python"\nstatus = "current"\n' >> "$P/.ekit/stack-plan.toml"
sed -i.bak 's/retiring/current/' "$P/.ekit/stack-plan.toml"; rm -f "$P/.ekit/stack-plan.toml.bak"
git -C "$P" -c user.email=t@t -c user.name=t -c commit.gpgsign=false commit -qam clean
cctx="$(echo "{\"cwd\":\"$P\"}" | python3 -I "$ROOT/scripts/session-start.py" | jq -r .hookSpecificOutput.additionalContext)"
lacks "$cctx" "Stack plan" "clean plan: no stack plan line"

# default verify commands (#61): the plan's stacks at HEAD, declared for the hook's session, as the Stop gate reads them
vctx="$(echo "{\"cwd\":\"$P\",\"session_id\":\"s61\"}" | python3 -I "$ROOT/scripts/session-start.py" | jq -r .hookSpecificOutput.additionalContext)"
has "$vctx" "\`cd api && python3 -m pytest\`" "python stack's test command named, in its folder"
has "$vctx" "\`cd web && node_modules/.bin/vitest run\`" "ts stack's test command named, in its folder"
has "$vctx" "stack \`api\` (python, in api) names no build or lint command" "missing steps named"
vcheck="$(python3 -I "$ROOT/scripts/task-verify.py" --repo "$P" check s61)"
has "$vcheck" "\`cd api && python3 -m pytest\`: no run recorded" "declared for the session: the Stop gate asks for its run"
has "$vcheck" "\`cd web && node_modules/.bin/vitest run\`: no run recorded" "both stacks declared"

# cloud install: hook command from settings.json yields the kit's absolute runner path
bash "$ROOT/cloud/install.sh" "$R" >/dev/null
cmd="$(jq -r '.hooks.SessionStart[0].hooks[0].command' "$R/.claude/settings.json")"
ctx2="$(echo "{\"cwd\":\"$R\"}" | bash -c "$cmd" | jq -r .hookSpecificOutput.additionalContext)"
has "$ctx2" "python3 $ROOT/scripts/scenarios.py" "cloud install: runner path resolves to kit"

# runner line is executable from the cloud install, against the repo
runner="$(grep -o 'python3 [^ ]*scenarios.py' <<<"$ctx2")"
export EKIT_STATE="$T/ekstate"
mkdir -p "$R/.ekit/scenarios/hello"; echo '# s' > "$R/.ekit/scenarios/hello/SCENARIO.md"; printf '#!/bin/bash\nexit 0\n' > "$R/.ekit/scenarios/hello/run.sh"
rout="$(cd "$R" && $runner run 2>&1)"; has "$rout" "PASS hello" "runner line runs scenarios"
(cd "$R" && $runner check >/dev/null 2>&1) && ok "runner check passes" || fail "runner check passes"

done_tests
