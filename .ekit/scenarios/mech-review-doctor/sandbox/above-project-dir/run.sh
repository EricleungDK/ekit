#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
source "$EKIT_PARENT_DIR/fixtures/sandbox.sh"

# 1. project in app/, its tests read ../docs/guide.md (above the project dir)
R="$PWD/above"; py_repo "$R" app; mkdir -p "$R/docs"; printf '# Guide\n\nRun `calc add 1 2`.\n' > "$R/docs/guide.md"
cat > "$R/app/tests/test_guide.py" <<'PY'
from pathlib import Path

APP = Path(__file__).resolve().parent.parent


def test_guide_mentions_add():
    assert "calc add" in (APP / ".." / "docs" / "guide.md").read_text()
PY
commit "$R" base; plain_ok "$R/app" above

# 2. passes in the checkout, fails in R3's copy: an env entry that names the missing file
doc above "$R" --project-dir app; sandbox_fail above
has "above names the file" "$PROBLEM" '../docs/guide.md'
hasnt "above not ok" "$(jq -r .summary <<<"$OUT")" "ok "
doc "above detected" "$R"; sandbox_fail "above detected"
eq "above detected dir" "$(jq -r .detected.project_dir <<<"$OUT")" app
has "above detected names the file" "$PROBLEM" '../docs/guide.md'

# 3. control: the guide inside the project dir is in R3's copy
C="$PWD/inside"; py_repo "$C" app; docs_test "$C/app"; commit "$C" base; plain_ok "$C/app" inside
doc inside "$C" --project-dir app; sandbox_ok inside
echo "doctor above-project-dir ok"
