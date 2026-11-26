#!/bin/bash
source "$EKIT_SCENARIO_DIR/fixtures/lib.sh"
# vd_count <label> <want>: how many [ekit] Verify defaults lines the context has
vd_count() { eq "$1: Verify defaults lines" "$(grep -c '^\[ekit\] Verify defaults' <<<"$CTX")" "$2"; }

# 61.1: a plan of two current stacks (an adapter file with build and lint, a built-in) and a planned one with no manifest
newrepo two
web_adapter .ekit/adapters/web.toml
put web/package.json '{"devDependencies": {"jest": "29"}}'; put api/pyproject.toml '[project]'
stack web web .ekit/adapters/web.toml current; stack api api python current; stack mob mob rust planned
commit base
start "$R" s-two
WANT=$'cd api && python3 -m pytest\ncd web && node_modules/.bin/jest\ncd web && npm run build\ncd web && npx eslint .'
eq "two stacks: each one's build, lint and test, in its folder" "$(declared s-two)" "$WANT"
while IFS= read -r c; do
  eq "two stacks: one context line for \`$c\`" "$(grep -cF "[ekit] Verify defaults: \`$c\` (" <<<"$VD")" 1
  eq "two stacks: the run line for \`$c\`" "$(shown "$c")" "python3 $TV --repo $R run -- '$c'"
done <<<"$WANT"
has "two stacks: names step and stack" "$VD" "(build of stack \`web\`"
has "two stacks: names step and stack" "$VD" "(lint of stack \`web\`"
has "two stacks: names step and stack" "$VD" "(test of stack \`api\`"
hasnt "install is never declared" "$CTX" "npm ci"; hasnt "planned, no manifest: nothing" "$VD" "mob"
hasnt "planned, no manifest: no cargo" "$VD" "cargo"
# 61.4: a step the adapter names no command for is named once, per stack
eq "61.4: api's build and lint named once" "$(grep -c 'stack `api`.* names no build or lint command' <<<"$VD")" 1
hasnt "61.4: web names every step" "$VD" "stack \`web\` (in web) names no"
# the same from a subfolder of the repo (a new session)
start "$R/web" s-two-sub; eq "from web/: the same commands" "$(declared s-two-sub)" "$WANT"
# the drift check still runs beside it: an unplanned manifest is still named
put cli/Cargo.toml '[package]'; commit cli; start "$R" s-two-cli
has "drift beside defaults" "$CTX" "unchecked manifest cli/Cargo.toml"
eq "drift beside defaults: the same commands" "$(declared s-two-cli)" "$WANT"

# 61.3: the commands CI runs for each stack: a retiring stack and a planned one whose manifest is there run in CI,
# a built-in's test is the one R1/R4 run (jest when the project lists only jest, vitest when it lists vitest)
newrepo mixed
put old/package.json '{"devDependencies": {"jest": "29"}}'; put new/package.json '{"devDependencies": {"jest": "29", "vitest": "2"}}'
put svc/pyproject.toml '[project]'; put core/Cargo.toml '[package]'
stack old old ts retiring; stack new new ts current; stack svc svc python planned; stack core core rust current
commit base; start "$R" s-mixed
eq "61.3: CI's test commands" "$(declared s-mixed)" "$(printf '%s\n' 'cd core && cargo test' 'cd new && node_modules/.bin/vitest run' \
  'cd old && node_modules/.bin/jest' 'cd svc && python3 -m pytest')"
for s in old new svc core; do
  eq "61.4: \`$s\` names no build or lint, once" "$(grep -c "stack \`$s\`.* names no build or lint command" <<<"$VD")" 1; done

# 61.2: no plan, one project: the stack auto finds, at the root a plain command
newrepo solo; put package.json '{"devDependencies": {"jest": "29"}}'; commit base; start "$R" s-solo
eq "no plan, one ts project" "$(declared s-solo)" "node_modules/.bin/jest"
eq "no plan: run line" "$(shown node_modules/.bin/jest)" "python3 $TV --repo $R run -- node_modules/.bin/jest"
eq "no plan: build and lint named once" "$(grep -c 'names no build or lint command' <<<"$VD")" 1
# no plan, the repo's own adapter file found by auto: its build and test, its empty lint named; install never
newrepo own; put build.gradle.kts 'x'
tool_adapter tool $'[commands]\ninstall = "touch INSTALLED"\nbuild = "test -f build.gradle.kts"\nlint = ""\ntest = "grep -q ok src.kt"'
commit base; start "$R" s-own
eq "no plan, adapter file" "$(declared s-own)" $'grep -q ok src.kt\ntest -f build.gradle.kts'
eq "adapter file: lint named once" "$(grep -c 'stack `tool`.* names no lint command' <<<"$VD")" 1
hasnt "adapter file: install never" "$CTX" "INSTALLED"
# an adapter file with no [commands] table: every step named, nothing declared
newrepo bare; put build.gradle.kts 'x'; tool_adapter tool; commit base; start "$R" s-bare
none_declared "no [commands]" s-bare
eq "no [commands]: one line naming the three steps" "$(grep -c 'stack `tool`.* names no build, lint or test command' <<<"$VD")" 1
vd_count "no [commands]" 1
# several projects, or none: nothing declared, one line saying why
newrepo several; put web/package.json '{}'; put api/pyproject.toml '[project]'; commit base; start "$R" s-several
none_declared "several projects" s-several; vd_count "several projects" 1
has "several projects: why" "$VD" "none declared: several projects"
has "several: names them" "$VD" "web"; has "several: names them" "$VD" "api"
newrepo nothing; put README.md 'hi'; commit base; start "$R" s-nothing
none_declared "no project" s-nothing; vd_count "no project" 1; has "no project: why" "$VD" "none declared: no project"

# misuse: a plan that does not read, an adapter file that is not TOML, a command holding a run of spaces,
# no commit yet, outside git, no session_id: never a guess, never a failed hook, one line each
newrepo badplan; put web/package.json '{}'; stack web web ts done; commit base; start "$R" s-badplan
none_declared "bad plan" s-badplan; vd_count "bad plan" 1; has "bad plan: names the field" "$VD" 'stack[0] `web`, field status'
newrepo badadapter; put build.gradle.kts 'x'; mkdir -p "$R/.ekit/adapters"; printf 'not = [toml\n' > "$R/.ekit/adapters/tool.toml"
commit base; start "$R" s-badadapter
none_declared "bad adapter" s-badadapter; vd_count "bad adapter" 1; has "bad adapter: names it" "$VD" ".ekit/adapters/tool.toml"
newrepo spaces; put build.gradle.kts 'x'
tool_adapter tool $'[commands]\ninstall = ""\nbuild = "test -f build.gradle.kts"\nlint = ""\ntest = "grep  -q ok src.kt"'
commit base; start "$R" s-spaces
eq "spaces: only the clean step declared" "$(declared s-spaces)" "test -f build.gradle.kts"
eq "spaces: one line naming the test step" "$(grep -c 'stack `tool`.*test not declared.*whitespace' <<<"$VD")" 1
newrepo nocommit; put package.json '{}'; start "$R" s-nocommit
none_declared "no commit" s-nocommit; vd_count "no commit" 1; has "no commit: why" "$VD" "none declared"
mkdir -p "$PWD/plain"; start "$PWD/plain" s-plain; vd_count "outside git" 1; has "outside git: why" "$VD" "none declared"
newrepo nosession; put package.json '{}'; commit base; start "$R" -
vd_count "no session_id" 1; has "no session_id: why" "$VD" "none declared"
echo "stack-plan/session-start/verify-defaults ok"
