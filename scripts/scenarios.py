"""Scenario runner: `scenarios.py [--repo DIR] run [ID]|tree-hash|check|can-fail REF`.

can-fail: exit 0 every scenario fails on REF, 1 one passes there, 4 none passes but one could not run here (n/a).

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
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir from sys.path
import shells  # noqa: E402 - the sys.path line above has to run first

LAYOUT = ".ekit/scenarios/<slug>/SCENARIO.md + run.sh"
NODOC = "missing SCENARIO.md — document it (story, covers, steps, expected)"


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


# Untracked Python bytecode is the interpreter's cache, never a scenario's output: left out even where no .gitignore
# names it. Tracked bytecode, and anything else under __pycache__/, still counts.
BYTECODE = (b".pyc", b".pyo")
# the caller's pathspec modes would change what `git add -A` and `ls-files` see
PATHSPEC_ENV = ("GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS")


def cannot_hash(r):
    print(f"cannot hash the working tree: {r.stderr.decode(errors='replace').strip()}", file=sys.stderr)
    sys.exit(3)


def tree_hash(repo):
    """Content id of the working tree: the git tree `git add -A` would write (tracked + untracked, ignore rules
    honoured, untracked Python bytecode left out), whichever dir of the repo it is asked from. A commit, amend or
    rebase that keeps the files keeps the hash, so a PASS survives the commit that follows it. Read-only for the repo: a copy of its index and a throwaway object dir take the writes, and the repo's
    own objects are read through an alternate. Files git cannot add (unreadable, fifo, socket, device) are left out."""
    gd = git(repo, "rev-parse", "--absolute-git-dir").strip()
    if not os.path.isdir(gd):
        return ""
    objects = os.path.join(repo, git(repo, "rev-parse", "--git-path", "objects").strip())
    with tempfile.TemporaryDirectory() as tmp:  # the throwaway object dir; the index copy sits in it too
        fd, index = tempfile.mkstemp(dir=tmp)
        os.close(fd)
        real = os.path.join(gd, "index")
        if os.path.exists(real):
            # unchanged files keep their entries: not re-read, and sparse entries stay. The copy keeps the index's
            # mtime: git re-reads an entry written in the same second as the index (racy git), because a same-size
            # edit in that second leaves the stat data git compares unchanged. A fresh mtime would hide that edit.
            st = os.stat(real)  # before the copy: an index rewritten in between only makes git re-read more
            shutil.copyfile(real, index)
            os.utime(index, ns=(st.st_atime_ns, st.st_mtime_ns))
        else:
            os.unlink(index)  # no index yet (fresh repo): git starts from none, an empty file is an error
        alt = os.pathsep.join(x for x in (objects, os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")) if x)
        genv = {k: v for k, v in os.environ.items() if k not in PATHSPEC_ENV}
        genv.update(GIT_INDEX_FILE=index, GIT_OBJECT_DIRECTORY=tmp, GIT_ALTERNATE_OBJECT_DIRECTORIES=alt)
        top = git(repo, "rev-parse", "--show-toplevel").strip() or repo

        def run(*args, **kw):
            return subprocess.run(["git", "-C", top, *args], env=genv, capture_output=True, **kw)

        untracked = run("ls-files", "-z", "-o", "--exclude-standard")  # before the add: what is untracked now
        if untracked.returncode:
            cannot_hash(untracked)
        r = run("add", "-A", "--ignore-errors")
        if r.returncode > 1:  # 1: some files could not be added (--ignore-errors left them out); more: git died
            cannot_hash(r)
        cache = [p for p in untracked.stdout.split(b"\0") if p.endswith(BYTECODE)]
        if cache:
            r = run("update-index", "--force-remove", "-z", "--stdin", input=b"\0".join(cache) + b"\0")
            if r.returncode:
                cannot_hash(r)
        r = run("write-tree")
        if r.returncode:
            cannot_hash(r)
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
    """ids of the repo's scenarios: each dir under the root that holds a run.sh, a parent before its children.
    A `fixtures` dir is a scenario's data: nothing inside one is a scenario, whatever it holds."""
    base = root(repo)
    ids = []
    for d, dirs, fs in os.walk(base):
        dirs[:] = [name for name in dirs if name != "fixtures"]
        if "run.sh" in fs:
            ids.append(os.path.relpath(d, base).replace(os.sep, "/"))  # an id reads the same on every OS
    return sorted(ids, key=lambda i: i.split("/"))


