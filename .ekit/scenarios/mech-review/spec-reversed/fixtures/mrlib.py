"""Shared helpers for the mech-review/spec-reversed scenarios (imported, not a scenario).

A user's view: build a throwaway git repo in the temp cwd, commit, run the kit's CLI at
$EKIT_REPO/scripts/mech-review.py with python3, read its JSON.
"""
import json
import os
import subprocess
import sys

HERE = os.getcwd()
MR = os.path.join(os.environ["EKIT_REPO"], "scripts", "mech-review.py")
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
           GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@t", HOME=os.path.join(HERE, "home"))
os.makedirs(ENV["HOME"], exist_ok=True)


def fail(msg):
    sys.exit(f"ASSERT FAILED: {msg}")


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=ENV)
    if r.returncode:
        fail(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def write(repo, files):
    for path, text in files.items():
        p = os.path.join(repo, path)
        if text is None:
            os.remove(p)
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def new_repo(name, files):
    """A fresh repo holding `files` at its first commit; returns (path, base sha)."""
    repo = os.path.join(HERE, name)
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    write(repo, files)
    return repo, commit(repo, {}, "base")


def commit(repo, files, msg):
    write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def branch(repo, name, at):
    git(repo, "checkout", "-q", "-b", name, at)


def mr(*args):
    """Run the CLI; returns (exit code, parsed JSON or None, stdout, stderr)."""
    r = subprocess.run([sys.executable, MR, *args], capture_output=True, text=True, env=ENV, timeout=600)
    try:
        data = json.loads(r.stdout)
    except ValueError:
        data = None
    if "Traceback" in r.stderr:
        fail(f"traceback from {args}:\n{r.stderr}")
    return r.returncode, data, r.stdout, r.stderr


def r2(repo, base, head, stack, *extra):
    return mr("r2", "--repo", repo, "--base", base, "--head", head, "--stack", stack,
              "--test-paths", "tests/**", *extra)


def r2_entries(data):
    if data is None:
        fail("no JSON on stdout")
    return [e for e in data["entries"] if e["check"] == "R2"]


def expect(label, cond, detail=""):
    if not cond:
        fail(f"{label}: {detail}")


def expect_fail_removed(label, res, test):
    """The plain removal: exit 1, one R2 fail naming the test, no confirm."""
    rc, data, out, err = res
    es = r2_entries(data)
    expect(label + " exit", rc == 1, f"want 1, got {rc}\n{out}{err}")
    fails = [e for e in es if e["severity"] == "fail" and f"`{test}`" in e["problem"]]
    expect(label + " fail entry", len(fails) == 1 and "removed" in fails[0]["problem"], out)
    expect(label + " no spec confirm", not any("spec #" in e["problem"] for e in es), out)
    expect(label + " summary", data["summary"].startswith("fail "), data["summary"])


def expect_spec_confirm(label, res, test, n, head):
    """The spec-reversed removal: exit 0, exactly one R2 entry, a confirm naming test and #n."""
    rc, data, out, err = res
    es = r2_entries(data)
    expect(label + " exit", rc == 0, f"want 0, got {rc}\n{out}{err}")
    expect(label + " one entry", len(es) == 1, out)
    e = es[0]
    expect(label + " confirm", e["severity"] == "confirm", out)
    expect(label + " names test and issue", f"`{test}`" in e["problem"] and f"#{n} " in e["problem"] + " "
           and "removed" in e["problem"], e["problem"])
    expect(label + " hint: quoted sentence of the issue",
           "quoted sentence" in e["hint"] and f"#{n}" in e["hint"] and "restore" in e["hint"], e["hint"])
    expect(label + " summary", data["summary"] == f"pass {head} (0 fail, 1 confirm; ran: R2; skipped: R1 R3 R4)",
           data["summary"])
