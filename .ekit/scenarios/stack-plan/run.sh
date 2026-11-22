#!/bin/bash
SPFX="$EKIT_SCENARIO_DIR/fixtures"; source "$SPFX/lib.sh"
PY='[project]
name = "x"'

# --- 56.5: no plan anywhere: no D, resolve as before ---
newrepo noplan; put web/package.json '{}'; commit base; B=$C
branch pr "$B"; put api/pyproject.toml "$PY"; commit pr
drift noplan "$B" "$C" 0
eq "no plan: checks" "$(q '.checks | keys | join(" ")')" "R1 R2 R3 R4"
eq "no plan: entries" "$(q '.entries | length')" 0
hasnt "no plan: summary" "$(q .summary)" "D"
RES=$(python3 -I "$MR" resolve --repo "$R" --base "$B" --head "$B" 2>/dev/null)
eq "no plan: resolve" "$(jq -c '[.stack, .project_dir, .error, .target_os]' <<<"$RES")" '["ts","web",null,"linux"]'

# --- 56.2: a base plan with a current, a retiring and a planned stack, and an ignore list ---
newrepo mono
put app/Cargo.toml '[package]'; put legacy/package.json '{}'
mkdir -p "$R/.ekit"; printf 'ignore = ["samples"]\n' > "$R/.ekit/stack-plan.toml"
stack app app rust current; stack legacy legacy ts retiring; stack svc svc python planned
stack mob mob .ekit/adapters/kt.toml planned
commit base; B=$C
drift "base itself" "$B" "$B" 0
eq "base: D pass" "$(q .checks.D.status)" pass
has "base: summary names D" "$(q .summary)" "ran: D"
eq "base: one message" "$(q '.checks.D.messages | length')" 1
has "retiring message" "$(q '.checks.D.messages[0]')" "retiring stack \`legacy\`"
has "retiring message says finish" "$(q '.checks.D.messages[0]')" "finish the migration"

# PR: the planned svc's manifest appears, app's manifest disappears, manifests land in folders the check skips,
# and mob's (unwritten) adapter file would list build.gradle.kts
branch pr1 "$B"; put svc/pyproject.toml "$PY"; git -C "$R" rm -q app/Cargo.toml
for d in samples/demo tests/fx node_modules/x web/vendor/y build dist/z fixtures/a testdata/b examples/c third_party/d target/e; do
  put "$d/package.json" '{}'; done
put mob/build.gradle.kts ''
commit pr1
drift pr1 "$B" "$C" 0
eq "pr1: no fail entry" "$(q '.entries | length')" 0
eq "pr1: D pass" "$(q .checks.D.status)" pass
M=$(q '.checks.D.messages | join("\n")')
has "planned svc: its checks start" "$M" "planned stack \`svc\`"
has "planned svc: names its manifest" "$M" "svc/pyproject.toml"
has "planned svc: checks start" "$M" "its checks start"
has "vanished app: names the entry to remove" "$M" "remove the entry \`app\`"
has "retiring still there" "$M" "retiring stack \`legacy\`"
hasnt "unproven planned mob starts nothing" "$M" "planned stack \`mob\`"
eq "pr1: three messages" "$(q '.checks.D.messages | length')" 3
drift "pr1 text" "$B" "$C" 0 --format text
eq "pr1 text: message lines" "$(grep -c '^message: ' <<<"$OUT")" 3
has "pr1 text: first line pass" "$(head -1 <<<"$OUT")" "pass $C"

# PR: a manifest no stack covers blocks
branch pr2 "$B"; put tools/gen/package.json '{}'; commit pr2
drift pr2 "$B" "$C" 1
eq "pr2: D fail" "$(q .checks.D.status)" fail
eq "pr2: one entry" "$(q '[.entries[] | "\(.check) \(.class) \(.severity) \(.file)"] | join("|")')" "D adapter-fix fail .ekit/stack-plan.toml"
has "pr2: names the manifest" "$(q '.entries[0].problem')" "tools/gen/package.json"
has "pr2: id is D-" "$(q '.entries[0].id')" "D-"
has "pr2: summary" "$(q .summary)" "fail $C (1 fail"