def timeout():
    try:
        return float(env("SCENARIO_TIMEOUT") or 300)
    except ValueError:
        return 300.0


def run_one(repo, sid, ids, tdir, kept=None):
    """ids: every scenario in the repo, not only the ones this run was filtered to: a child run alone still gets its
    parent's dir. kept: the dir that holds each scenario's last failed transcript (none: not kept)."""
    d = os.path.join(root(repo), sid)
    res = {"id": sid, "exit": None, "duration": 0.0, "transcript": os.path.join(tdir, sid.replace("/", "__") + ".log")}
    bash = shells.find("bash")  # on Windows: Git for Windows' bash, never WSL's
    if not os.path.isfile(os.path.join(d, "SCENARIO.md")):
        res.update(exit=1, reason=NODOC)
        out = err = b""
        cwd = ""
    elif not bash:
        res.update(exit=None, reason="bash is not on this machine (env)")
        out = err = b""
        cwd = ""
    else:
        parent = os.path.dirname(sid)
        pdir = os.path.join(root(repo), parent) if parent in ids else ""
        # screenshots and other files a person checks: kept beside the transcript, outside the work tree
        art = os.path.join(tdir, sid.replace("/", "__"))
        shutil.rmtree(art, ignore_errors=True)  # a rerun on the same tree lists only its own files
        os.makedirs(art)
        env = dict(os.environ, EKIT_REPO=repo, EKIT_SCENARIO_DIR=d, EKIT_PARENT_DIR=pdir, EKIT_ARTIFACT_DIR=art,
                   EK_REPO=repo, EK_SCENARIO_DIR=d, EK_PARENT_DIR=pdir,  # EK_*: pre-rename scenarios
                   PYTHONDONTWRITEBYTECODE="1")  # a scenario writes nothing into a checkout, bytecode included
        cwd = tempfile.mkdtemp(prefix="ekit-scenario-")
        t0 = time.time()
        limit = timeout()
        # output to files, not pipes: a child the stop misses can hold no pipe open, and what the scenario printed
        # before a timeout stays for the transcript
        fo, fe = tempfile.TemporaryFile(), tempfile.TemporaryFile()
        p = shells.spawn([bash, os.path.join(d, "run.sh")], cwd=cwd, env=shells.env_for(bash, "bash", env), stdout=fo,
                         stderr=fe)
        try:
            p.wait(timeout=limit)
            res["exit"] = p.returncode
        except subprocess.TimeoutExpired:
            shells.kill_tree(p)  # the process group on POSIX, the tree on Windows
            try:
                p.wait(timeout=shells.REAP)
            except subprocess.TimeoutExpired:
                pass  # escaped the stop: its output so far is in the files all the same
            res.update(exit=None, reason=f"timeout after {limit:g}s")
        finally:
            shells.finish(p)  # Windows: what the scenario left running stops with its job
            out, err = (f.seek(0) or f.read() for f in (fo, fe))
            fo.close()
            fe.close()
            res["duration"] = round(time.time() - t0, 3)
            shutil.rmtree(cwd, ignore_errors=True)
            files = sorted(os.path.join(dp, n) for dp, _, ns in os.walk(art) for n in ns)
            if files:
                res["artifacts"] = files
            else:
                shutil.rmtree(art, ignore_errors=True)
        if res["exit"] and "reason" not in res:
            res["reason"] = f"exit {res['exit']}"
    text = (f"command: bash run.sh\nscenario: {d}\ncwd: {cwd}\n--- stdout ---\n".encode() + out
            + b"\n--- stderr ---\n" + err + f"\n--- exit: {res['exit'] if res['exit'] is not None else 'timeout'} ---\n".encode())
    with open(res["transcript"], "wb") as f:
        f.write(text)
    if res.get("reason") and kept:
        # a flake's evidence: the next run on this tree (a pass) rewrites the transcript, so a copy stays until the
        # same scenario fails again
        res["failed_transcript"] = keep(kept, quote(sid, safe="") + ".log", text)
    return res


