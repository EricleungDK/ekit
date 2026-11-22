"""runner/run-py: run.py scenarios in a sample repo, driven through the runner the kit ships (no bash used)."""
import os
import shutil
import subprocess
import sys
import time

KIT = os.environ["EKIT_REPO"]
RUNNER = os.path.join(KIT, "scripts", "scenarios.py")
HERE = os.getcwd()  # the runner's fresh temp cwd
os.environ.update(EKIT_STATE=os.path.join(HERE, "state"), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                  GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
SAMPLE = os.path.join(HERE, "sample")


def fail(msg):
    sys.exit(f"ASSERT FAILED: {msg}")


def git(*args):
    subprocess.run(["git", "-C", SAMPLE, *args], check=True, capture_output=True)


def scenario(sid, files):
    d = os.path.join(SAMPLE, ".ekit", "scenarios", sid)
    os.makedirs(d, exist_ok=True)
    files = dict({"SCENARIO.md": f"# {sid}\n- story: s\n- covers: c\n- steps: x\n- expected: y\n"}, **files)
    for name, text in files.items():
        with open(os.path.join(d, name), "w", newline="\n") as f:
            f.write(text)


def run(*args, **env):
    r = subprocess.run([sys.executable, RUNNER, "--repo", SAMPLE, *args], capture_output=True, text=True,
                       env=dict(os.environ, **env))
    if "Traceback" in r.stderr:
        fail(f"traceback from `{' '.join(args)}`: {r.stderr}")
    return r.returncode, r.stdout


def expect(what, got, want):
    if got != want:
        fail(f"{what}: expected [{want}] got [{got}]")


def has(what, out, part):
    if part not in out:
        fail(f"{what}: expected output to contain [{part}], got [{out}]")


os.makedirs(SAMPLE)
git("init", "-q")
with open(os.path.join(SAMPLE, "app.py"), "w") as f:
    f.write("print('hi')\n")
scenario("hello", {"run.py": "print('scenario-hello')\n"})
scenario("bad", {"run.py": "import sys\nsys.exit(2)\n"})
git("add", "-A")
git("commit", "-qm", "s")

rc, out = run("run")
expect("run rc with a failing run.py", rc, 1)
has("run", out, "PASS hello")
has("run", out, "FAIL bad: exit 2")

scenario("hello", {"run.sh": "exit 0\n"})
rc, out = run("run")
expect("run rc with two run files", rc, 1)
has("run", out, "FAIL hello: more than one run file (run.py, run.sh): keep one")

os.remove(os.path.join(SAMPLE, ".ekit", "scenarios", "hello", "run.sh"))
shutil.rmtree(os.path.join(SAMPLE, ".ekit", "scenarios", "bad"))
git("add", "-A")
git("commit", "-qm", "drop")
rc, out = run("run")
expect("run rc green", rc, 0)
has("run", out, "PASS: 1/1")
expect("check rc fresh", run("check")[0], 0)

mark = os.path.join(HERE, "late")
child = f"import time; time.sleep(4); open({mark!r}, 'w')"
scenario("hang", {"run.py": f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {child!r}])\n"
                            "time.sleep(30)\n"})
git("add", "-A")
git("commit", "-qm", "hang")
t0 = time.time()
rc, out = run("run", "hang", EKIT_SCENARIO_TIMEOUT="1")
took = time.time() - t0
expect("timeout rc", rc, 1)
has("timeout", out, "FAIL hang: timeout after 1s")
if took >= 15:
    fail(f"timeout took {took:.0f}s")
time.sleep(5)
if os.path.exists(mark):
    fail("the run.py's background child outlived its timeout")
print("run-py ok")
