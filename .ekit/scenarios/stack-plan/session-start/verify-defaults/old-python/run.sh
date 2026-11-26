#!/bin/bash
source "$EKIT_PARENT_DIR/fixtures/lib.sh"
# the hooks' python3 is 3.9: through uv (its installed 3.9, offline), else a python3.9 or 3.10 on PATH put first as python3
UVRUN=(env HOME="$OLDHOME" UV_OFFLINE=1 uv run -q --offline --no-project --python 3.9 -- env HOME="$HOME")
if command -v uv >/dev/null && V=$("${UVRUN[@]}" python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) && [[ $V == 3.9 ]]; then
  WRAP=("${UVRUN[@]}")
else
  OLD=$(command -v python3.9 || command -v python3.10) || fail "unrunnable here: no python 3.9 (uv python install 3.9, or python3.9 on PATH)"
  mkdir -p "$PWD/oldbin"; ln -sf "$OLD" "$PWD/oldbin/python3"; WRAP=(env PATH="$PWD/oldbin:$PATH")
  V=$("${WRAP[@]}" python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
fi
"${WRAP[@]}" python3 -c 'import sys; sys.exit(sys.version_info >= (3, 11))' || fail "the hooks' python3 is not older than 3.11"

# 61.5: a plan of two current stacks, the one project auto finds, a repo adapter file: one line, nothing declared
for kind in plan solo own; do
  newrepo "$kind"
  case $kind in
    plan) web_adapter .ekit/adapters/web.toml; put web/package.json '{"devDependencies": {"jest": "29"}}'
          put api/pyproject.toml '[project]'; stack web web .ekit/adapters/web.toml current; stack api api python current ;;
    solo) put package.json '{"devDependencies": {"jest": "29"}}' ;;
    own) put build.gradle.kts 'x'; tool_adapter tool $'[commands]\ninstall = ""\nbuild = "true"\nlint = ""\ntest = "true"' ;;
  esac
  commit base; start "$R" "s-$kind" "${WRAP[@]}"
  eq "$kind: one Verify defaults line" "$(grep -c '^\[ekit\] Verify defaults' <<<"$CTX")" 1
  has "$kind: nothing declared" "$VD" "none declared"
  has "$kind: names the version needed" "$VD" "3.11"; has "$kind: names this python" "$VD" "$V"
  hasnt "$kind: no command shown" "$VD" "task-verify.py --repo"
  none_declared "$kind" "s-$kind"
done
echo "stack-plan/session-start/verify-defaults/old-python ok ($V)"
