"""runner/not-run: run.sh with no bash (and run.ps1 with no PowerShell) reads not run here (env)."""
import os
import shutil
import subprocess
import sys

if os.name == "nt":  # checked nothing: a FAIL that says why, never a PASS
    sys.exit("CANNOT CHECK: native Windows has no host to make without the shells: the runner finds Git Bash beside "
             "git.exe whatever PATH says, and Windows PowerShell under SystemRoot. Run this scenario on Linux, macOS "
             "or WSL; on native Windows it is verification debt.")

KIT = os.environ["EKIT_REPO"]
RUNNER = os.path.join(KIT, "scripts", "scenarios.py")
HERE = os.getcwd()
SAMPLE = os.path.join(HERE, "sample")
BIN = os.path.join(HERE, "bin")  # only Python and git: no bash, no sh, no PowerShell
os.makedirs(BIN)
for name, exe in (("python3", sys.executable), ("git", shutil.which("git"))):
    os.symlink(os.path.realpath(exe), os.path.join(BIN, name))
ENV = dict(os.environ, PATH=BIN, EKIT_STATE=os.path.join(HERE, "state"), GIT_CONFIG_GLOBAL=os.devnull,
           GIT_CONFIG_SYSTEM=os.devnull, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@t")
no_ps = not (shutil.which("pwsh") or shutil.which("powershell"))  # this host, whatever PATH the runner gets


def fail(msg):
    sys.exit(f"ASSERT FAILED: {msg}")


def git(*args):
    subprocess.run(["git", "-C", SAMPLE, *args], check=True, capture_output=True, env=ENV)


def run(*args):
    r = subprocess.run([sys.executable, RUNNER, "--repo", SAMPLE, *args], capture_output=True, text=True, env=ENV)
    if "Traceback" in r.stderr:
        fail(f"traceback from `{' '.join(args)}`: {r.stderr}")
    return r.returncode, r.stdout


def expect(what, got, want):
    if got != want:
        fail(f"{what}: expected [{want}] got [{got}]")


os.makedirs(SAMPLE)
git("init", "-q")
files = {"posix": ("run.sh", "exit 0\n"), "any": ("run.py", "print('ran')\n")}
if no_ps:
    files["win"] = ("run.ps1", "exit 0\n")
for sid, (name, text) in files.items():
    d = os.path.join(SAMPLE, ".ekit", "scenarios", sid)
    os.makedirs(d)
    for n, t in (("SCENARIO.md", f"# {sid}\n- story: s\n"), (name, text)):
        with open(os.path.join(d, n), "w") as f:
            f.write(t)
git("add", "-A")
git("commit", "-qm", "s")

bash = "posix: bash is not on this machine (env)"
ps = "win: PowerShell is not on this machine (env)"
rc, out = run("run")
want = "PASS any\nNOT-RUN " + bash + "\n" + ("NOT-RUN " + ps + "\n" if no_ps else "")
want += f"NOT-RUN: 1/{len(files)} scenarios\n"
expect("run", (rc, out), (1, want))
expect("check", run("check"), (1, "cannot run here: " + "; ".join([bash] + ([ps] if no_ps else [])) + "\n"))
shutil.rmtree(os.path.join(SAMPLE, ".ekit", "scenarios", "any"))  # can-fail runs the scenarios as they are now
rc, out = run("can-fail", "HEAD")
expect("can-fail rc", rc, 4)
for line in ["N/A " + bash] + (["N/A " + ps] if no_ps else []):
    if line not in out.splitlines():
        fail(f"can-fail: expected the line [{line}], got [{out}]")
print("not-run ok")
