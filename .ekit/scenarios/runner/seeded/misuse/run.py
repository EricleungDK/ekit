"""runner/seeded/misuse: `seeded` on scenarios it cannot judge."""
import os
import subprocess
import sys
from pathlib import Path

CWD = Path.cwd()
KIT = CWD / "kit"
APP = CWD / "app"
FAILS = []


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
    both = p.stdout + p.stderr
    if "Traceback" in both:
        FAILS.append(f"`{' '.join(args)}` printed a traceback")
    if "SEEDED ✓" in both or "CHECKS NOTHING YET" in both:
        FAILS.append(f"`{' '.join(args)}` gave a seeded verdict: {both.strip()!r}")
    return p


def expect(cond, msg):
    if not cond:
        FAILS.append(msg)


def scenario(sid, marker, body="sys.exit(1)"):
    d = APP / ".ekit" / "scenarios" / sid
    d.mkdir(parents=True, exist_ok=True)
    md = f"# {sid}\n\n- story: s\n- covers: c\n- steps: s\n- expected: e\n{marker}\n"
    (d / "SCENARIO.md").write_text(md)
    (d / "run.py").write_text("import os, sys\n" + body + "\n")
    return d


p = subprocess.run(["git", "clone", "-q", os.environ["EKIT_REPO"], str(KIT)], capture_output=True, text=True)
if p.returncode:
    sys.exit(f"setup: clone failed: {p.stderr}")
APP.mkdir()
git("init", "-q")
git("config", "user.email", "dev@example.com")
git("config", "user.name", "dev")
(APP / "app.py").write_text("print('app')\n")
scenario("plain", "")
scenario("blank", "- feature:")
scenario("caps", "- Feature: export")
d = scenario("both", "- feature: both")
(d / "run.sh").write_text("exit 1\n")
scenario("scribble", "- feature: notes",
         "open(os.path.join(os.environ['EKIT_REPO'], 'notes.txt'), 'w').write('x')\nsys.exit(1)")
git("add", "-A")
git("commit", "-qm", "scenarios")

cases = {
    "plain": ["- feature:"],
    "blank": ["empty"],
    "caps": ["- Feature: export"],
    "both": ["run.py", "run.sh"],
    "scribble": ["notes.txt"],
}
for sid, needles in cases.items():
    s = runner("seeded", sid)
    err = [l for l in (s.stdout + s.stderr).splitlines() if l.startswith(f"ERROR {sid}:")]
    expect(s.returncode == 2, f"seeded {sid}: exit {s.returncode}, want 2")
    expect(len(err) == 1, f"seeded {sid}: no `ERROR {sid}:` line")
    for n in needles:
        expect(bool(err) and n in err[0], f"seeded {sid}: the ERROR line does not name {n!r}")
    (APP / "notes.txt").unlink(missing_ok=True)

s = runner("seeded", "nope")
expect(s.returncode == 2 and "nope" in s.stdout + s.stderr, f"seeded nope: exit {s.returncode}, want 2 naming `nope`")
s = runner("seeded")
expect(s.returncode == 2 and "usage" in (s.stdout + s.stderr).lower(), f"seeded with no id: exit {s.returncode}, want 2 with usage")
expect(not (APP / ".git" / "ekit" / "results.json").exists(), "seeded wrote results.json")

if FAILS:
    print("\nFAILED CHECKS:", file=sys.stderr)
    for f in FAILS:
        print(" - " + f, file=sys.stderr)
    sys.exit(1)
print("all checks passed")
