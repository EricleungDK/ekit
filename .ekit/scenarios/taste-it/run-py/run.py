"""taste-it/run-py: the shipped skill makes run.py the default; run.sh scenarios still run."""
import ast
import os
import re
import shutil
import subprocess
import sys

HERE = os.getcwd()
KIT = os.path.join(HERE, "kit")
SAMPLE = os.path.join(HERE, "sample")
ENV = dict(os.environ, EKIT_STATE=os.path.join(HERE, "state"), GIT_CONFIG_GLOBAL=os.devnull,
           GIT_CONFIG_SYSTEM=os.devnull, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def fail(msg):
    sys.exit(f"ASSERT FAILED: {msg}")


def sh(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, env=ENV)


sh(["git", "clone", "-q", os.environ["EKIT_REPO"], KIT])
skill = open(os.path.join(KIT, "skills", "taste-it", "SKILL.md"), encoding="utf-8").read()
drivers = open(os.path.join(KIT, "skills", "taste-it", "drivers.md"), encoding="utf-8").read()

# the layout block: the first fenced block that shows .ekit/scenarios/<use-case>/
blocks = re.findall(r"```[^\n]*\n(.*?)```", skill, re.S)
layout = next((b for b in blocks if ".ekit/scenarios/<use-case>/" in b), None)
if layout is None:
    fail("SKILL.md has no layout block")
print("layout block:\n" + layout)
if not re.search(r"/run\.py\b", layout):
    fail("the layout block does not name run.py as the run file")
if re.search(r"/run\.sh\b", layout):
    fail("the layout block still names run.sh as the run file")

flat = " ".join(skill.split())
if "Write the run file as `run.py`" not in flat:
    fail("SKILL.md does not tell the agent to write run.py")
m = re.search(r"Write `run\.sh`[^.]*`run\.ps1`[^.]*only when the user asks", flat)
if not m:
    fail("SKILL.md does not keep run.sh / run.ps1 for when the user asks")
print("rule: " + m.group(0))

dflat = " ".join(drivers.split())
if "`run.py` (the default run file)" not in dflat:
    fail("drivers.md does not call run.py the default run file")
py_blocks = re.findall(r"```python\n(.*?)```", drivers, re.S)
if not py_blocks:
    fail("drivers.md has no python example")
for b in py_blocks:
    try:
        ast.parse(b.replace("<cmd>", "mycli"))
    except SyntaxError as e:
        fail(f"drivers.md python example does not parse: {e}\n{b}")

# old run.sh scenarios in a user repo keep their verdicts
if shutil.which("bash") is None:
    sys.exit("CANNOT CHECK: no bash on this host for the run.sh part")
sh(["git", "init", "-q", SAMPLE])
for sid, rc in (("old-ok", 0), ("old-bad", 1)):
    d = os.path.join(SAMPLE, ".ekit", "scenarios", sid)
    os.makedirs(d)
    with open(os.path.join(d, "SCENARIO.md"), "w") as f:
        f.write(f"# {sid}\n\n- story: s\n- covers: c\n- steps: s\n- expected: e\n")
    with open(os.path.join(d, "run.sh"), "w") as f:
        f.write(f"#!/usr/bin/env bash\nset -euo pipefail\n[[ -d \"$EKIT_REPO\" ]]\nexit {rc}\n")
sh(["git", "-C", SAMPLE, "add", "-A"])
sh(["git", "-C", SAMPLE, "commit", "-qm", "old scenarios"])
r = subprocess.run([sys.executable, os.path.join(KIT, "scripts", "scenarios.py"), "--repo", SAMPLE, "run"],
                   capture_output=True, text=True, env=ENV, timeout=120)
out = r.stdout + r.stderr
print("--- run\n" + out)
if r.returncode != 1 or "PASS old-ok" not in out or not re.search(r"^FAIL old-bad: exit 1$", out, re.M):
    fail(f"old run.sh scenarios: exit {r.returncode}, want 1 with PASS old-ok and FAIL old-bad: exit 1")
print("OK")
