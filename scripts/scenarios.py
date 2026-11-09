"""Scenario runner: `scenarios.py [--repo DIR] run [ID]|tree-hash|check|can-fail REF`.

Runs .ekit/scenarios/<slug>/run.sh in fresh temp dirs; evidence goes to <git dir>/ekit/ (or $EKIT_STATE/scenarios/<repo key>/).
Repo-local so the Stop hook (plugin env) and sandboxed Bash (read-only HOME) agree on one location.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

LAYOUT = ".ekit/scenarios/<slug>/SCENARIO.md + run.sh"
NODOC = "missing SCENARIO.md — document it (story, covers, steps, expected)"


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def tree_hash(repo):
    """Content id of the working tree: the git tree `git add -A` would write (tracked + untracked, ignore rules
    honoured). A commit, amend or rebase that keeps the files keeps the hash, so a PASS survives the commit that
    follows it. Read-only for the repo: a copy of the index and a throwaway object dir take the writes.
    Files git cannot add (unreadable, fifo, socket, device) are left out."""
    gd = git(repo, "rev-parse", "--absolute-git-dir").strip()
    if not gd:
        return ""
    objects = git(repo, "rev-parse", "--git-path", "objects").strip()
    objects = objects if os.path.isabs(objects) else os.path.join(repo, objects)
    with tempfile.TemporaryDirectory(prefix="ekit-tree-") as tmp:
        index = os.path.join(tmp, "index")
        try:
            shutil.copyfile(os.path.join(gd, "index"), index)
        except OSError:
            pass  # no index yet (fresh repo): start empty
        os.mkdir(os.path.join(tmp, "objects"))
        alt = os.pathsep.join(x for x in (objects, os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")) if x)
        genv = dict(os.environ, GIT_INDEX_FILE=index, GIT_OBJECT_DIRECTORY=os.path.join(tmp, "objects"),
                    GIT_ALTERNATE_OBJECT_DIRECTORIES=alt)
        subprocess.run(["git", "-C", repo, "add", "-A", "--ignore-errors"], env=genv, capture_output=True)
        r = subprocess.run(["git", "-C", repo, "write-tree"], env=genv, capture_output=True)
        if r.returncode:
            print(f"cannot hash the working tree: {r.stderr.decode(errors='replace').strip()}", file=sys.stderr)
            sys.exit(3)
        return r.stdout.decode().strip()


def repo_state(repo):
    """(HEAD, tree hash): what a scenario must leave untouched."""
    return git(repo, "rev-parse", "HEAD").strip(), tree_hash(repo)


def env(name):
    """EKIT_<name>, falling back to the pre-rename EK_<name>."""
    return os.environ.get("EKIT_" + name) or os.environ.get("EK_" + name)


def outdir(repo):
    if env("STATE"):
        key = hashlib.sha1(os.path.realpath(repo).encode()).hexdigest()[:12]
        return os.path.join(env("STATE"), "scenarios", key)
    gd = git(repo, "rev-parse", "--absolute-git-dir").strip()
    return os.path.join(gd or os.path.join(repo, ".git"), "ekit")


def root(repo):
    """.ekit/scenarios; a pre-rename repo with only .ek/scenarios keeps working."""
    new, old = os.path.join(repo, ".ekit", "scenarios"), os.path.join(repo, ".ek", "scenarios")
    return old if not os.path.isdir(new) and os.path.isdir(old) else new


def find(repo):
    base = root(repo)
    return sorted((os.path.relpath(d, base) for d, _, fs in os.walk(base) if "run.sh" in fs), key=lambda i: i.split("/"))


def timeout():
    try:
        return float(env("SCENARIO_TIMEOUT") or 300)
    except ValueError:
        return 300.0


def run_one(repo, sid, ids, tdir):
    d = os.path.join(root(repo), sid)
    res = {"id": sid, "exit": None, "duration": 0.0, "transcript": os.path.join(tdir, sid.replace("/", "__") + ".log")}
    if not os.path.isfile(os.path.join(d, "SCENARIO.md")):
        res.update(exit=1, reason=NODOC)
        out = err = b""
        cwd = ""
    else:
        parent = os.path.dirname(sid)
        pdir = os.path.join(root(repo), parent) if parent in ids else ""
        env = dict(os.environ, EKIT_REPO=repo, EKIT_SCENARIO_DIR=d, EKIT_PARENT_DIR=pdir,
                   EK_REPO=repo, EK_SCENARIO_DIR=d, EK_PARENT_DIR=pdir)  # EK_*: pre-rename scenarios
        cwd = tempfile.mkdtemp(prefix="ekit-scenario-")
        t0 = time.time()
        limit = timeout()
        p = subprocess.Popen(["bash", os.path.join(d, "run.sh")], cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
        try:
            out, err = p.communicate(timeout=limit)
            res["exit"] = p.returncode
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, 9)
            out, err = p.communicate()
            res.update(exit=None, reason=f"timeout after {limit:g}s")
        finally:
            res["duration"] = round(time.time() - t0, 3)
            shutil.rmtree(cwd, ignore_errors=True)
        if res["exit"] and "reason" not in res:
            res["reason"] = f"exit {res['exit']}"
    with open(res["transcript"], "wb") as f:
        f.write(f"command: bash run.sh\nscenario: {d}\ncwd: {cwd}\n--- stdout ---\n".encode() + out
                + b"\n--- stderr ---\n" + err + f"\n--- exit: {res['exit'] if res['exit'] is not None else 'timeout'} ---\n".encode())
    return res


def cmd_run(repo, only=None):
    ids = find(repo)
    if not ids:
        print(f"no scenarios found. expected layout: {LAYOUT}")
        return 2
    if only:
        only = only.strip("/")
        ids = [i for i in ids if i == only or i.startswith(only + "/")]
        if not ids:
            print(f"no scenario '{only}' (or children) under .ekit/scenarios/")
            return 2
    before = repo_state(repo)
    th = before[1]
    out = outdir(repo)
    tdir = os.path.join(out, th)
    os.makedirs(tdir, exist_ok=True)
    results = [run_one(repo, sid, ids, tdir) for sid in ids]
    for r in results:
        print(f"FAIL {r['id']}: {r['reason']}" if r.get("reason") else f"PASS {r['id']}")
    doc = {"verdict": "PASS", "tree": th, "repo": os.path.realpath(repo), "filter": only or None, "scenarios": results}
    if any(r.get("reason") for r in results):
        doc["verdict"] = "FAIL"
    if repo_state(repo) != before:
        doc.update(verdict="FAIL", reason="scenarios modified the repo: run in the temp cwd")
        print("FAIL: " + doc["reason"])
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump(doc, f, indent=1)
    prune(out, th)
    print(f"{doc['verdict']}: {sum(not r.get('reason') for r in results)}/{len(results)} scenarios")
    return doc["verdict"] == "FAIL"


KEEP_DAYS = 14


def prune(out, keep):
    """Drop transcript dirs of other trees once they are older than KEEP_DAYS; the current tree's stay."""
    cutoff = time.time() - KEEP_DAYS * 86400
    for name in os.listdir(out):
        d = os.path.join(out, name)
        if name != keep and os.path.isdir(d) and not os.path.islink(d) and os.path.getmtime(d) < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def cmd_can_fail(repo, ref=None):
    if not ref:
        usage()
    ids = find(repo)
    if not ids:
        print(f"no scenarios found. expected layout: {LAYOUT}")
        return 2
    tmp = tempfile.mkdtemp(prefix="ekit-canfail-")
    wt = os.path.join(tmp, "wt")
    try:
        r = subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", wt, ref], capture_output=True, text=True)
        if r.returncode:
            print(f"cannot create worktree at {ref}: {r.stderr.strip()}")
            return 2
        shutil.rmtree(root(wt), ignore_errors=True)
        shutil.copytree(root(repo), root(wt))
        flagged = 0
        for sid in ids:
            res = run_one(wt, sid, ids, tmp)
            if res.get("reason"):
                print(f"CAN-FAIL ✓ {sid}")
            else:
                print(f"CANNOT FAIL {sid}: passes on baseline {ref}")
                flagged += 1
        return flagged > 0
    finally:
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["git", "-C", repo, "worktree", "prune"], capture_output=True)


