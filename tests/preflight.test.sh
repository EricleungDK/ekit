source "$(dirname "$0")/lib.sh"
PF="$ROOT/scripts/preflight.sh"
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT  # physical path: macOS temp dirs sit behind a symlink
# the host's browser must not reach preflight: GitHub's ubuntu image sets CHROME_BIN, which made the
# "no chromium" cases see one (the release run for v0.2.5 failed on them)
unset CHROME_BIN PLAYWRIGHT_BROWSERS_PATH

run() { PATH="$1" HOME="$T/home" bash "$PF" "$2" 2>&1; }

# bare python missing, python3 present
B="$T/b1"; fakebin "$B" python3; P="$T/p1"; mkdir -p "$P"
out="$(run "$B" "$P")"
has "$out" "python: missing → use python3" "bare python missing → fallback python3"
has "$out" "jq: missing → python3 -c 'import json'" "jq missing → fallback"
has "$out" "rg: missing → grep -rn / find" "rg missing → fallback"
lacks "$out" "cargo" "no Cargo.toml → no cargo check"
lacks "$out" "docker" "no Dockerfile → no docker check"

# all present → quiet output only has ok lines; --quiet prints nothing
B="$T/b2"; fakebin "$B" python3 jq; stub "$B" python 'exec python3 "$@"'; stub "$B" rg 'exit 0'
out="$(PATH="$B" HOME="$T/home" bash "$PF" --quiet "$P" 2>&1)"
eq "$out" "" "--quiet with nothing wrong prints nothing"

# python project without .venv
P="$T/p3"; mkdir -p "$P"; touch "$P/pyproject.toml"
out="$(run "$T/b2" "$P")"
has "$out" "venv: no .venv → uv sync, then uv run <cmd>" "pyproject without .venv"
mkdir "$P/.venv"; out="$(run "$T/b2" "$P")"
lacks "$out" "venv:" ".venv present → no warning"

# rust project without cargo
P="$T/p4"; mkdir -p "$P"; touch "$P/Cargo.toml"
out="$(run "$T/b2" "$P")"
has "$out" "cargo: missing → Cargo.toml present; rust build/test can't run here" "Cargo.toml without cargo"

# node engines mismatch
P="$T/p5"; mkdir -p "$P"; echo '{"engines":{"node":">=22"}}' > "$P/package.json"
B="$T/b5"; fakebin "$B" python3 jq; stub "$B" node 'echo v20.1.0'
out="$(run "$B" "$P")"
has "$out" "node: v20.1.0 < engines >=22 → nvm use 22" "node below engines"
stub "$B" node 'echo v24.0.0'; out="$(run "$B" "$P")"
lacks "$out" "node:" "node satisfies engines"

# docker project, docker unusable
P="$T/p6"; mkdir -p "$P"; touch "$P/docker-compose.yml"
B="$T/b6"; fakebin "$B" python3 jq; stub "$B" docker 'echo "permission denied while trying to connect to the Docker daemon socket" >&2; exit 1'
out="$(run "$B" "$P")"
has "$out" "docker: unusable (permission denied" "docker perm denied surfaced"
has "$out" "container tests → verification debt" "docker fallback stated"

# playwright project, no chromium
P="$T/p7"; mkdir -p "$P"; echo '{"devDependencies":{"@playwright/test":"1.0"}}' > "$P/package.json"
out="$(run "$T/b2" "$P")"
has "$out" "playwright: no chromium in the ms-playwright cache or \$CHROME_BIN → npx playwright install chromium" "playwright no browser"
mkdir -p "$T/home/.cache/ms-playwright/chromium-1/chrome-linux64"; touch "$T/home/.cache/ms-playwright/chromium-1/chrome-linux64/chrome"
out="$(run "$T/b2" "$P")"
lacks "$out" "playwright:" "chromium found in the Linux cache"
rm -rf "$T/home/.cache"; mkdir -p "$T/home/Library/Caches/ms-playwright/chromium-1200/chrome-mac"
out="$(run "$T/b2" "$P")"
lacks "$out" "playwright:" "chromium found in the macOS cache"
rm -rf "$T/home/Library"; mkdir -p "$T/pwb/chromium_headless_shell-1200"
out="$(PLAYWRIGHT_BROWSERS_PATH="$T/pwb" run "$T/b2" "$P")"
lacks "$out" "playwright:" "chromium found under PLAYWRIGHT_BROWSERS_PATH"
out="$(run "$T/b2" "$P")"
has "$out" "playwright: no chromium" "no cache anywhere → warning again"
mkdir -p "$T/home/.cache/ms-playwright/chromium-1/chrome-linux64"

