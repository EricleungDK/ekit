#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_SCENARIO_DIR/fixtures/sandbox.sh"

# 2. 5b: tests read a tracked top-level docs/ file and load a tracked scripts/ file by path: sandbox pass, ok
R="$PWD/root"; py_repo "$R"; docs_test "$R"; mkdir -p "$R/scripts"
printf 'def greet(name):\n    return "hello " + name\n' > "$R/scripts/tool.py"
cat > "$R/tests/test_script.py" <<'PY'
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_script_by_path():
    spec = importlib.util.spec_from_file_location("tool", ROOT / "scripts" / "tool.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.greet("x") == "hello x"
PY
commit "$R" base; plain_ok "$R" root
doc root "$R"; sandbox_ok root
eq "root detected" "$(jq -c .detected <<<"$OUT")" '{"stack":"python","project_dir":"."}'
eq "root head" "$(jq -r .head <<<"$OUT")" "$(git -C "$R" rev-parse HEAD)"
doc "root --stack python" "$R" --stack python; sandbox_ok "root --stack python"

# 3. 5e: plain tests fail: no sandbox verdict
F="$PWD/failing"; py_repo "$F"; sed -i.bak 's/== 5/== 6/' "$F/tests/test_core.py"; rm "$F/tests/test_core.py.bak"; commit "$F" base
doc failing "$F"
eq "failing exit" "$RC" 1
eq "failing tests" "$(jq -r .trial.tests <<<"$OUT")" fail
eq "failing sandbox" "$(jq -r .trial.sandbox <<<"$OUT")" skipped
has "failing entry" "$(jq -r '[.entries[].problem]|join(" | ")' <<<"$OUT")" 'python3 -m pytest'
echo "doctor sandbox ok"