def cmd_hash(repo):
    print(tree_hash(repo))
    return 0


def cmd_check(repo):
    if not os.path.isdir(root(repo)):
        print(f"no scenarios. expected layout: {LAYOUT}")
        return 2
    try:
        with open(os.path.join(outdir(repo), "results.json")) as f:
            res = json.load(f)
    except (OSError, ValueError):
        print("no results: run scenarios")
        return 1
    if res.get("verdict") != "PASS":
        print("last run FAIL")
    elif res.get("filter"):
        print(f"partial run: only '{res['filter']}' was run; run all scenarios")
    elif res.get("tree") != tree_hash(repo):
        print("stale: tree changed since run")
    else:
        return 0
    return 1


def usage():
    print("usage: scenarios.py [--repo DIR] run [ID]|tree-hash|check|can-fail REF", file=sys.stderr)
    sys.exit(2)


def main():
    a = sys.argv[1:]
    repo = "."
    if "--repo" in a:
        i = a.index("--repo")
        if i + 1 >= len(a):
            usage()
        repo = a[i + 1]
        del a[i:i + 2]
    top = git(repo, "rev-parse", "--show-toplevel").strip()
    repo = top or os.path.abspath(repo)
    cmds = {"run": cmd_run, "tree-hash": cmd_hash, "check": cmd_check, "can-fail": cmd_can_fail}
    if not a or a[0] not in cmds:
        usage()
    sys.exit(cmds[a[0]](repo, *a[1:2]) if a[0] in ("run", "can-fail") else cmds[a[0]](repo))


if __name__ == "__main__":
    main()
