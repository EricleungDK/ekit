"""Scenario runner: `scenarios.py [--repo DIR] run [ID]|tree-hash|check|can-fail REF|seeded ID`.

can-fail: exit 0 every scenario fails on REF, 1 one passes there, 4 none passes but one could not run here (n/a),
2 a scenario folder holds more than one run file (or no worktree at REF).
seeded: the same read of ID and its children on the files as they are (a seeded scenario fails until its feature
works); 2 also for a scenario with no `- feature:` line in its SCENARIO.md.
A `- feature: <name>` line marks a scenario's feature: `run` (unfiltered) and `check` (fresh, full run) end with
`N of M features working`, N the marked features whose scenarios all PASS; no line when none is marked.

Runs .ekit/scenarios/<slug>/run.py (the Python running this runner), run.sh (bash) or run.ps1 (PowerShell) in fresh
temp dirs; evidence goes to <git dir>/ekit/ (or $EKIT_STATE/scenarios/<repo key>/).
Repo-local so the Stop hook (plugin env) and sandboxed Bash (read-only HOME) agree on one location.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir from sys.path
import shells  # noqa: E402 - the sys.path line above has to run first

# run.sh first only because scenarios already match this text (runner/no-layout); run.py is what taste-it writes
LAYOUT = ".ekit/scenarios/<slug>/SCENARIO.md + run.sh, run.py or run.ps1 (one of them)"
RUN_FILES = ("run.py", "run.sh", "run.ps1")  # a scenario's one run file: what makes a dir a scenario
NODOC = "missing SCENARIO.md — document it (story, covers, steps, expected)"
MANY = "more than one run file"
# the caller's Python settings a scenario does not inherit: each changes what a run.py's own exit means.
# PYTHONOPTIMIZE strips assert (a failed one would PASS); PYTHONSAFEPATH takes the scenario dir off sys.path (an
# import of a helper beside run.py would FAIL); PYTHONINSPECT turns sys.exit(N) into an interactive prompt's exit.
PY_UNSET = ("PYTHONOPTIMIZE", "PYTHONSAFEPATH", "PYTHONINSPECT")


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
    """ids of the repo's scenarios: each dir under the root that holds a run file, a parent before its children.
    A `fixtures` dir is a scenario's data: nothing inside one is a scenario, whatever it holds."""
    base = root(repo)
    ids = []
    for d, dirs, fs in os.walk(base):
        dirs[:] = [name for name in dirs if name != "fixtures"]
        if any(f in fs for f in RUN_FILES):
            ids.append(os.path.relpath(d, base).replace(os.sep, "/"))  # an id reads the same on every OS
    return sorted(ids, key=lambda i: i.split("/"))


def timeout():
    try:
        return float(env("SCENARIO_TIMEOUT") or 300)
    except ValueError:
        return 300.0


def program(run_file):
    """(name, executable or None) that runs `run_file`: run.py the Python running this runner (the one the hooks
    found), run.sh bash (Git Bash on Windows, never WSL's), run.ps1 pwsh, else Windows PowerShell."""
    if run_file == "run.py":
        return "python", sys.executable or None
    if run_file == "run.sh":
        return "bash", shells.find("bash")
    for name in shells.PS_SHELLS:
        exe = shells.find(name)
        if exe:
            return name, exe
    return "powershell", None


LABEL = {"python": "Python", "powershell": "PowerShell"}  # how a missing program is named; bash as it is


def not_here(res):
    """True when the scenario was not run: this host lacks what runs it (env), so no proof either way."""
    return str(res.get("reason")).endswith("(env)")


def argv(name, exe, path):
    """How `exe` runs the run file at `path`. run.ps1: called from -Command, not run with -File (which exits 0 on
    normal termination whatever the last native command gave). The exit code is the script's own `exit N`, else 1
    when an error stops it, else the exit code of the last native command it ran (0 if none). Not bash's last-status
    rule: a native failure the script handled, then cmdlets, reads FAIL with that code (a false FAIL, never a false
    PASS), and a `$LASTEXITCODE = 0` in the script sets only a script-scope copy: such a script ends with `exit 0`."""
    if name in shells.PS_SHELLS:
        # one line, `;` between: cmd.exe (a .cmd shim in the way) ends a command line at a line feed
        line = f"$global:LASTEXITCODE = 0; & {shells.ps_call_path(path)}; {shells.PS_EXIT.strip()}; exit $LASTEXITCODE"
        return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", line]
    return [exe, path]


