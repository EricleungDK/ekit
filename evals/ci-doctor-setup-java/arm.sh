# Sourced by each ci-doctor-setup-* setup.sh after its scaffold commit (#23). Arms the grader support: whenever HEAD or
# a ref moves (commit, reset, checkout, merge, rebase), .git/ekit-eval/verdict.py (written below: a heredoc, so the kit
# tracks no python file outside its test paths) reads the end state at HEAD of the main checkout and writes
# .git/ekit-eval/verdict.txt, which the regex graders read. $1: the case's expect.json (the script's header). The kit's
# path is data in a file, never shell text.
arm_verdict() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  mkdir -p .git/ekit-eval
  printf '%s' "$(cd "$here/../.." && pwd -P)" > .git/ekit-eval/kit
  printf '%s\n' "$1" > .git/ekit-eval/expect.json
  git rev-parse HEAD > .git/ekit-eval/start
  cat > .git/ekit-eval/verdict.py <<'PY'
# The end state of a ci-doctor setup eval (#23), read at HEAD of the main checkout by the scaffold's ref hooks and
# written to .git/ekit-eval/verdict.txt for the regex graders. Every ci-doctor-setup-* case's arm_verdict writes it
# into .git/ekit-eval/ with its expect.json: {"status": "current" | "planned", "folder", "target_os", "ci": "keep" | "write"}.
# The case's scaffold commit is .git/ekit-eval/start; `setup: yes` needs every line it checks at once. Git and the kit's
# own engine only (r0, static half; drift); nothing printed. A harness problem (no kit, no tomllib) says `harness:`.
import json
import os
import subprocess
import sys

here = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True,
                      text=True).stdout.strip()  # the main checkout's .git, from it or from any linked worktree
repo = os.path.dirname(here)
env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                                                        "GIT_OBJECT_DIRECTORY", "GIT_PREFIX")}
CALLER = "EricleungDK/ekit/.github/workflows/mech-review.yml@"
WAIVER = "EricleungDK/ekit/.github/workflows/mech-waive.yml@"


def git(*a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, env=env)


def read(name):
    with open(os.path.join(here, "ekit-eval", name), encoding="utf-8") as f:
        return f.read()


def workflows(ref):
    """{path: blob sha} of the workflow files at ref"""
    out = git("ls-tree", ref, ".github/workflows/").stdout.splitlines()
    return {line.split("\t", 1)[1]: line.split()[2] for line in out
            if line.split("\t", 1)[1].endswith((".yml", ".yaml"))}


expect, kit, start = json.loads(read("expect.json")), read("kit"), read("start").strip()
engine = os.path.join(kit, "scripts", "mech-review.py")
lines, ok = [], []
branch = git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip() or "(detached)"
lines.append(f"branch: {branch}")
ok.append(branch not in ("main", "(detached)"))
main_moved = git("rev-parse", "refs/heads/main").stdout.strip() != start
lines.append(f"main: {'moved' if main_moved else 'untouched'}")
ok.append(not main_moved)
new = git("rev-list", "--count", "--branches", "--not", start).stdout.strip() or "0"
lines.append(f"new-commits: {new}")

entry, adapter = None, {}
try:
    import tomllib
except ImportError:
    tomllib = None
    lines.append("entry: not read: harness: no tomllib (python 3.11 or newer runs the hooks)")
if tomllib:
    try:
        stacks = tomllib.loads(git("show", "HEAD:.ekit/stack-plan.toml").stdout).get("stack", [])
    except Exception as e:  # no plan at HEAD, or not TOML
        stacks = []
        lines.append(f"plan: does not read ({type(e).__name__})")
    mine = [s for s in stacks if isinstance(s, dict) and s.get("folder") == expect["folder"]
            and str(s.get("adapter", "")).endswith(".toml")]
    entry = mine[0] if mine else None
    if entry:
        shown = git("show", f"HEAD:{entry['adapter']}")
        try:
            adapter = tomllib.loads(shown.stdout) if shown.returncode == 0 else {}
        except Exception:
            adapter = {}
        lines.append(f"entry: {entry.get('name')} adapter {entry['adapter']} status {entry.get('status')}")
    else:
        lines.append(f"entry: none (no plan entry for folder {expect['folder']!r} naming an adapter file)")
