# shared by mech-review-doctor/sandbox and its children (sourced after lib.sh; not a scenario). cwd = the scenario's temp dir.
# The user's install: a fresh venv with pytest 9.2.0 and mutmut 3.8.1 first on PATH, and `mr` (mech-review under a hard
# time limit, exit 124 on a hang, stderr in $PWD/mr.err), both from the real-mutmut helper.
source "$EKIT_REPO/.ekit/scenarios/mech-review-python/real-mutmut/fixtures/mutmut.sh"
export MR_LIMIT=90
# after pip, so its own temp files do not count: doctor must leave this empty
export TMPDIR="$PWD/tmp"; mkdir -p "$TMPDIR"

# what `git` sees of a repo: HEAD, refs, status (ignored files too), worktrees, stashes
snapshot() { git -C "$1" rev-parse HEAD; git -C "$1" for-each-ref; git -C "$1" status --porcelain --ignored; git -C "$1" worktree list; git -C "$1" stash list; }
commit() { git -C "$1" add -A; git -C "$1" commit -qm "${2:-c}"; }

# py_repo <dir> [project dir, default .]: src layout, a test of add, and the mech-review caller doctor asks for
# (so a sandbox problem is the only entry left). Not committed: the caller adds tests and commits.
py_repo() { local r="$1" p="${2:-.}" d; d="$1/$p"; mkdir -p "$d/src/calc" "$d/tests" "$r/.github/workflows"; git -C "$r" init -q -b main
  printf '[project]\nname = "calc"\nversion = "0.0.1"\n\n[tool.pytest.ini_options]\npythonpath = ["src"]\n' > "$d/pyproject.toml"
  : > "$d/src/calc/__init__.py"
  printf 'def add(a, b):\n    return a + b\n' > "$d/src/calc/core.py"
  printf 'from calc.core import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n' > "$d/tests/test_core.py"
  local with='      stack: python
      test-paths: tests/**'
  [[ "$p" == . ]] || with="      stack: python
      project-dir: $p
      test-paths: $p/tests/**"
  printf 'name: mech-review\non: pull_request\njobs:\n  mech-review:\n    uses: EricleungDK/ekit/.github/workflows/mech-review.yml@v0\n    with:\n%s\n' "$with" > "$r/.github/workflows/mech-review.yml"; }

# tests that read docs/usage.md (relative to __file__) in project dir <d>
docs_test() { mkdir -p "$1/docs"; printf '# Usage\n\nRun `calc add 1 2`.\n' > "$1/docs/usage.md"
  printf 'from pathlib import Path\n\nROOT = Path(__file__).resolve().parent.parent\n\n\ndef test_docs_mention_add():\n    assert "calc add" in (ROOT / "docs" / "usage.md").read_text()\n' > "$1/tests/test_docs.py"; }

# each pytest and doctor run's output is kept in the artifact dir (#44: a rare load flake left only its ASSERT line);
# on a failed assert they also go to stderr, so the runner's kept failure transcript holds the real error
SAVE="${EKIT_ARTIFACT_DIR:-$PWD}"
save_as() { printf '%s/%s' "$SAVE" "${1//[^A-Za-z0-9._-]/_}"; }
trap 'rc=$?; if (( rc )); then for f in "$SAVE"/plain-* "$SAVE"/doctor-*; do [[ -f $f ]] && { echo "--- ${f##*/}"; cat "$f"; } >&2; done; fi' EXIT

# the plain suite passes in the user's checkout (so a doctor fail is about the sandbox): plain_ok <project dir> <label>
plain_ok() { local o; o=$(save_as "plain-$2.out")
  (cd "$1" && python3 -m pytest -q -p no:cacheprovider >"$o" 2>&1) || fail "$2: tests do not pass in the checkout"; }

# run doctor on repo $1 with args, under the limit; sets OUT and RC; fails on a hang or a traceback
# and asserts doctor wrote nothing, left one worktree and an empty TMPDIR: doc <label> <repo> [args]
doc() { local l="$1" r="$2" before; shift 2; before=$(snapshot "$r")
  OUT=$(mr doctor --repo "$r" "$@"); RC=$?
  cp "$PWD/mr.err" "$(save_as "doctor-$l.err")"; printf '%s\n' "$OUT" > "$(save_as "doctor-$l.json")"
  [[ $RC != 124 ]] || fail "$l: doctor hung (killed after ${MR_LIMIT}s)"
  hasnt "$l no traceback" "$(cat "$PWD/mr.err")" "Traceback"
  jq -e . >/dev/null <<<"$OUT" || fail "$l: stdout is not JSON: [$OUT] stderr [$(cat "$PWD/mr.err")]"
  eq "$l git state unchanged" "$(snapshot "$r")" "$before"
  eq "$l one worktree" "$(git -C "$r" worktree list | lines)" 1
  eq "$l no temp dir left" "$(ls -A "$TMPDIR" | lines)" 0; }
# one env entry, sandbox fail, exit 1: sandbox_fail <label>; the entry's problem and hint are in PROBLEM and HINT
sandbox_fail() {
  eq "$1 exit" "$RC" 1
  eq "$1 tests" "$(jq -r .trial.tests <<<"$OUT")" pass
  eq "$1 sandbox" "$(jq -r .trial.sandbox <<<"$OUT")" fail
  eq "$1 one entry" "$(jq -r '.entries|length' <<<"$OUT")" 1
  eq "$1 class" "$(jq -r '.entries[0].class' <<<"$OUT")" env
  has "$1 summary" "$(jq -r .summary <<<"$OUT")" "fail $(jq -r .head <<<"$OUT") (1 problems)"
  PROBLEM=$(jq -r '.entries[0].problem' <<<"$OUT"); HINT=$(jq -r '.entries[0].hint' <<<"$OUT"); }
# no problems, sandbox pass, exit 0: sandbox_ok <label>
sandbox_ok() {
  eq "$1 exit" "$RC" 0
  eq "$1 trial" "$(jq -c .trial <<<"$OUT")" '{"tests":"pass","command":"python3 -m pytest","mutation_tool":"present","sandbox":"pass"}'
  eq "$1 entries" "$(jq -c '[.entries[]|.problem]' <<<"$OUT")" '[]'
  eq "$1 summary" "$(jq -r .summary <<<"$OUT")" "ok $(jq -r .head <<<"$OUT")"; }
