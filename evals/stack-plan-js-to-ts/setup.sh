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
# regex graders read; `migrated: yes` needs all three. Git only; nothing printed. The kit's path is data in a file, never
# shell text.
mkdir -p .git/ekit-eval
printf '%s' "$(cd "$(dirname "$0")/../.." && pwd -P)" > .git/ekit-eval/kit
cat > .git/ekit-eval/verdict.py <<'PY'
import json, os, subprocess, sys
def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)
here = git("rev-parse", "--absolute-git-dir").stdout.strip()
repo = git("rev-parse", "--show-toplevel").stdout.strip()
with open(os.path.join(here, "ekit-eval", "kit"), encoding="utf-8") as f:
    kit = f.read()
lines = []
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
                        "--format", "json"], capture_output=True, text=True)
    try:
        env = json.loads(r.stdout)
        d = env["checks"].get("D") or {}
        clean = r.returncode == 0 and d.get("status") == "pass" and not env["entries"]
        lines.append(f"drift: {'clean' if clean else 'not clean'} (exit {r.returncode}, D {d.get('status')}, "
                     f"{len(env['entries'])} entries, messages {json.dumps(d.get('messages', []))})")
    except (ValueError, KeyError):
        lines.append(f"drift: not clean (exit {r.returncode}: {r.stderr.strip()[:300]})")
lines.append(f"migrated: {'yes' if ts and retiring and clean else 'no'}")  # the one end state: all three at once
with open(os.path.join(here, "ekit-eval", "verdict.txt"), "w") as f:
    f.write("\n".join(lines) + "\n")
PY
# reference-transaction: every ref update (commit, reset, merge, rebase); post-checkout: a switch of HEAD alone
printf '#!/bin/sh\n[ "$1" = committed ] || exit 0\nexec python3 -I "$(git rev-parse --absolute-git-dir)/ekit-eval/verdict.py" >/dev/null 2>&1\n' > .git/hooks/reference-transaction
printf '#!/bin/sh\nexec python3 -I "$(git rev-parse --absolute-git-dir)/ekit-eval/verdict.py" >/dev/null 2>&1\n' > .git/hooks/post-checkout
chmod +x .git/hooks/reference-transaction .git/hooks/post-checkout
git add -A; git commit -qm "greet: js package, stack plan"
