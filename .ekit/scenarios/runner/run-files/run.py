"""runner/run-files: a folder with two or more run files is an error naming them all; none of them runs."""
import os
import shutil
import subprocess
import sys

if os.name == "nt":
    sys.exit("CANNOT CHECK: native Windows finds Git Bash beside git.exe whatever PATH says; run this on Linux, macOS or WSL.")

HERE = os.getcwd()
KIT = os.path.join(HERE, "kit")
SAMPLE = os.path.join(HERE, "sample")
MARKS = os.path.join(HERE, "marks")
BIN = os.path.join(HERE, "bin")  # only Python and git: no bash, no sh, no PowerShell
os.makedirs(MARKS)
os.makedirs(BIN)
for name, exe in (("python3", sys.executable), ("git", shutil.which("git"))):
    os.symlink(os.path.realpath(exe), os.path.join(BIN, name))
BASE_ENV = dict(os.environ, EKIT_STATE=os.path.join(HERE, "state"), GIT_CONFIG_GLOBAL=os.devnull,
                GIT_CONFIG_SYSTEM=os.devnull, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
NO_BASH = dict(BASE_ENV, PATH=BIN)


def fail(msg):
    sys.exit(f"ASSERT FAILED: {msg}")


def sh(args, env=BASE_ENV, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, env=env, **kw)


# the kit as a user gets it: a git clone (of the tree under test)
sh(["git", "clone", "-q", os.environ["EKIT_REPO"], KIT])
RUNNER = os.path.join(KIT, "scripts", "scenarios.py")
kit_status = sh(["git", "-C", KIT, "status", "--porcelain"]).stdout


def run(args, env):
    r = subprocess.run([sys.executable, RUNNER, "--repo", SAMPLE, *args], capture_output=True, text=True,
                       env=env, timeout=300)
    out = r.stdout + r.stderr
    if "Traceback" in out:
        fail(f"traceback from `{' '.join(args)}`:\n{out}")
    return r.returncode, out


BODY = {
    "run.py": "open({m!r}, 'w').close()\n",
    "run.sh": "touch {m!r}\n",
    "run.ps1": "New-Item -ItemType File -Path '{m}' | Out-Null\nexit 0\n",
}


def scenario(sid, files):
    d = os.path.join(SAMPLE, ".ekit", "scenarios", *sid.split("/"))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SCENARIO.md"), "w") as f:
        f.write(f"# {sid}\n\n- story: s\n- covers: c\n- steps: s\n- expected: e\n")
    for name in files:
        mark = os.path.join(MARKS, sid.replace("/", "_") + "." + name)
        with open(os.path.join(d, name), "w") as f:
            f.write(BODY[name].format(m=mark))


os.makedirs(SAMPLE)
sh(["git", "init", "-q", SAMPLE])
with open(os.path.join(SAMPLE, "app.txt"), "w") as f:
    f.write("app\n")
scenario("trio", ["run.py", "run.sh", "run.ps1"])
scenario("pair", ["run.py", "run.ps1"])
scenario("ok", ["run.py"])
scenario("ok/kid", ["run.py", "run.sh"])
sh(["git", "-C", SAMPLE, "add", "-A"])
sh(["git", "-C", SAMPLE, "commit", "-qm", "scenarios"])

NAMES = {"trio": ["run.py", "run.sh", "run.ps1"], "pair": ["run.py", "run.ps1"], "ok/kid": ["run.py", "run.sh"]}


def line_for(out, word, sid):
    for ln in out.splitlines():
        if ln.startswith(f"{word} {sid}:") or ln == f"{word} {sid}":
            return ln
    fail(f"no `{word} {sid}` line in:\n{out}")


def assert_multi(out, word, label):
    for sid, names in NAMES.items():
        ln = line_for(out, word, sid)
        missing = [n for n in names if n not in ln]
        if missing:
            fail(f"{label}: `{ln}` does not name {missing}")
        if f"NOT-RUN {sid}" in out:
            fail(f"{label}: {sid} read NOT-RUN, not the run-file error:\n{out}")


def assert_no_marks(label):
    left = sorted(m for m in os.listdir(MARKS) if not m.startswith("ok.run.py"))
    if left:
        fail(f"{label}: run files ran although their folder had more than one: {left}")


# 2. no bash on PATH
rc, out = run(["run"], NO_BASH)
print("--- run (only python and git on PATH)\n" + out)
if rc != 1:
    fail(f"run with two run files: exit {rc}, want 1")
assert_multi(out, "FAIL", "run, no bash")
line_for(out, "PASS", "ok")
assert_no_marks("run, no bash")

rc, out = run(["check"], NO_BASH)
print("--- check\n" + out)
if rc != 1:
    fail(f"check after a FAIL: exit {rc}, want 1")

rc, out = run(["can-fail", "HEAD"], NO_BASH)
print("--- can-fail HEAD\n" + out)
if rc != 2:
    fail(f"can-fail with two run files: exit {rc}, want 2")
assert_multi(out, "ERROR", "can-fail")
assert_no_marks("can-fail")

# 3. full PATH: bash is here, still no pick
rc, out = run(["run"], BASE_ENV)
print("--- run (full PATH)\n" + out)
if rc != 1:
    fail(f"run with bash, two run files: exit {rc}, want 1")
assert_multi(out, "FAIL", "run, bash present")
assert_no_marks("run, bash present")

# 4. one run file each: green
for sid, names in NAMES.items():
    for n in names:
        if n != "run.py":
            os.remove(os.path.join(SAMPLE, ".ekit", "scenarios", *sid.split("/"), n))
sh(["git", "-C", SAMPLE, "add", "-A"])
sh(["git", "-C", SAMPLE, "commit", "-qm", "one run file each"])
rc, out = run(["run"], NO_BASH)
print("--- run (one run file each)\n" + out)
if rc != 0:
    fail(f"run with one run.py each: exit {rc}, want 0")
for sid in ("trio", "pair", "ok", "ok/kid"):
    line_for(out, "PASS", sid)
rc, out = run(["check"], NO_BASH)
print("--- check\n" + out)
if rc != 0:
    fail(f"check after a green run: exit {rc}, want 0")

if sh(["git", "-C", KIT, "status", "--porcelain"]).stdout != kit_status:
    fail("the runner wrote into the kit clone")
print("OK")
