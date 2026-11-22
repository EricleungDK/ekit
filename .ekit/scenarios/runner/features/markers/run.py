"""runner/features/markers: misuse, feature lines in the wrong form and marker-like text."""
import os
import subprocess
import sys
from pathlib import Path

CWD = Path.cwd()
KIT = CWD / "kit"
APP = CWD / "app"
FAILS = []
FENCE = "`" * 3


def env():
    return {k: v for k, v in os.environ.items() if not k.startswith("EKIT_")}


def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env(), timeout=300)


def git(*args):
    p = sh(["git", *args], APP)
    if p.returncode:
        sys.exit(f"setup: git {' '.join(args)} failed: {p.stderr}")


def runner(*args):
    p = sh([sys.executable, str(KIT / "scripts" / "scenarios.py"), *args], APP)
    print(f"$ scenarios.py {' '.join(args)}  -> exit {p.returncode}")
    print(p.stdout, end="")
    print(p.stderr, end="")
    if "Traceback" in p.stdout + p.stderr:
        FAILS.append(f"`{' '.join(args)}` printed a traceback")
    return p


def expect(cond, msg):
    if not cond:
        FAILS.append(msg)


def lines(p):
    return [l for l in p.stdout.splitlines() if l.strip()]


def scenario(sid, marker_block, body="sys.exit(0)"):
    d = APP / ".ekit" / "scenarios" / sid
    d.mkdir(parents=True, exist_ok=True)
    md = f"# {sid}\n\n- story: s\n- covers: c\n- steps: s\n- expected: e\n{marker_block}\n"
    (d / "SCENARIO.md").write_text(md)
    (d / "run.py").write_text("import os, sys\n" + body + "\n")


p = subprocess.run(["git", "clone", "-q", os.environ["EKIT_REPO"], str(KIT)], capture_output=True, text=True)
if p.returncode:
    sys.exit(f"setup: clone failed: {p.stderr}")
APP.mkdir()
git("init", "-q")
git("config", "user.email", "dev@example.com")
git("config", "user.name", "dev")
(APP / "app.py").write_text("print('app')\n")

scenario("real", "- feature: export")
scenario("two", "- feature: alpha\n- feature: beta")
scenario("caps", "- Feature: x")
scenario("bold", "- **feature**: x")
scenario("open-fence", f"{FENCE}\n- feature: z")
scenario("fenced", f"{FENCE}\n- feature: fake\n{FENCE}")
scenario("comment", "<!--\n- feature: hidden\n-->")
scenario("gherkin", "Feature: login")
scenario("nested", "- notes:\n  - feature: deep")
git("add", "-A")
git("commit", "-qm", "scenarios")

r = runner("run")
out = lines(r)
fail = {l.split(":", 1)[0][5:]: l for l in out if l.startswith("FAIL ") and ":" in l}
expect(r.returncode == 1, f"run: exit {r.returncode}, want 1")
expect("two" in fail and "alpha" in fail["two"] and "beta" in fail["two"], f"`two` not a FAIL naming alpha and beta: {fail.get('two')}")
expect("caps" in fail and "- Feature: x" in fail["caps"], f"`caps` not a FAIL quoting its line: {fail.get('caps')}")
expect("bold" in fail and "- **feature**: x" in fail["bold"], f"`bold` not a FAIL quoting its line: {fail.get('bold')}")
expect("open-fence" in fail and "fence" in fail["open-fence"], f"`open-fence` not a FAIL naming the fence: {fail.get('open-fence')}")
for sid in ("real", "fenced", "comment", "gherkin", "nested"):
    expect(f"PASS {sid}" in out, f"run: no `PASS {sid}` line (marker-like text must read as unmarked)")
expect(out[-1:] == ["1 of 1 features working"], f"run: last line {out[-1:]}, want `1 of 1 features working`")
c = runner("check")
expect(c.returncode == 1 and lines(c)[-1:] == ["1 of 1 features working"],
       f"check: exit {c.returncode} {lines(c)}, want exit 1 ending `1 of 1 features working`")

# a seeded scenario that writes into the repo: nothing counts as working in that run
scenario("writer", "- feature: notes",
         "open(os.path.join(os.environ['EKIT_REPO'], 'notes.txt'), 'w').write('x')\nsys.exit(0)")
r = runner("run")
out = lines(r)
expect(r.returncode == 1, f"run with writer: exit {r.returncode}, want 1")
expect("modified the repo" in r.stdout + r.stderr, "run with writer: no `modified the repo`")
expect(out[-1:] == ["0 of 2 features working"], f"run with writer: last line {out[-1:]}, want `0 of 2 features working`")

if FAILS:
    print("\nFAILED CHECKS:", file=sys.stderr)
    for f in FAILS:
        print(" - " + f, file=sys.stderr)
    sys.exit(1)
print("all checks passed")