def run_one(repo, sid, ids, tdir, kept=None):
    """ids: every scenario in the repo, not only the ones this run was filtered to: a child run alone still gets its
    parent's dir. kept: the dir that holds each scenario's last failed transcript (none: not kept)."""
    d = os.path.join(root(repo), sid)
    res = {"id": sid, "exit": None, "duration": 0.0, "transcript": os.path.join(tdir, sid.replace("/", "__") + ".log")}
    # files and links to files, as find() sees them: a dangling link is still the run file the author wrote (it fails
    # as itself); a directory, or a link to one, is not a run file
    found = [f for f in RUN_FILES if os.path.lexists(os.path.join(d, f)) and not os.path.isdir(os.path.join(d, f))]
    run_file = found[0]
    name, exe = program(run_file)
    command = f"{name} {run_file}"
    if len(found) > 1:  # never a silent pick: which one the author meant is theirs to say
        res.update(exit=1, reason=f"{MANY} ({', '.join(found)}): keep one")
        out = err = b""
        cwd = ""
        command = "none"
    elif not os.path.isfile(os.path.join(d, "SCENARIO.md")):
        res.update(exit=1, reason=NODOC)
        out = err = b""
        cwd = ""
    elif not exe:
        res.update(exit=None, reason=f"{LABEL.get(name, name)} is not on this machine (env)")
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
        env = {k: v for k, v in env.items() if k not in PY_UNSET}
        cwd = tempfile.mkdtemp(prefix="ekit-scenario-")
        t0 = time.time()
        limit = timeout()
        # output to files, not pipes: a child the stop misses can hold no pipe open, and what the scenario printed
        # before a timeout stays for the transcript
        fo, fe = tempfile.TemporaryFile(), tempfile.TemporaryFile()
        p = shells.spawn(argv(name, exe, os.path.join(d, run_file)), cwd=cwd, env=shells.env_for(exe, name, env),
                         stdout=fo, stderr=fe)
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
    text = (f"command: {command}\nscenario: {d}\ncwd: {cwd}\n--- stdout ---\n".encode() + out
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


# a SCENARIO.md field line `- feature: <name>`; [^\S\n]: a blank that is not a line end (a \r of CRLF included)
FEATURE = re.compile(r"^[-*][^\S\n]*feature[^\S\n]*:[^\S\n]*(.*?)[^\S\n]*$")
# any line that looks meant as one (another case, bold, no bullet): read as a marker or named, never dropped
FEATURE_LIKE = re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*|__)?feature(?:\*\*|__)?\s*:", re.I)
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def marker(repo, sid):
    """(feature, error) of a scenario's SCENARIO.md: the `- feature: <name>` line taste-it seeds it with (an empty one
    marks nothing). Lines inside a fenced block are text, not fields. error: no SCENARIO.md, more than one feature line,
    or a feature line not in that form, each named, never a silent pick or drop."""
    path = os.path.join(root(repo), sid, "SCENARIO.md")
    if not os.path.isfile(path):
        return None, NODOC
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    found, fence = [], None
    for line in text.lstrip("\ufeff").splitlines():
        m = FENCE.match(line)
        if m and (fence is None or m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)):
            fence = None if fence else m.group(1)
        elif not fence and FEATURE_LIKE.match(line):
            found.append(line.strip())
    if len(found) > 1:
        names = ", ".join(x.split(":", 1)[1].strip() for x in found)
        return None, f"SCENARIO.md has more than one feature line ({names}): keep one"
    if not found:
        return None, None
    m = FEATURE.match(found[0])
    if not m:
        return None, f"SCENARIO.md feature line `{found[0]}` is not `- feature: <name>`"
    return m.group(1) or None, None