ok.append(bool(entry) and entry.get("status") == expect["status"])
target = (entry or {}).get("target-os") or adapter.get("target-os") or "linux"
lines.append(f"target-os: {target}")
ok.append(target == expect["target_os"])


def engine_run(*args):
    r = subprocess.run([sys.executable, "-I", engine, *args, "--repo", repo, "--base", "HEAD", "--head", "HEAD"],
                       capture_output=True, text=True, env=env)
    try:
        return r, json.loads(r.stdout)
    except ValueError:
        return r, None


if not os.path.isfile(engine):
    lines.append(f"r0: not run: harness: the kit's scripts/mech-review.py is not at {kit!r} (not the model's doing)")
    lines.append("drift: not run: harness: no kit")
    ok.append(False)
else:
    if not entry or not adapter.get("name"):
        lines.append("r0: not run (no plan entry with an adapter file that reads at HEAD)")
        ok.append(False)
    else:
        r, result = engine_run("r0", "--stack", str(adapter["name"]), "--project-dir", expect["folder"])
        r0 = (result or {}).get("checks", {}).get("R0") or {}
        if r0.get("status") == "pass":
            lines.append(f"r0: pass ({r0.get('note')})")
        else:
            why = [e.get("problem") for e in (result or {}).get("entries", [])] or [r0.get("note")]
            why = why if why != [None] else [(r.stderr.strip().splitlines() or ["no output"])[0]]
            lines.append(f"r0: not pass (exit {r.returncode}, R0 {r0.get('status')}: {'; '.join(why)[:400]})")
        ok.append(r0.get("status") == "pass")
    r, result = engine_run("drift", "--format", "json")
    d = (result or {}).get("checks", {}).get("D") or {}
    clean = r.returncode == 0 and d.get("status") == "pass" and not (result or {}).get("entries")
    lines.append(f"drift: {'clean' if clean else 'not clean'} (exit {r.returncode}, "
                 + (f"D {d.get('status')}, {len((result or {}).get('entries', []))} entries)" if d else "no plan: no D)"))
    ok.append(clean)

flows, before = workflows("HEAD"), workflows(start)
texts = {p: git("show", f"HEAD:{p}").stdout for p in flows}
caller = any(CALLER in t for t in texts.values())
lines.append(f"caller: {'yes' if caller else 'no'}")
ok.append(caller)
kept = all(flows.get(p) == sha for p, sha in before.items())
lines.append(f"ci-kept: {'yes' if kept else 'no'}")
ok.append(kept)
added = sorted(p for p in flows if p not in before and CALLER not in texts[p] and WAIVER not in texts[p])
test_cmd = (adapter.get("commands") or {}).get("test") if isinstance(adapter.get("commands"), dict) else None
if not added:
    lines.append("base-jobs: none")
elif test_cmd and any(test_cmd in texts[p] for p in added):
    lines.append(f"base-jobs: yes ({', '.join(added)} run `{test_cmd}`)")
else:
    lines.append(f"base-jobs: no test command ({', '.join(added)} never run the adapter's [commands] test)")
ok.append(lines[-1].startswith("base-jobs: yes" if expect["ci"] == "write" else "base-jobs: none"))
lines.append(f"setup: {'yes' if all(ok) else 'no'}")
with open(os.path.join(here, "ekit-eval", "verdict.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
PY
  # reference-transaction: every ref update; post-checkout: a switch of HEAD alone. Never fails the model's git command
  printf '#!/bin/sh\n[ "$1" = committed ] || exit 0\npython3 -I "$(git rev-parse --path-format=absolute --git-common-dir)/ekit-eval/verdict.py" >/dev/null 2>&1\nexit 0\n' > .git/hooks/reference-transaction
  printf '#!/bin/sh\npython3 -I "$(git rev-parse --path-format=absolute --git-common-dir)/ekit-eval/verdict.py" >/dev/null 2>&1\nexit 0\n' > .git/hooks/post-checkout
  chmod +x .git/hooks/reference-transaction .git/hooks/post-checkout
  python3 -I .git/ekit-eval/verdict.py  # the start state's verdict
}
