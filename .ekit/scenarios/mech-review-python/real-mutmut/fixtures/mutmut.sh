# shared setup for the real-mutmut scenarios (sourced after lib.sh; not a scenario). cwd = the scenario's temp dir.
MR="$EKIT_REPO/scripts/mech-review.py"
export PIP_DISABLE_PIP_VERSION_CHECK=1
# the user's CI install: a fresh venv with the pinned tools; real mutmut and pytest resolve from it
python3 -m venv v && v/bin/pip install -q pytest==9.2.0 mutmut==3.8.1 || fail "pip install pytest mutmut failed"
export PATH="$PWD/v/bin:$PATH"
[[ "$(command -v mutmut)" == "$PWD/v/bin/mutmut" ]] || fail "mutmut does not resolve to the venv"

# mech-review with a hard limit (macOS has no `timeout`): kills the whole process group, exit 124 on timeout.
# usage: mr <subcommand> <args...>; stdout = the JSON, stderr kept in $PWD/mr.err
mr() { python3 - "$MR" "$@" 2>"$PWD/mr.err" <<'PY'
import os, signal, subprocess, sys
p = subprocess.Popen([sys.executable, *sys.argv[1:]], start_new_session=True)
try:
    sys.exit(p.wait(timeout=float(os.environ.get("MR_LIMIT", "150"))))
except subprocess.TimeoutExpired:
    os.killpg(p.pid, signal.SIGKILL); p.wait(); print("mech-review timed out", file=sys.stderr); sys.exit(124)
PY
}
# a mutants run on base..head of repo $R: mutants_run <base> <head> [extra args]
mutants_run() { local b="$1" h="$2"; shift 2
  mr mutants --repo "$R" --base "$b" --head "$h" --stack python --test-paths 'tests/**' "$@"; }

# sample repo in $R: src layout, tests read a tracked docs/ file, load a tracked scripts/ file by path,
# and read a tracked data file inside the source dir; is_positive is weakly tested, add is well tested.
# mk_py_repo [docs-test=1]
mk_py_repo() { R="$PWD/repo"; rm -rf "$R"; mkdir -p "$R/src/calc/assets" "$R/tests" "$R/docs" "$R/scripts"
  git -C "$R" init -q -b main
  printf '[project]\nname = "calc"\nversion = "0.0.1"\n\n[tool.pytest.ini_options]\npythonpath = ["src"]\n' > "$R/pyproject.toml"
  : > "$R/src/calc/__init__.py"
  printf 'def add(a, b):\n    return a + b\n\n\ndef is_positive(n):\n    return n > 0\n' > "$R/src/calc/core.py"
  printf 'units: cm\n' > "$R/src/calc/assets/units.txt"
  printf '# Usage\n\nRun `calc add 1 2`.\n' > "$R/docs/usage.md"
  printf 'def greet(name):\n    return "hello " + name\n' > "$R/scripts/tool.py"
  cat > "$R/tests/test_core.py" <<'PY'
from pathlib import Path

from calc.core import add, is_positive

ROOT = Path(__file__).resolve().parent.parent


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0


def test_is_positive():
    assert is_positive(5)


def test_units_asset():
    assert (ROOT / "src" / "calc" / "assets" / "units.txt").read_text() == "units: cm\n"
PY
  cat > "$R/tests/test_repo_files.py" <<'PY'
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_script_by_path():
    spec = importlib.util.spec_from_file_location("tool", ROOT / "scripts" / "tool.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.greet("x") == "hello x"
PY
  if [[ "${1:-1}" == 1 ]]; then cat >> "$R/tests/test_repo_files.py" <<'PY'


def test_docs_mention_add():
    assert "calc add" in (ROOT / "docs" / "usage.md").read_text()
PY
  fi
  git -C "$R" add -A; git -C "$R" commit -qm base; BASE=$(git -C "$R" rev-parse HEAD)
  (cd "$R" && python3 -m pytest -q -p no:cacheprovider >/dev/null) || fail "sample tests fail at base"; }
# head that changes both functions (is_positive's change survives `0 < n -> 0 <= n`): sets HEAD_BOTH
head_both() { git -C "$R" checkout -q -b both "$BASE"
  printf 'def add(a, b):\n    return b + a\n\n\ndef is_positive(n):\n    return 0 < n\n' > "$R/src/calc/core.py"
  git -C "$R" commit -qam both; HEAD_BOTH=$(git -C "$R" rev-parse HEAD); }
# R3 ran its mutants and reports exactly the is_positive MISSED on core.py:6: check_missed <out> <rc> <head> <label>
check_missed() {
  eq "$4 exit" "$2" 1
  eq "$4 R3" "$(jq -r .checks.R3.status <<<"$1")" fail
  hasnt "$4 note" "$(jq -r .checks.R3.note <<<"$1")" "baseline tests fail"
  eq "$4 entries" "$(jq -r '[.entries[] | select(.check=="R3") | "\(.file):\(.line):\(.class)"] | unique | join(" ")' <<<"$1")" "src/calc/core.py:6:agent-fixable"
  has "$4 problem" "$(jq -r '[.entries[].problem] | join(" | ")' <<<"$1")" "MISSED mutant src/calc/core.py:6: return 0 < n -> return 0 <= n"
  hasnt "$4 add caught" "$(jq -r '[.entries[].problem] | join(" | ")' <<<"$1")" "core.py:2"
  has "$4 summary" "$(jq -r .summary <<<"$1")" "fail $3 ("; }