def keep(kept, name, text):
    """Write <kept>/<name> whole or not at all (a parallel run may write the same name); returns its path."""
    os.makedirs(kept, exist_ok=True)
    path = os.path.join(kept, name)
    fd, tmp = tempfile.mkstemp(dir=kept, prefix=".tmp-")
    with os.fdopen(fd, "wb") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def cmd_run(repo, only=None):
    ids = known = find(repo)
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
    results = [run_one(repo, sid, known, tdir, os.path.join(out, FAILED)) for sid in ids]
    for r in results:
        print(f"FAIL {r['id']}: {r['reason']}" if r.get("reason") else f"PASS {r['id']}")
    doc = {"verdict": "PASS", "tree": th, "repo": os.path.realpath(repo), "filter": only or None, "scenarios": results}
    if any(r.get("reason") for r in results):
        doc["verdict"] = "FAIL"
    after = repo_state(repo)
    if after != before:
        doc.update(verdict="FAIL", reason="scenarios modified the repo: run in the temp cwd")
        print("FAIL: " + doc["reason"])
        note = (f"scenarios: {' '.join(ids)}\nbefore (HEAD, tree): {before}\nafter (HEAD, tree): {after}\n"
                f"--- git status --porcelain ---\n{git(repo, 'status', '--porcelain')}")
        doc["failed_transcript"] = keep(os.path.join(out, FAILED), REPO_NOTE, note.encode())
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump(doc, f, indent=1)
    prune(out, th)
    print(f"{doc['verdict']}: {sum(not r.get('reason') for r in results)}/{len(results)} scenarios")
    return doc["verdict"] == "FAIL"


KEEP_DAYS = 14
FAILED = "failed"  # <out>/failed/<quoted id>.log: each scenario's last failed transcript, whatever its age
REPO_NOTE = "%repo.log"  # the last repo change; quote() writes no % that two hex digits do not follow


def prune(out, keep):
    """Drop transcript dirs of other trees once they are older than KEEP_DAYS; the current tree's and the kept
    failures stay."""
    cutoff = time.time() - KEEP_DAYS * 86400
    for name in os.listdir(out):
        d = os.path.join(out, name)
        if name not in (keep, FAILED) and os.path.isdir(d) and not os.path.islink(d) and os.path.getmtime(d) < cutoff:
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
        flagged = na = 0
        for sid in ids:
            res = run_one(wt, sid, ids, tmp)
            if str(res.get("reason", "")).endswith("(env)"):  # it never ran: no proof either way
                print(f"N/A {sid}: {res['reason']}")
                na += 1
            elif res.get("reason"):
                print(f"CAN-FAIL ✓ {sid}")
            else:
                print(f"CANNOT FAIL {sid}: passes on baseline {ref}")
                flagged += 1
        return 1 if flagged else 4 if na else 0
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
    failed = [r for r in res.get("scenarios") or [] if isinstance(r, dict) and r.get("reason")]
    if res.get("verdict") != "PASS" and failed and not res.get("reason") \
            and all(str(r["reason"]).endswith("(env)") for r in failed):
        # every failure is what this host lacks: the Stop gate takes a blocked report naming it
        print("cannot run here: " + "; ".join(f"{r.get('id')}: {r['reason']}" for r in failed))
    elif res.get("verdict") != "PASS":
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


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # ✓ and → on a Windows pipe, which reads as cp1252
    a = list(sys.argv[1:] if argv is None else argv)
    repo = "."
    if "--repo" in a:
        i = a.index("--repo")
        if i + 1 >= len(a):
            usage()
        repo = a[i + 1]
        del a[i:i + 2]
    if not os.path.isdir(repo):  # not "no scenarios found": the path itself is wrong
        print(f"scenarios.py: no such directory: {repo}", file=sys.stderr)
        sys.exit(2)
    top = git(repo, "rev-parse", "--show-toplevel").strip()
    repo = top or os.path.abspath(repo)
    cmds = {"run": cmd_run, "tree-hash": cmd_hash, "check": cmd_check, "can-fail": cmd_can_fail}
    if not a or a[0] not in cmds:
        usage()
    sys.exit(cmds[a[0]](repo, *a[1:2]) if a[0] in ("run", "can-fail") else cmds[a[0]](repo))


if __name__ == "__main__":
    main()
