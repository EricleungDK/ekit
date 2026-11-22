"""runner/features: the `N of M features working` line, as a user with seeded scenarios sees it."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

CWD = Path.cwd()
KIT = CWD / "kit"
APP = CWD / "app"
FAILS = []


def env():
    # the user's shell: none of the outer runner's EKIT_* variables
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


def scenario(sid, feature, body, extra=""):
    d = APP / ".ekit" / "scenarios" / sid
    d.mkdir(parents=True, exist_ok=True)
    md = f"# {sid}\n\n- story: s\n- covers: c\n- steps: s\n- expected: e\n"
    if feature is not None:
        md += f"- feature: {feature}\n"
    (d / "SCENARIO.md").write_text(md + extra)
    (d / "run.py").write_text("import os, subprocess, sys\n" + body + "\n")


def greet(args, want):
    return (
        f"out = subprocess.run([sys.executable, os.path.join(os.environ['EKIT_REPO'], 'greet.py'), {args}],"
        " capture_output=True, text=True).stdout.strip()\n"
        f"print('got', repr(out), file=sys.stderr)\n"
        f"sys.exit(0 if out == {want!r} else 1)"
    )


# 1. the kit as a user gets it, and a user repo with an app and two old (unmarked) scenarios
p = subprocess.run(["git", "clone", "-q", os.environ["EKIT_REPO"], str(KIT)], capture_output=True, text=True)
if p.returncode:
    sys.exit(f"setup: clone failed: {p.stderr}")
kit_head = sh(["git", "status", "--porcelain"], KIT).stdout
APP.mkdir()
git("init", "-q")
git("config", "user.email", "dev@example.com")
git("config", "user.name", "dev")
(APP / "greet.py").write_text(
    "import sys\nargs = sys.argv[1:]\nprint('hello ' + (args[0] if args else 'world'))\n"
)
scenario("ok", None, "sys.exit(0)")
scenario("bad", None, "sys.exit(1)")
git("add", "-A")
git("commit", "-qm", "app and old scenarios")

# 2. nothing marked: reads exactly as before, no features line
r = runner("run")
expect(r.returncode == 1, f"unmarked run: exit {r.returncode}, want 1")
expect(lines(r) == ["FAIL bad: exit 1", "PASS ok", "FAIL: 1/2 scenarios"],
       f"unmarked run printed {lines(r)}, want exactly FAIL bad / PASS ok / FAIL: 1/2 scenarios")
c = runner("check")
expect(c.returncode == 1 and lines(c) == ["last run FAIL"], f"unmarked check: exit {c.returncode} {lines(c)}, want exit 1 ['last run FAIL']")
shutil.rmtree(APP / ".ekit" / "scenarios" / "bad")
r = runner("run")
expect(r.returncode == 0 and lines(r) == ["PASS ok", "PASS: 1/1 scenarios"],
       f"unmarked green run: exit {r.returncode} {lines(r)}, want exit 0 exactly PASS ok / PASS: 1/1 scenarios")
c = runner("check")
expect(c.returncode == 0 and lines(c) == [], f"unmarked green check: exit {c.returncode} {lines(c)}, want exit 0 and no output")

# 3. seeded scenarios: greeting works, shouting does not yet; a child shares the feature (other case and spacing)
scenario("greets", "greeting", greet("'bob'", "hello bob"))
scenario("shouts", "shouting", greet("'--shout', 'bob'", "HELLO BOB"))
scenario("shouts/plain", "  Shouting ", greet("'bob'", "hello bob"))
git("add", "-A")
git("commit", "-qm", "seed greeting and shouting")

# 4. full run and check count 1 of 2; a filtered run and a partial check print no count
r = runner("run")
out = lines(r)
expect(r.returncode == 1, f"seeded run: exit {r.returncode}, want 1")
expect(any(l.startswith("FAIL shouts:") for l in out), "seeded run: no `FAIL shouts:` line")
for sid in ("greets", "ok", "shouts/plain"):
    expect(f"PASS {sid}" in out, f"seeded run: no `PASS {sid}` line")
expect(out[-1:] == ["1 of 2 features working"], f"seeded run: last line {out[-1:]}, want `1 of 2 features working`")
expect(sum("features working" in l for l in out) == 1, "seeded run: the features line is not printed once")
c = runner("check")
expect(c.returncode == 1 and lines(c) == ["last run FAIL", "1 of 2 features working"],
       f"seeded check: exit {c.returncode} {lines(c)}, want exit 1 ['last run FAIL', '1 of 2 features working']")
r = runner("run", "greets")
expect(r.returncode == 0 and "PASS greets" in lines(r), f"filtered run: exit {r.returncode}, want 0 with PASS greets")
expect(not any("features working" in l for l in lines(r)), "filtered `run greets` printed a features line")
c = runner("check")
expect(c.returncode == 1 and "partial" in c.stdout + c.stderr, f"check after filtered run: exit {c.returncode}, want 1 `partial`")
expect("features working" not in c.stdout + c.stderr, "check after a filtered run printed a features line")

# 5. the user builds --shout: every feature works
(APP / "greet.py").write_text(
    "import sys\nargs = sys.argv[1:]\nshout = '--shout' in args\nargs = [a for a in args if a != '--shout']\n"
    "msg = 'hello ' + (args[0] if args else 'world')\nprint(msg.upper() if shout else msg)\n"
)
r = runner("run")
expect(r.returncode == 0, f"run after --shout: exit {r.returncode}, want 0")
expect(lines(r)[-1:] == ["2 of 2 features working"], f"run after --shout: last line {lines(r)[-1:]}, want `2 of 2 features working`")
c = runner("check")
expect(c.returncode == 0 and lines(c) == ["2 of 2 features working"],
       f"check after --shout: exit {c.returncode} {lines(c)}, want exit 0 ['2 of 2 features working']")

# 6. an edit makes the run stale: no count
with open(APP / "greet.py", "a") as f:
    f.write("# tidy later\n")
c = runner("check")
expect(c.returncode == 1 and "stale" in c.stdout + c.stderr, f"check after edit: exit {c.returncode}, want 1 `stale`")
expect("features working" not in c.stdout + c.stderr, "stale check printed a features line")

expect(sh(["git", "status", "--porcelain"], KIT).stdout == kit_head, "the kit clone was modified")

if FAILS:
    print("\nFAILED CHECKS:", file=sys.stderr)
    for f in FAILS:
        print(" - " + f, file=sys.stderr)
    sys.exit(1)
print("all checks passed")
