"""runner/run-py/own-session: a child in its own session is still part of the scenario's tree."""
import os
import shutil
import subprocess
import sys
import time

if os.name == "nt":
    sys.exit("CANNOT CHECK: POSIX sessions only; on Windows this is verification debt.")

HERE = os.getcwd()
KIT = os.path.join(HERE, "kit")
SAMPLE = os.path.join(HERE, "sample")
MARKS = os.path.join(HERE, "marks")
os.makedirs(MARKS)
ENV = dict(os.environ, EKIT_STATE=os.path.join(HERE, "state"), GIT_CONFIG_GLOBAL=os.devnull,
           GIT_CONFIG_SYSTEM=os.devnull, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def fail(msg):
    sys.exit(f"ASSERT FAILED: {msg}")


def sh(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, env=ENV, **kw)


sh(["git", "clone", "-q", os.environ["EKIT_REPO"], KIT])
RUNNER = os.path.join(KIT, "scripts", "scenarios.py")

RUN_PY = '''import subprocess, sys, time
MARKS = {marks!r}
late = "import sys, time; time.sleep(4); open(sys.argv[1], 'w').close()"
subprocess.Popen([sys.executable, "-c", late, MARKS + "/{sid}.plain"])
grand = ("import subprocess, sys, time; "
         "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2] + '.grand']); "
         "time.sleep(4); open(sys.argv[2], 'w').close()")
subprocess.Popen([sys.executable, "-c", grand, late, MARKS + "/{sid}.session"], start_new_session=True)
time.sleep(0.5)
{tail}
'''

sh(["git", "init", "-q", SAMPLE])
for sid, tail in (("hang", "time.sleep(30)"),):
    d = os.path.join(SAMPLE, ".ekit", "scenarios", sid)
    os.makedirs(d)
    with open(os.path.join(d, "SCENARIO.md"), "w") as f:
        f.write(f"# {sid}\n\n- story: s\n- covers: c\n- steps: s\n- expected: e\n")
    with open(os.path.join(d, "run.py"), "w") as f:
        f.write(RUN_PY.format(marks=MARKS, sid=sid, tail=tail))
sh(["git", "-C", SAMPLE, "add", "-A"])
sh(["git", "-C", SAMPLE, "commit", "-qm", "scenarios"])


def run(args, env):
    t0 = time.time()
    r = subprocess.run([sys.executable, RUNNER, "--repo", SAMPLE, *args], capture_output=True, text=True,
                       env=env, timeout=120)
    out = r.stdout + r.stderr
    print(f"--- {' '.join(args)} ({time.time() - t0:.1f}s, exit {r.returncode})\n{out}")
    if "Traceback" in out:
        fail(f"traceback from `{' '.join(args)}`")
    return r.returncode, out, time.time() - t0


def marks_after_wait(label):
    time.sleep(7)
    left = sorted(os.listdir(MARKS))
    if left:
        fail(f"{label}: children outlived their scenario and wrote {left}")


rc, out, took = run(["run", "hang"], dict(ENV, EKIT_SCENARIO_TIMEOUT="1"))
if rc != 1 or "FAIL hang: timeout after 1s" not in out:
    fail(f"timeout run: exit {rc}, want 1 and `FAIL hang: timeout after 1s`")
if took > 15:
    fail(f"timeout run took {took:.1f}s, want under 15s")
marks_after_wait("after the timeout")
# out of scope: an own-session child outliving a run.py that exits normally (see SCENARIO.md)
print("OK")