# gh present but not authed
B="$T/b8"; fakebin "$B" python3 jq; stub "$B" gh '[[ $1 == auth ]] && exit 1; exit 0'
out="$(run "$B" "$T/p1")"
has "$out" "gh: not authed → user runs: ! gh auth login" "gh unauthed"
has "$out" "gh issue view: always pass --json" "gh --json gotcha"

# a host with no `timeout` (stock macOS): a working gh and docker are not reported broken
nt() { local d="$1"; shift; mkdir -p "$d"; for t in bash sh env grep sed head cat "$@"; do ln -sf "$(command -v "$t")" "$d/$t"; done; }
P="$T/p8"; mkdir -p "$P"; touch "$P/Dockerfile"
for helper in none perl; do
  B="$T/nt-$helper"; nt "$B" python3; [[ $helper == perl ]] && nt "$B" perl
  stub "$B" gh 'exit 0'; stub "$B" docker 'exit 0'
  out="$(run "$B" "$P")"
  lacks "$out" "timeout: command not found" "no timeout ($helper): no shell error leaks"
  has "$out" "ok gh" "no timeout ($helper): authed gh is ok"
  has "$out" "ok docker" "no timeout ($helper): working docker is ok"
done
stub "$T/nt-perl" gh '[[ $1 == auth ]] && exit 1; exit 0'
has "$(run "$T/nt-perl" "$P")" "gh: not authed" "no timeout: an unauthed gh is still reported"
stub "$T/nt-perl" docker 'sleep 30'
t0=$SECONDS; out="$(run "$T/nt-perl" "$P")"
has "$out" "docker: unusable" "no timeout: a hung docker is unusable"
(( SECONDS - t0 < 15 )) && ok "no timeout: perl bounds a hung docker" || fail "no timeout: perl bounds a hung docker"

# .git read-only
P="$T/p9"; mkdir -p "$P/.git"; chmod a-w "$P/.git"
out="$(run "$T/b2" "$P")"
if [[ -w $P/.git ]]; then skip ".git read-only" "this user writes through mode bits (root)"
else has "$out" "git: .git read-only (sandbox) → commits need unsandboxed run" ".git read-only"; fi
chmod u+w "$P/.git"

# loopback bind blocked (stub python3 failing bind probe)
B="$T/b10"; fakebin "$B" jq; stub "$B" python3 '[[ "$*" == *bind* ]] && { echo "PermissionError: [Errno 1] Operation not permitted" >&2; exit 1; }; exit 0'
out="$(run "$B" "$T/p1")"
has "$out" "loopback: bind 127.0.0.1 blocked (sandbox) → server/e2e tests need unsandboxed run" "loopback blocked"

# scenarios marker: missing driver tools warn, for the tools the scenarios name
P="$T/p11"; mkdir -p "$P/.ekit/scenarios/a"
printf 'tmux new -d -s t\nexpect -c "spawn x"\ncurl -s localhost\n' > "$P/.ekit/scenarios/a/run.sh"
out="$(run "$T/b2" "$P")"
for t in tmux expect curl; do
  has "$out" "$t: missing → scenarios needing $t can't run here → human verdict / verification debt" "scenarios + no $t"
done
B="$T/b11"; fakebin "$B" python3 jq; for t in tmux expect curl; do stub "$B" $t "exit 0"; done
out="$(run "$B" "$P")"
lacks "$out" "tmux:" "tmux present → no warning"
lacks "$out" "expect:" "expect present → no warning"
lacks "$out" "curl:" "curl present → no warning"
out="$(run "$T/b2" "$T/p1")"
lacks "$out" "tmux:" "no scenarios → no tmux check"
lacks "$out" "curl:" "no scenarios → no curl check"
out="$(PATH="$B" HOME="$T/home" bash "$PF" --quiet "$P" 2>&1)"
lacks "$out" "ok tmux" "--quiet hides ok driver lines"
out="$(run "$B" "$P")"
has "$out" "ok tmux" "driver present → ok line"

# a scenario that drives none of them: no driver warning at all
P="$T/p11b"; mkdir -p "$P/.ekit/scenarios/a"; echo 'python3 app.py --help' > "$P/.ekit/scenarios/a/run.sh"
out="$(run "$T/b2" "$P")"
for t in tmux expect curl playwright; do lacks "$out" "$t:" "scenarios never name $t → no $t warning"; done

# playwright check also applies when a scenario drives playwright (no playwright dep)
rm -rf "$T/home/.cache"
P="$T/p12"; mkdir -p "$P/.ekit/scenarios/a"; echo 'npx playwright test' > "$P/.ekit/scenarios/a/run.sh"
out="$(run "$T/b2" "$P")"
has "$out" "playwright: no chromium" "a playwright scenario triggers the playwright check"
P="$T/p13"; mkdir -p "$P"
out="$(run "$T/b2" "$P")"
lacks "$out" "playwright:" "no marker → no playwright check"

done_tests
