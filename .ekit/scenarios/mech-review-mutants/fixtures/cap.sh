# shared setup for the R3 cap scenarios (sourced after lib.sh; not a scenario). cwd = the scenario's temp dir.
# Fake cargo-mutants (fake_cargo_mutants.py, see its header) answers `--list --json` from a generated listing of
# 10 functions x 6 mutants (gen_list.py: per function 3 branch conditions, 1 return, 1 arithmetic, 1 other).
MR="$EKIT_REPO/scripts/mech-review.py"
CAPFX="$EKIT_REPO/.ekit/scenarios/mech-review-mutants/fixtures"
STUB="$PWD/fake-cargo-mutants"; cp "$CAPFX/fake_cargo_mutants.py" "$STUB"; chmod +x "$STUB"
python3 "$CAPFX/gen_list.py" 10 > "$PWD/list60.json" || fail "gen_list failed"
export FAKE_LIST="$PWD/list60.json"

R="$PWD/repo"; mkdir -p "$R/src" "$R/tests"; git -C "$R" init -q -b main
printf 'pub fn add(a: i32, b: i32) -> i32 { a + b }\n' > "$R/src/lib.rs"
printf '#[test]\nfn adds() {\n    assert_eq!(add(1, 2), 3);\n}\n' > "$R/tests/a.rs"
printf '[package]\nname = "x"\nversion = "0.1.0"\n' > "$R/Cargo.toml"
git -C "$R" add -A; git -C "$R" commit -qm base; B=$(git -C "$R" rev-parse HEAD)
printf 'pub fn add(a: i32, b: i32) -> i32 { a + b } // fixed\n' > "$R/src/lib.rs"
git -C "$R" add -A; git -C "$R" commit -qm head; H=$(git -C "$R" rev-parse HEAD)

mut() { MECH_TEST_STUB="$STUB" python3 -I "$MR" mutants --repo "$R" --base "$B" --head "$H" --stack rust --test-paths 'tests/**' "$@"; }
bl() { MECH_TEST_STUB="$STUB" python3 -I "$MR" baseline --repo "$R" --base "$B" --head "$H" --stack rust --test-paths 'tests/**' "$@"; }
mrg() { python3 -I "$MR" merge --repo "$R" --base "$B" --head "$H" --stack rust "$@"; }
r3() { jq -r .checks.R3.status <<<"$1"; }
note() { jq -r .checks.R3.note <<<"$1"; }
nmissed() { jq -r '[.entries[] | select(.check=="R3" and (.problem | startswith("MISSED")))] | length' <<<"$1"; }
# names of the listed mutants by kind, in listing (= position) order: kind <regex>
kind() { jq -r --arg r "$1" '.[] | select(.name | test($r)) | .name' "$FAKE_LIST"; }
# the expected risk-ordered pick: the branch conditions of f0, f1, ... in position order, then the returns
BRANCH='(replace > with ==|delete !|replace match guard with true) in f[0-9]+$'
