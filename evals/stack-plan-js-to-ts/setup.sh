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
# Grader support: after each commit, the end state at HEAD (the committed plan read with tomllib, and the kit's own drift
# check on HEAD) goes to .git/ekit-eval-verdict.txt, which the regex graders read. Git only; nothing printed.
KIT="$(cd "$(dirname "$0")/../.." && pwd -P)"
cat > .git/ekit-eval-verdict.py <<'PY'
import json, os, subprocess, sys
kit, repo = sys.argv[1], os.getcwd()
def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)
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
lines.append(f"ts-entry: {'yes' if ts else 'no'}")
lines.append(f"js-retiring: {'yes' if len(js) == 1 and js[0].get('status') == 'retiring' else 'no'}")
r = subprocess.run([sys.executable, "-I", os.path.join(kit, "scripts", "mech-review.py"), "drift", "--repo", repo,
                    "--base", "HEAD", "--head", "HEAD", "--format", "json"], capture_output=True, text=True)
try:
    env = json.loads(r.stdout)
    d = env["checks"].get("D") or {}
    clean = r.returncode == 0 and d.get("status") == "pass" and not env["entries"]
    lines.append(f"drift: {'clean' if clean else 'not clean'} (exit {r.returncode}, D {d.get('status')}, "
                 f"{len(env['entries'])} entries, messages {json.dumps(d.get('messages', []))})")
except (ValueError, KeyError):
    lines.append(f"drift: not clean (exit {r.returncode}: {r.stderr.strip()[:300]})")
with open(os.path.join(git("rev-parse", "--git-dir").stdout.strip(), "ekit-eval-verdict.txt"), "w") as f:
    f.write("\n".join(lines) + "\n")
PY
printf '#!/bin/sh\npython3 -I "$(git rev-parse --git-dir)/ekit-eval-verdict.py" %s >/dev/null 2>&1 || true\n' "'$KIT'" > .git/hooks/post-commit
chmod +x .git/hooks/post-commit
git add -A; git commit -qm "greet: js package, stack plan"
