"""runner/every-format: transcripts, artifacts, bytecode, repo writes and can-fail read the same for run.py and run.sh."""
import json
import os
import re
import shutil
import subprocess
import sys

if os.name == "nt":
    sys.exit("CANNOT CHECK: needs bash and a PATH without it; run this on Linux, macOS or WSL.")

HERE = os.getcwd()
KIT = os.path.join(HERE, "kit")
SAMPLE = os.path.join(HERE, "sample")
STATE = os.path.join(HERE, "state")
BIN = os.path.join(HERE, "bin")  # only Python and git
os.makedirs(BIN)
for name, exe in (("python3", sys.executable), ("git", shutil.which("git"))):
    os.symlink(os.path.realpath(exe), os.path.join(BIN, name))
ENV = dict(os.environ, EKIT_STATE=STATE, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
           GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
NO_BASH = dict(ENV, PATH=BIN)


def fail(msg):
    sys.exit(f"ASSERT FAILED: {msg}")


def sh(args, env=ENV):
    return subprocess.run(args, check=True, capture_output=True, text=True, env=env)


def git(*args):
    return sh(["git", "-C", SAMPLE, *args]).stdout


sh(["git", "clone", "-q", os.environ["EKIT_REPO"], KIT])
RUNNER = os.path.join(KIT, "scripts", "scenarios.py")


def run(args, env=ENV):
    r = subprocess.run([sys.executable, RUNNER, "--repo", SAMPLE, *args], capture_output=True, text=True,
                       env=env, timeout=300)
    out = r.stdout + r.stderr
    print(f"--- {' '.join(args)} (exit {r.returncode})\n{out}")
    if "Traceback" in out:
        fail(f"traceback from `{' '.join(args)}`")
    return r.returncode, out


def verdicts(out):
    """{id: word} from the runner's PASS/FAIL/NOT-RUN lines."""
    return {m[2]: m[1] for m in re.finditer(r"^(PASS|FAIL|NOT-RUN) ([\w./-]+)", out, re.M)}


PY = {
    "shot": "import os\nopen(os.path.join(os.environ['EKIT_ARTIFACT_DIR'], 'shot-py.png'), 'w').write('png')\n"
            "print('MARK-shot-py')\nraise SystemExit({rc})\n",
    "pyc": "import os, subprocess, sys\nenv = dict(os.environ)\nenv.pop('PYTHONDONTWRITEBYTECODE', None)\n"
           "subprocess.run([sys.executable, '-c', 'import lib'], cwd=os.environ['EKIT_REPO'], env=env, check=True)\n"
           "assert os.path.isdir(os.path.join(os.environ['EKIT_REPO'], '__pycache__')), 'no bytecode written'\n",
    "feat": "import os, sys\nsys.exit(0 if os.path.exists(os.path.join(os.environ['EKIT_REPO'], 'feature.txt')) else 1)\n",
    "always": "print('fine')\n",
    "dirty": "import os\nopen(os.path.join(os.environ['EKIT_REPO'], 'notes.txt'), 'w').write('x')\n",
}
SH = {
    "shot": "echo png > \"$EKIT_ARTIFACT_DIR/shot-sh.png\"\necho MARK-shot-sh\nexit {rc}\n",
    "pyc": "cd \"$EKIT_REPO\" && env -u PYTHONDONTWRITEBYTECODE python3 -c 'import lib' && test -d __pycache__\n",
    "feat": "test -f \"$EKIT_REPO/feature.txt\"\n",
    "always": "echo fine\n",
    "dirty": "echo x > \"$EKIT_REPO/notes.txt\"\n",
}
EXTRA_PY = {
    "raise-py": "raise RuntimeError('boom')\n",
    "syntax-py": "def broken(:\n",
    "assert-py": "assert 1 == 2, 'one is not two'\n",
}


def scenario(sid, file, body):
    d = os.path.join(SAMPLE, ".ekit", "scenarios", sid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SCENARIO.md"), "w") as f:
        f.write(f"# {sid}\n\n- story: s\n- covers: c\n- steps: s\n- expected: e\n")
    with open(os.path.join(d, file), "w") as f:
        f.write(body)


# 1. sample repo: base has lib.py, head adds feature.txt
sh(["git", "init", "-q", SAMPLE])
with open(os.path.join(SAMPLE, "lib.py"), "w") as f:
    f.write("X = 1\n")
git("add", "-A")
git("commit", "-qm", "base")
with open(os.path.join(SAMPLE, "feature.txt"), "w") as f:
    f.write("feature\n")
for name in ("shot", "pyc", "feat", "always"):
    scenario(f"{name}-py", "run.py", PY[name].format(rc=1))
    scenario(f"{name}-sh", "run.sh", SH[name].format(rc=1))
for sid, body in EXTRA_PY.items():
    scenario(sid, "run.py", body)
git("add", "-A")
git("commit", "-qm", "feature and scenarios")

# 2. first run, with the caller's PYTHONOPTIMIZE set
rc, out = run(["run"], dict(ENV, PYTHONOPTIMIZE="1"))
v = verdicts(out)
want = {"shot-py": "FAIL", "shot-sh": "FAIL", "raise-py": "FAIL", "syntax-py": "FAIL", "assert-py": "FAIL",
        "pyc-py": "PASS", "pyc-sh": "PASS", "feat-py": "PASS", "feat-sh": "PASS", "always-py": "PASS",
        "always-sh": "PASS"}
if rc != 1 or any(v.get(k) != w for k, w in want.items()):
    fail(f"first run: exit {rc}, verdicts {v}, want exit 1 and {want}")
if "modified the repo" in out:
    fail("bytecode left in the repo read as a repo change")
if not os.path.isdir(os.path.join(SAMPLE, "__pycache__")):
    fail("the pyc scenarios left no __pycache__: the bytecode case did not happen")

found = [os.path.join(d, "results.json") for base in (STATE, os.path.join(SAMPLE, ".git"))
         for d, _, files in os.walk(base) if "results.json" in files]
if not found:
    fail("no results.json written")
res = json.load(open(found[0]))
by_id = {s["id"]: s for s in res["scenarios"]}
for fmt in ("py", "sh"):
    s = by_id[f"shot-{fmt}"]
    arts = s.get("artifacts") or []
    hit = [a for a in arts if os.path.basename(a) == f"shot-{fmt}.png" and os.path.isfile(a)]
    if not hit:
        fail(f"shot-{fmt}: artifacts {arts} do not list an existing shot-{fmt}.png")
    ft = s.get("failed_transcript")
    if not ft or not os.path.isfile(ft) or f"MARK-shot-{fmt}" not in open(ft).read():
        fail(f"shot-{fmt}: failed transcript {ft} missing or without its output")
FAILED = {fmt: by_id[f"shot-{fmt}"]["failed_transcript"] for fmt in ("py", "sh")}

# 3. shot-* now pass: the last failed transcript stays
scenario("shot-py", "run.py", PY["shot"].format(rc=0))
scenario("shot-sh", "run.sh", SH["shot"].format(rc=0))
git("add", "-A")
git("commit", "-qm", "shots pass")
rc, out = run(["run"])
v = verdicts(out)
if v.get("shot-py") != "PASS" or v.get("shot-sh") != "PASS":
    fail(f"after the fix: verdicts {v}, want shot-py and shot-sh PASS")
for fmt, path in FAILED.items():
    if not os.path.isfile(path) or f"MARK-shot-{fmt}" not in open(path).read():
        fail(f"shot-{fmt}: the failed transcript {path} was not kept after a pass")
with_bash = v

# 4. no bash on PATH: run.py verdicts unchanged, run.sh not run
rc, out = run(["run"], NO_BASH)
v = verdicts(out)
for sid, w in with_bash.items():
    got = v.get(sid)
    if sid.endswith("-py") and got != w:
        fail(f"no bash: {sid} read {got}, with bash it read {w}")
    if sid.endswith("-sh") and got != "NOT-RUN":
        fail(f"no bash: {sid} read {got}, want NOT-RUN")
if not re.search(r"^NOT-RUN always-sh: .*\(env\)", out, re.M):
    fail("no bash: no `NOT-RUN always-sh: ... (env)` line")

# 5. can-fail reads the same for both formats
rc, out = run(["can-fail", "HEAD~2"])
lines = {}
for ln in out.splitlines():
    m = re.match(r"^(CAN-FAIL ✓|CANNOT FAIL|N/A|ERROR) ([\w./-]+)(.*)$", ln)
    if m:
        lines[m[2]] = (m[1], m[3])
for name, word in (("feat", "CAN-FAIL ✓"), ("always", "CANNOT FAIL")):
    py, shl = lines.get(f"{name}-py"), lines.get(f"{name}-sh")
    if not py or not shl or py[0] != word or shl[0] != word:
        fail(f"can-fail: {name}-py {py}, {name}-sh {shl}, want both {word}")
    if py[1] != shl[1]:
        fail(f"can-fail: {name}-py and {name}-sh read differently: {py[1]!r} vs {shl[1]!r}")
if rc != 1:
    fail(f"can-fail with CANNOT FAIL lines: exit {rc}, want 1")

# 6. a real write into the repo is still a repo change, for either format
for fmt, file, body in (("py", "run.py", PY["dirty"]), ("sh", "run.sh", SH["dirty"])):
    scenario(f"dirty-{fmt}", file, body)
git("add", "-A")
git("commit", "-qm", "dirty")
for fmt in ("py", "sh"):
    rc, out = run(["run", f"dirty-{fmt}"])
    if rc != 1 or "modified the repo" not in out:
        fail(f"dirty-{fmt}: exit {rc}, want 1 and `modified the repo`")
    if os.path.exists(os.path.join(SAMPLE, "notes.txt")):
        os.remove(os.path.join(SAMPLE, "notes.txt"))
print("OK")
