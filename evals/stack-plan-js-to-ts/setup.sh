#!/bin/bash
# fixture: a JS package (package.json, src/greet.js, test/greet.test.js) whose committed stack plan lists it as one
# current stack, `js` (adapter ts: the built-in covers JS and TS). The run should end with a TS entry in the plan, `js`
# retiring, and a drift check that names no uncovered manifest (#57), all read at HEAD.
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n' >> .git/info/exclude  # sandbox HOME files: not the work, keep the finish gate quiet
cat > package.json <<'JSON'
{
  "name": "greet",
  "version": "1.0.0",
  "type": "module",
  "main": "src/greet.js",
  "scripts": { "test": "node --test test/" }
}
JSON
mkdir -p src test .ekit
cat > src/greet.js <<'JS'
export function greet(name) {
  if (!name) throw new Error("name is required");
  return `Hello, ${name}!`;
}
JS
cat > test/greet.test.js <<'JS'
import { test } from "node:test";
import assert from "node:assert/strict";
import { greet } from "../src/greet.js";

test("greets by name", () => assert.equal(greet("Ada"), "Hello, Ada!"));
test("a missing name throws", () => assert.throws(() => greet(""), /name is required/));
JS
cat > .ekit/stack-plan.toml <<'TOML'
[[stack]]
name = "js"
folder = "."
adapter = "ts"
status = "current"
TOML
# Grader support: whenever HEAD or a ref moves (commit, reset, checkout, merge, rebase), the end state at HEAD (the
# committed plan read with tomllib, and the kit's own drift check on HEAD) goes to .git/ekit-eval/verdict.txt, which the
# regex graders read; `migrated: yes` needs all three. The trigger is evals/git-shim.sh, which evals/run.sh puts first
# on PATH as `git` (the eval sandbox turns git hooks off). Git and the kit's engine, copied into .git/ekit-eval/engine
# (evals/verdict-kit.sh: the sandbox may deny the kit itself); nothing printed. `kit` names that copy, relative to
# .git/ekit-eval/ (an absolute path is read as one). A crash keeps this run's lines and adds its own.
mkdir -p .git/ekit-eval
source "$(dirname "$0")/../verdict-kit.sh"
copy_engine .git/ekit-eval/engine
printf 'engine' > .git/ekit-eval/kit
cat > .git/ekit-eval/verdict.py <<'PY'
import json, os, subprocess, sys
here = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True,
                      text=True).stdout.strip()  # the main checkout's .git, from it or from any linked worktree
repo = os.path.dirname(here)  # the main checkout: its HEAD is the end state, whichever worktree moved a ref
# a caller's GIT_DIR (and index), a linked worktree's: dropped, so git reads the main checkout
env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                                                        "GIT_OBJECT_DIRECTORY", "GIT_PREFIX")}
def git(*a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, env=env)
VERDICT = os.path.join(here, "ekit-eval", "verdict.txt")
lines = []
try:  # no verdict of an earlier ref move outlives this one
    os.remove(VERDICT)
except OSError:
    pass
def crashed(kind, value, tb):
    """any exception: this run's lines so far, then the crash; `migrated: no`"""
    with open(VERDICT, "w") as f:
        f.write("\n".join(lines + [f"verdict: crashed ({kind.__name__}: {str(value)[:300]})", "migrated: no"]) + "\n")
sys.excepthook = crashed
with open(os.path.join(here, "ekit-eval", "kit"), encoding="utf-8") as f:
    kit = os.path.join(here, "ekit-eval", f.read())  # the engine's copy (relative); an absolute path stays itself
try:
    import tomllib
    stacks = tomllib.loads(git("show", "HEAD:.ekit/stack-plan.toml").stdout).get("stack", [])
    stacks = [s for s in stacks if isinstance(s, dict)] if isinstance(stacks, list) else []
except Exception as e:  # no plan at HEAD, not TOML, no tomllib: neither entry is there
    stacks = []
    lines.append(f"plan: does not read ({type(e).__name__})")
js = [s for s in stacks if s.get("name") == "js"]
ts = [s for s in stacks if s.get("name") != "js" and s.get("adapter") == "ts" and s.get("status") in ("current", "planned")]
retiring = len(js) == 1 and js[0].get("status") == "retiring"
lines.append(f"ts-entry: {'yes' if ts else 'no'}")
lines.append(f"js-retiring: {'yes' if retiring else 'no'}")
engine = os.path.join(kit, "scripts", "mech-review.py")
clean = False
if not os.path.isfile(engine):
    lines.append(f"drift: not run: harness: the kit's scripts/mech-review.py is not at {kit!r} (not the model's doing)")
else:
    r = subprocess.run([sys.executable, "-I", engine, "drift", "--repo", repo, "--base", "HEAD", "--head", "HEAD",
                        "--format", "json"], capture_output=True, text=True, env=env)
    try:
        result = json.loads(r.stdout)
        d = result["checks"].get("D") or {}
        entries = result["entries"]
    except (ValueError, KeyError, TypeError):  # no result on stdout
        result, d, entries = None, {}, []
    if r.returncode == 2 or result is None:  # a usage error: the reason is the result's entry, else stderr's first line
        reason = entries[0].get("problem") if entries and isinstance(entries[0], dict) else None
        reason = reason or (r.stderr.strip().splitlines() or ["no output"])[0]
        lines.append(f"drift: not clean (exit {r.returncode}: {reason[:300]})")
    else:
        clean = r.returncode == 0 and d.get("status") == "pass" and not entries
        lines.append(f"drift: {'clean' if clean else 'not clean'} (exit {r.returncode}, D {d.get('status')}, "
                     f"{len(entries)} entries, messages {json.dumps(d.get('messages', []))})")
# committed with git on the branch that ends checked out: HEAD is on a branch beyond the scaffold's commit, and git moved
# it there (its tip is the newest entry of its own reflog; a ref written by hand leaves none)
on = git("symbolic-ref", "-q", "HEAD").stdout.strip()
tip = git("rev-parse", "-q", "--verify", "HEAD").stdout.strip()
try:
    with open(os.path.join(here, "ekit-eval", "start"), encoding="utf-8") as f:
        start = f.read().strip()
except OSError:  # the scaffold's own commit, before it records the start
    start = tip
newest = git("reflog", "show", "-n", "1", "--format=%H", on).stdout.strip() if on else ""
lines.append("by-git: " + ("no (HEAD is on no branch)" if not on else "no (no commit beyond the scaffold's)"
                           if tip == start else "yes" if newest == tip else
                           f"no (the tip of {on} is not the newest entry of its reflog: a ref written by hand)"))
lines.append(f"migrated: {'yes' if ts and retiring and clean else 'no'}")  # the one end state: all three at once
with open(VERDICT, "w") as f:
    f.write("\n".join(lines) + "\n")
PY
git add -A; git commit -qm "greet: js package, stack plan"
git rev-parse HEAD > .git/ekit-eval/start
python3 -I .git/ekit-eval/verdict.py  # the start state's verdict
