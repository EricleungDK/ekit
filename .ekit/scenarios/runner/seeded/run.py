"""runner/seeded: `scenarios.py seeded <id>` on scenarios a user has just seeded."""
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
    if "Traceback" in p.stdout + p.stderr:
        FAILS.append(f"`{' '.join(args)}` printed a traceback")
    return p


def expect(cond, msg):
    if not cond:
        FAILS.append(msg)


def scenario(sid, feature, body):
    d = APP / ".ekit" / "scenarios" / sid
    d.mkdir(parents=True, exist_ok=True)
    md = f"# {sid}\n\n- story: s\n- covers: c\n- steps: s\n- expected: e\n"
    if feature is not None:
        md += f"- feature: {feature}\n"
    (d / "SCENARIO.md").write_text(md)
    (d / "run.py").write_text("import os, subprocess, sys\n" + body + "\n")


def greet(args, want):
    return (
        f"out = subprocess.run([sys.executable, os.path.join(os.environ['EKIT_REPO'], 'greet.py'), {args}],"
        " capture_output=True, text=True).stdout.strip()\n"
        f"if out != {want!r}:\n"
        f"    print('checking greet.py', {args})\n"
        f"    print('wanted', repr({want!r}) + ', got', repr(out), file=sys.stderr)\n"
        "    sys.exit(1)"
    )


def seeded_line(p, sid):
    for l in p.stdout.splitlines() + p.stderr.splitlines():
        if l.startswith(f"SEEDED ✓ {sid}:"):
            return l
    return None


def transcript_after(p, sid):
    out = (p.stdout + p.stderr).splitlines()
    for i, l in enumerate(out):
        if l.startswith(f"SEEDED ✓ {sid}:") and i + 1 < len(out) and out[i + 1].strip().startswith("transcript:"):
            return Path(out[i + 1].split("transcript:", 1)[1].strip())
    return None


p = subprocess.run(["git", "clone", "-q", os.environ["EKIT_REPO"], str(KIT)], capture_output=True, text=True)
if p.returncode:
    sys.exit(f"setup: clone failed: {p.stderr}")
APP.mkdir()
git("init", "-q")
git("config", "user.email", "dev@example.com")
git("config", "user.name", "dev")
(APP / "greet.py").write_text("import sys\nargs = sys.argv[1:]\nprint('hello ' + (args[0] if args else 'world'))\n")
scenario("ok", None, "sys.exit(0)")
git("add", "-A")
git("commit", "-qm", "app")

# 1. a full green run: the results seeded must leave alone
r = runner("run")
if r.returncode != 0:
    sys.exit("setup: the first full run is not green")
results = APP / ".git" / "ekit" / "results.json"
before = results.read_bytes() if results.exists() else None
expect(before is not None, "no results.json after the full run")

# 2. seed, without committing
scenario("greets", "greeting", greet("'bob'", "hello bob"))
scenario("shouts", "shouting", greet("'--shout', 'bob'", "HELLO BOB"))
scenario("shouts/quiet", "shouting", "print('quiet mode missing')\nsys.exit(3)")

# 3. seeded on each
want_quiet = "SEEDED ✓ shouts/quiet: fails on the repo as it is: exit 3: quiet mode missing"
want_shout = "SEEDED ✓ shouts: fails on the repo as it is: exit 1: wanted 'HELLO BOB', got 'hello --shout'"

s = runner("seeded", "shouts/quiet")
expect(s.returncode == 0, f"seeded shouts/quiet: exit {s.returncode}, want 0")
expect(seeded_line(s, "shouts/quiet") == want_quiet, f"seeded shouts/quiet: {seeded_line(s, 'shouts/quiet')!r}, want {want_quiet!r} (stdout's last line when stderr is empty)")
expect(f"SEEDED ✓ shouts:" not in s.stdout + s.stderr, "seeded shouts/quiet also ran its parent")

s = runner("seeded", "shouts")
expect(s.returncode == 0, f"seeded shouts: exit {s.returncode}, want 0")
expect(seeded_line(s, "shouts") == want_shout, f"seeded shouts: {seeded_line(s, 'shouts')!r}, want {want_shout!r} (stderr's last line)")
expect(seeded_line(s, "shouts/quiet") == want_quiet, "seeded shouts did not take its child shouts/quiet")
for sid, needle in (("shouts", "wanted 'HELLO BOB'"), ("shouts/quiet", "quiet mode missing")):
    t = transcript_after(s, sid)
    expect(t is not None and t.is_file() and needle in t.read_text(errors="replace"),
           f"seeded shouts: transcript for {sid} ({t}) missing or without {needle!r}")
expect(results.read_bytes() == before, "seeded shouts changed results.json")

s = runner("seeded", "greets")
expect(s.returncode == 1, f"seeded greets: exit {s.returncode}, want 1")
expect(any(l.startswith("CHECKS NOTHING YET greets") for l in (s.stdout + s.stderr).splitlines()),
       "seeded greets: no `CHECKS NOTHING YET greets` line for a scenario that already passes")
expect("SEEDED ✓" not in s.stdout + s.stderr, "seeded greets printed SEEDED ✓ for a passing scenario")
expect(results.read_bytes() == before, "seeded greets changed results.json")

c = runner("check")
expect(c.returncode == 1 and "stale" in c.stdout + c.stderr, f"check after seeded: exit {c.returncode}, want 1 `stale` (no seeded result taken as a run)")

# 4. the user builds --shout (quiet mode still missing)
(APP / "greet.py").write_text(
    "import sys\nargs = sys.argv[1:]\nshout = '--shout' in args\nargs = [a for a in args if a != '--shout']\n"
    "msg = 'hello ' + (args[0] if args else 'world')\nprint(msg.upper() if shout else msg)\n"
)
s = runner("seeded", "shouts")
expect(s.returncode == 1, f"seeded shouts after --shout: exit {s.returncode}, want 1")
expect(any(l.startswith("CHECKS NOTHING YET shouts") and "shouts/" not in l for l in (s.stdout + s.stderr).splitlines()),
       "seeded shouts after --shout: no `CHECKS NOTHING YET shouts`")
expect(seeded_line(s, "shouts/quiet") == want_quiet, "seeded shouts after --shout: shouts/quiet no longer SEEDED ✓")

if FAILS:
    print("\nFAILED CHECKS:", file=sys.stderr)
    for f in FAILS:
        print(" - " + f, file=sys.stderr)
    sys.exit(1)
print("all checks passed")