def features_line(results, valid=True):
    """`N of M features working`: M marked features (a name counts once whatever its case and spacing), N of them with
    every scenario marked with it a PASS; None when no scenario is marked. valid=False: the run proves no scenario (it
    modified the repo), so no feature works. A row that is not a dict, or whose feature is not a string, marks none."""
    works = {}
    for r in results:
        name = r.get("feature") if isinstance(r, dict) else None
        if isinstance(name, str) and name.split():
            key = " ".join(name.split()).casefold()
            works[key] = works.get(key, True) and valid and not r.get("reason")
    return f"{sum(works.values())} of {len(works)} features working" if works else None


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
        name, err = marker(repo, r["id"])
        if name:
            r["feature"] = name  # results.json keeps it: check counts the features from there
        elif err and err != NODOC:  # no SCENARIO.md is run_one's FAIL already
            r["reason"] = err  # the folder is to be fixed, whatever the run gave
    for r in results:
        print(f"{'NOT-RUN' if not_here(r) else 'FAIL'} {r['id']}: {r['reason']}" if r.get("reason") else f"PASS {r['id']}")
    doc = {"verdict": "PASS", "tree": th, "repo": os.path.realpath(repo), "filter": only or None, "scenarios": results}
    if any(r.get("reason") and not not_here(r) for r in results):
        doc["verdict"] = "FAIL"
    elif any(r.get("reason") for r in results):
        doc["verdict"] = "NOT-RUN"  # nothing failed, but this host could not run each scenario: never a PASS
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
    line = features_line(results, valid="reason" not in doc)
    if line and not only:  # a filtered run sees only some of a feature's scenarios
        print(line)
    return doc["verdict"] != "PASS"


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
        bad = False
        for sid in ids:
            res = run_one(wt, sid, ids, tmp)
            if not_here(res):  # it never ran: no proof either way
                print(f"N/A {sid}: {res['reason']}")
                na += 1
            elif str(res.get("reason")).startswith(MANY):  # fails on any tree: the folder is to be fixed
                print(f"ERROR {sid}: {res['reason']}")
                bad = True
            elif res.get("reason"):
                print(f"CAN-FAIL ✓ {sid}")
            else:
                print(f"CANNOT FAIL {sid}: passes on baseline {ref}")
                flagged += 1
        return 2 if bad else 1 if flagged else 4 if na else 0
    finally:
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["git", "-C", repo, "worktree", "prune"], capture_output=True)


def cmd_seeded(repo, only=None):
    """A seeded scenario proves something only while its feature is missing: each scenario under `only` (it and its
    children) is run on the files as they are. exit 0 each one fails, 1 one passes (it checks nothing yet), 4 none
    passes but one could not run here, 2 one has no feature marker or more than one run file. Writes no results.json:
    `check` still reads the last full run."""
    if not only:
        usage()
    only = only.strip("/")
    known = find(repo)
    ids = [i for i in known if i == only or i.startswith(only + "/")]
    if not ids:
        print(f"no scenario '{only}' (or children) under .ekit/scenarios/")
        return 2
    flagged = na = 0
    bad = False
    with tempfile.TemporaryDirectory(prefix="ekit-seeded-") as tmp:
        for sid in ids:
            name, err = marker(repo, sid)
            if not name:
                print(f"ERROR {sid}: {err or 'SCENARIO.md has no `- feature:` line'}")
                bad = True
                continue
            res = run_one(repo, sid, known, tmp)
            if not_here(res):
                print(f"N/A {sid}: {res['reason']}")
                na += 1
            elif str(res.get("reason")).startswith(MANY):
                print(f"ERROR {sid}: {res['reason']}")
                bad = True
            elif res.get("reason"):
                print(f"SEEDED ✓ {sid}: fails on the repo as it is")
            else:
                print(f"CHECKS NOTHING YET {sid}: passes on the repo as it is")
                flagged += 1
    return 2 if bad else 1 if flagged else 4 if na else 0


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
    ran = [r for r in res.get("scenarios") or [] if isinstance(r, dict)]
    failed = [r for r in ran if r.get("reason")]
    # every failure is what this host lacks: the Stop gate takes a blocked report naming it. Said only of a full run
    # on the files as they are: else the scenarios that did run prove nothing about them now
    env_only = res.get("verdict") != "PASS" and failed and not res.get("reason") and all(not_here(r) for r in failed)
    fresh = not res.get("filter") and res.get("tree") == tree_hash(repo)
    rc = 1
    if res.get("verdict") != "PASS" and not env_only:
        print("last run FAIL")
    elif res.get("filter"):
        print(f"partial run: only '{res['filter']}' was run; run all scenarios")
    elif not fresh:
        print("stale: tree changed since run")
    elif env_only:
        print("cannot run here: " + "; ".join(f"{r.get('id')}: {r['reason']}" for r in failed))
    else:
        rc = 0
    line = features_line(ran, valid=not res.get("reason"))
    if line and fresh:  # after the verdict line, which the Stop gate reads first
        print(line)
    return rc


def usage():
    print("usage: scenarios.py [--repo DIR] run [ID]|tree-hash|check|can-fail REF|seeded ID", file=sys.stderr)
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
    cmds = {"run": cmd_run, "tree-hash": cmd_hash, "check": cmd_check, "can-fail": cmd_can_fail, "seeded": cmd_seeded}
    if not a or a[0] not in cmds:
        usage()
    sys.exit(cmds[a[0]](repo, *a[1:2]) if a[0] in ("run", "can-fail", "seeded") else cmds[a[0]](repo))


if __name__ == "__main__":
    main()