# --- 56.3: two uncovered manifests: exactly one fail entry naming both ---
branch pr3 "$B"; put api/pyproject.toml "$PY"; put cli/Cargo.toml '[package]'; commit pr3
drift pr3 "$B" "$C" 1
eq "pr3: one entry" "$(q '.entries | length')" 1
eq "pr3: fail entries" "$(q '[.entries[] | select(.severity == "fail")] | length')" 1
eq "pr3: class" "$(q '.entries[0].class')" adapter-fix
has "pr3: names api" "$(q '.entries[0].problem')" "api/pyproject.toml"
has "pr3: names cli" "$(q '.entries[0].problem')" "cli/Cargo.toml"
drift "pr3 text" "$B" "$C" 1 --format text
eq "pr3 text: one fail line" "$(grep -c '^fail D-' <<<"$OUT")" 1

# --- 56.4: which plan judges ---
# a) the setup PR: manifests on base, no plan; the PR adds only the plan (and an adapter file): its own plan judges
newrepo setup; put web/package.json '{}'; put api/pyproject.toml "$PY"; put mob/build.gradle.kts ''; commit base; B=$C
branch setup "$B"; mkdir -p "$R/.ekit/adapters"; cp "$SPFX/kt.toml" "$R/.ekit/adapters/kt.toml"
stack web web ts current; stack api api python current; stack mob mob .ekit/adapters/kt.toml current; commit setup; SETUP=$C
drift "setup PR" "$B" "$C" 0
eq "setup PR: D pass" "$(q .checks.D.status)" pass
eq "setup PR: no entry" "$(q '.entries | length')" 0
# b) once the plan is on base, a PR adding a manifest and its entry together stays blocked
branch both "$SETUP"; put cli/Cargo.toml '[package]'; stack cli cli rust current; commit both
drift "manifest+entry" "$SETUP" "$C" 1
eq "manifest+entry: names only cli" "$(q '.entries[0].problem')" "manifests no stack in .ekit/stack-plan.toml covers: cli/Cargo.toml"
# ... and so does one where base has no plan at all (base judges, nothing covered)
branch both0 "$B"; put cli/Cargo.toml '[package]'; mkdir -p "$R/.ekit/adapters"; cp "$SPFX/kt.toml" "$R/.ekit/adapters/kt.toml"
stack web web ts current; stack api api python current; stack mob mob .ekit/adapters/kt.toml current; stack cli cli rust current; commit both0
drift "manifest+plan, no base plan" "$B" "$C" 1
has "no base plan: cli uncovered" "$(q '.entries[0].problem')" "cli/Cargo.toml"
# c) the plan lands first (plan-only PR), then the manifest: passes
branch planfirst "$SETUP"; stack cli cli rust planned; commit planfirst; PF=$C
drift "plan-only PR" "$SETUP" "$PF" 0
branch thenmanifest "$PF"; put cli/Cargo.toml '[package]'; commit thenmanifest
drift "manifest after its plan" "$PF" "$C" 0
has "manifest after its plan: checks start" "$(q '.checks.D.messages | join(" ")')" "its checks start"
# d) a PR changing only an adapter file is judged by its own plan: base's kt.toml lists the wrong manifest
newrepo adapteronly; put mob/build.gradle.kts ''; put web/package.json '{}'; mkdir -p "$R/.ekit/adapters"
sed 's/^manifests = .*/manifests = ["settings.gradle.kts"]/' "$SPFX/kt.toml" > "$R/.ekit/adapters/kt.toml"
stack web web ts current; stack mob mob .ekit/adapters/kt.toml current; commit base; B=$C
branch fix "$B"; cp "$SPFX/kt.toml" "$R/.ekit/adapters/kt.toml"; commit fix
drift "adapter-only PR" "$B" "$C" 0
eq "adapter-only PR: no entry" "$(q '.entries | length')" 0
# ... but an adapter-file edit that comes with a new manifest is judged by the base plan
branch fix2 "$B"; cp "$SPFX/kt.toml" "$R/.ekit/adapters/kt.toml"; put mob2/build.gradle.kts ''; commit fix2
drift "adapter edit + manifest" "$B" "$C" 1
has "adapter edit + manifest: mob2 named" "$(q '.entries[0].problem')" "mob2/build.gradle.kts"
echo "stack-plan ok"
