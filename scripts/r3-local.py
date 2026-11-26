#!/usr/bin/env python3
"""r3-local: the workflow's R3 jobs on this machine, before the review request (#35). POSIX only (on Windows: WSL).

usage: python3 -I scripts/r3-local.py --base REF [--head REF] --stack {python,rust,ts} [--repo DIR]
           [--test-paths GLOB ...] [--mutation-budget MIN] [--max-mutants N] [--mutant-timeout SEC]
           [--project-dir DIR] [--env-dir DIR] [--wait-limit MIN]

Steps, as .github/workflows/mech-review.yml runs them: set up the stack's R3 tool with the workflow's pins (the adapter's
r3_tool: python a venv with pytest and mutmut plus the project dir's requirements*.txt at head, ts Stryker in its own
npm prefix, rust cargo-mutants), then the engine's plan, baseline (shard count, per-mutant timeout), every shard at the
same time with the CI budget each, and the merge. Prints the merged summary, R3's status, each shard's note, the fail
entries and the unconfirmed survivors (#79: a mutant mutmut reports surviving whose whole-suite retry the budget did
not reach; a missed mutant until a test kills it). Defaults are the workflow's (test-paths tests/**, budget 10,
max-mutants 40); pass your caller's inputs (ekit: --test-paths 'tests/**' --test-paths '.ekit/scenarios/**'
--mutation-budget 20). The run tests the head commit: uncommitted changes are not in it. The shards share this
machine's CPUs (CI gives each its own runner), so wall times and mutmut's own timeouts can differ from CI's. setup-command and extra-apt-packages are not run.
--env-dir keeps the tool and the results (reused while the pins and requirements match); default: a temp dir, removed.
One run at a time on this machine (#120): a second run, any user's and any env dir's, waits for the first, naming its
pid, up to --wait-limit minutes (default 90), then stops with exit 3; the lock file is /tmp/ekit-r3-local.lock.
One run at a time holds an env dir: a second run on it stops at once, naming the first's pid, without waiting for the
machine. Both locks go when the run that holds them ends, killed or not.
exit: 0 no fail entry and no unconfirmed survivor; 1 a fail entry or an unconfirmed survivor; 2 setup failed,
usage, the env dir in use by another run, git error, a step produced no usable result, or Windows; 3 waited past
--wait-limit for another run on this machine (R3 not run).
"""
import argparse
import concurrent.futures
import errno
import fnmatch
import hashlib
import inspect
import json
import os
import posixpath
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

try:
    import fcntl
except ImportError:  # Windows: main stops before the lock (POSIX only)
    fcntl = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir from sys.path

from mech_review.mutants import is_unconfirmed  # noqa: E402 - imported after the sys.path line above
from mech_review.stack import ADAPTERS  # noqa: E402 - imported after the sys.path line above, like the one before it

EXIT = __doc__[__doc__.index("exit: "):].strip()  # the exit codes above, also in --help

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mech-review.py")
MARKER = ".ekit-r3-env.json"  # the pins and requirements an env dir was set up with
LOCK = ".ekit-r3-env.lock"  # held (flock) by the run using the env dir; holds that run's pid
# held (flock) by the one run on this machine; holds its pid. /tmp, not $TMPDIR (per user on macOS): every user's runs
MACHINE_LOCK = "/tmp/ekit-r3-local.lock"
POLL_S = 0.1  # how often a waiting run tries the machine lock again
# what this python's tarfile offers, read once (tests patch these, never tarfile: 3.14 reads its own globals)
HAS_DATA_FILTER = hasattr(tarfile, "data_filter")
EXTRACT_TAKES_FILTER = "filter" in inspect.signature(tarfile.TarFile.extract).parameters
DROP_ENV = ("PYTHONPATH", "PYTEST_ADDOPTS")  # a developer's shell settings CI does not have


class Stop(Exception):
    code = 2


class Waited(Stop):
    code = 3


def run_cmd(argv, env=None, cwd=None):
    """(exit code, stdout, stderr) of one command; a missing executable is 127, as a shell reports it."""
    try:
        p = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        return 127, "", f"{argv[0]}: {e}\n"
    return p.returncode, p.stdout, p.stderr


def _left_out(m, root):
    """Why this tar member is not extracted under root ("name (reason)"), or None. The rules of tarfile's data filter,
    which python < 3.12 may lack: nothing is written outside root, no link points outside it or to an absolute path."""
    def outside(path):
        return os.path.commonpath([root, os.path.realpath(path)]) != root

    path = os.path.join(root, m.name)
    if outside(path):
        return f"{m.name} (outside the checkout)"
    if m.issym():
        if os.path.isabs(m.linkname) or outside(os.path.join(os.path.dirname(path), m.linkname)):
            return f"{m.name} -> {m.linkname} (outside the checkout)"
        return None
    return None if m.isreg() or m.isdir() else f"{m.name} (not a file, dir or link)"


def requirements(run, repo, head, project_dir, envdir):
    """A checkout of the tree at head under envdir/head (git archive: the repo is not touched), and the project dir's
    requirements*.txt in it: (project dir in the checkout, [(name, sha256)] sorted by name). pip runs in that dir, as
    CI runs it in caller/$PROJECT_DIR, so `-c x.txt`, `-r ../y.txt` and `-e .` resolve as there. A link that points
    out of the checkout (CI keeps it and never follows it) is not extracted and is named on stderr."""
    tar = os.path.join(envdir, "head.tar")
    os.makedirs(envdir, exist_ok=True)
    rc, _, err = run(["git", "-C", repo, "archive", "--format=tar", "-o", tar, head])
    if rc != 0:
        raise Stop(f"git archive: {err.strip()}")
    src = os.path.join(envdir, "head")
    shutil.rmtree(src, ignore_errors=True)
    root = os.path.realpath(src)
    try:
        with tarfile.open(tar) as t:
            for m in t.getmembers():
                why = _left_out(m, root)
                if why:
                    print(f"r3-local: head checkout: left out {why}", file=sys.stderr)
                elif HAS_DATA_FILTER:  # a member the check above let through stops the run here
                    t.extract(m, root, filter="data")
                elif EXTRACT_TAKES_FILTER:  # _left_out did the data filter's work; never reach tarfile's own default
                    t.extract(m, root, filter="fully_trusted")
                else:  # python < 3.12 without the filter backport
                    t.extract(m, root)
    except tarfile.TarError as e:
        raise Stop(f"head checkout: no usable archive ({type(e).__name__}: {e})")
    os.remove(tar)
    proj = os.path.normpath(os.path.join(src, project_dir))
    got = []
    for name in sorted(n for n in os.listdir(proj) if fnmatch.fnmatch(n, "requirements*.txt")) if os.path.isdir(proj) else []:
        with open(os.path.join(proj, name), "rb") as f:
            got.append((name, hashlib.sha256(f.read()).hexdigest()))
    return proj, got


def hold(envdir):
    """Lock envdir for this run: the open lock file, which holds this pid. flock goes with the process, so a killed
    run leaves no lock behind. Another live run's lock is a Stop naming its pid."""
    os.makedirs(envdir, exist_ok=True)
    f = open(os.path.join(envdir, LOCK), "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        pid = f.read().strip() or "?"
        f.close()
        raise Stop(f"{envdir} is in use by another r3-local run (pid {pid}): wait for it, or pass another --env-dir")
    f.truncate(0)
    f.write(str(os.getpid()))
    f.flush()
    return f


def _refused(path, why):
    return Stop(f"machine lock {path}: {why}: remove it, or ask its owner")


def _open_fd(path, flags, mode=0o666):
    """os.open that never follows a link at path: a link there (any user can make one in /tmp) is a Stop, as is any
    other error but a missing file (FileNotFoundError) or, for an existing file, the right to write it."""
    try:
        return os.open(path, flags | os.O_NOFOLLOW, mode)
    except (FileNotFoundError, FileExistsError):
        raise
    except PermissionError:
        if flags & os.O_RDWR:
            raise
        raise _refused(path, "cannot open it (Permission denied)")
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise _refused(path, "a symlink")
        if e.errno == errno.EISDIR:
            raise _refused(path, "not a regular file")
        raise _refused(path, f"cannot open it ({e.strerror})")


def _open_shared(path):
    """The machine lock file, open to write when this user may, else to read (flock works on either). The first run
    makes it writable by every user; an existing one is opened without O_CREAT, which a sticky /tmp refuses on another
    user's file. Never through a link, and only a regular file with no other hard link: the run writes its pid in it.
    Anything else is a Stop naming why."""
    for _ in range(3):  # a file that keeps going and coming back between the two opens
        mode = "r+"
        try:
            fd = _open_fd(path, os.O_RDWR)
        except FileNotFoundError:
            try:
                fd = _open_fd(path, os.O_RDWR | os.O_CREAT | os.O_EXCL)
            except FileExistsError:  # another run made it first
                continue
            except OSError as e:
                raise _refused(path, f"cannot make it ({e.strerror})")
            os.fchmod(fd, 0o666)  # past the umask
        except PermissionError:
            try:
                fd, mode = _open_fd(path, os.O_RDONLY), "r"
            except FileNotFoundError:  # gone in between
                continue
        st = os.fstat(fd)
        why = None if stat.S_ISREG(st.st_mode) else "not a regular file"
        why = why or (None if st.st_nlink == 1 else "a file with another hard link")
        if why:
            os.close(fd)
            raise _refused(path, why)
        return os.fdopen(fd, mode)
    raise _refused(path, "it keeps going and coming back")


def _holder(f):
    f.seek(0)
    pid = f.read(32).strip()
    return pid if pid.isdigit() else "?"


def hold_machine(path, limit_min):
    """Lock this machine for this run: the open lock file. While another run holds it, wait, naming that run's pid,
    up to limit_min minutes, then a Stop. flock goes with the process, so a killed run frees it."""
    f = _open_shared(path)
    deadline = time.monotonic() + limit_min * 60
    said = None
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            pid = _holder(f)
            if pid != said:
                print(f"r3-local: waiting for the r3-local run of pid {pid} (one run at a time on this machine: "
                      f"{path}), up to {limit_min:g} min", file=sys.stderr, flush=True)
                said = pid
            left = deadline - time.monotonic()
            if left <= 0:
                f.close()
                raise Waited(f"waited {limit_min:g} min for the r3-local run of pid {pid}: R3 not run; run it again "
                             "when that run ends, or pass a larger --wait-limit")
            time.sleep(min(POLL_S, left))
    if f.writable():
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()))
        f.flush()
    return f


def _setup_steps(tool, envdir, proj, reqs):
    """The install commands [(argv, cwd)], the dir to put first on PATH (or None), and the mutants cmd (or None)."""
    if tool.kind == "venv":
        venv = os.path.join(envdir, "venv")
        py = os.path.join(venv, "bin", "python")
        steps = [(["python3", "-m", "venv", venv], None), ([py, "-m", "pip", "install", "--quiet", *tool.packages], None)]
        steps += [([py, "-m", "pip", "install", "--quiet", "-r", name], proj) for name, _ in reqs]
        return steps, os.path.join(venv, "bin"), None
    if tool.kind == "npm":
        prefix = os.path.join(envdir, "stryker")
        steps = [(["npm", "install", "--prefix", prefix, "--no-audit", "--no-fund", "--legacy-peer-deps",
                   *tool.packages], None)]
        return steps, None, os.path.join(prefix, *tool.mutants_cmd.split("/"))
    root = os.path.join(envdir, "cargo")
    steps = [(["cargo", "install", "--locked", "--root", root, *p.split("@")[:1], "--version", p.split("@")[1]], None)
             for p in tool.packages]
    return steps, os.path.join(root, "bin"), None


def setup(run, tool, envdir, proj, reqs):
    """Install the tool unless envdir already holds these pins and requirements. Returns (engine env, mutants cmd)."""
    steps, bindir, mutants_cmd = _setup_steps(tool, envdir, proj, reqs)
    want = {"kind": tool.kind, "packages": list(tool.packages), "requirements": dict(reqs)}
    marker = os.path.join(envdir, MARKER)
    try:
        with open(marker) as f:
            ready = json.load(f) == want
    except (OSError, ValueError):
        ready = False
    if ready:
        print(f"r3-local: env ready in {envdir}")
    else:
        os.makedirs(envdir, exist_ok=True)
        for argv, cwd in steps:
            rc, _, err = run(argv, cwd=cwd)
            if rc != 0:
                raise Stop(f"setup failed: {' '.join(argv)} (exit {rc})\n{err.rstrip()}")
        with open(marker, "w") as f:
            json.dump(want, f)
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    env.update(tool.env)
    if bindir:
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    return env, mutants_cmd


def _sha(run, repo, ref):
    rc, out, err = run(["git", "-C", repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"])
    if rc != 0:
        raise Stop(f"{ref}: {err.strip()}")
    return out.strip()


def _engine(run, env, sub, args):
    return run(["python3", "-I", ENGINE, sub, *args], env)


def _parse(text, what, keys):
    """The step's JSON with these keys (a dotted key reaches into a table), or Stop."""
    try:
        d = json.loads(text)
        for k in keys:
            v = d
            for part in k.split("."):
                v = v[part]
    except (ValueError, KeyError, TypeError) as e:
        raise Stop(f"{what}: no usable result ({type(e).__name__}: {e})")
    return d


def _shard_line(k, n, text):
    try:
        c = json.loads(text)["checks"]["R3"]
        note = c["note"]
    except (ValueError, KeyError, TypeError):
        return None
    wall = (c.get("timing") or {}).get("wall_s")
    return f"shard {k}/{n}: {note}" + (f" (wall {wall} s)" if wall is not None else "")


def _r3_line(c):
    if c.get("tested") is None:
        return f"R3 {c['status']}"
    total = "?" if c.get("total") is None else c["total"]
    return f"R3 {c['status']} ({c['tested']}/{total} tested)"


def r3(run, a, keep):
    adapter = ADAPTERS.get(a.stack)
    tool = adapter.r3_tool if adapter else None
    if tool is None:
        raise Stop(f"no R3 tool for stack {a.stack} (built-in stacks: {', '.join(sorted(ADAPTERS))})")
    repo = os.path.abspath(a.repo)
    base, head = _sha(run, repo, a.base), _sha(run, repo, a.head)
    _, dirty, _ = run(["git", "-C", repo, "status", "--porcelain"])
    if dirty.strip():
        print(f"r3-local: uncommitted changes are not in the run (it tests {head})", file=sys.stderr)
    proj, reqs = requirements(run, repo, head, a.project_dir, a.env_dir) if tool.kind == "venv" else (None, [])
    env, mutants_cmd = setup(run, tool, a.env_dir, proj, reqs)
    test_paths = a.test_paths or ["tests/**"]  # the workflow's default input
    common = ["--repo", repo, "--base", base, "--head", head, "--stack", a.stack]
    tp = [x for g in test_paths for x in ("--test-paths", g)]
    knobs = ["--mutation-budget", a.mutation_budget, "--max-mutants", a.max_mutants, "--project-dir", a.project_dir]
    out = os.path.join(a.env_dir, "out")
    os.makedirs(out, exist_ok=True)

    rc, text, err = _engine(run, env, "plan", common + tp)
    if rc != 0:
        raise Stop(f"plan exit {rc}: no result\n{err.rstrip()}")
    if not _parse(text, "plan", ["run"])["run"]:
        print("R3 not run: no production file changed in scope (plan)")
        return 0
    rc, text, err = _engine(run, env, "baseline", common + knobs + ["--shards", "4"] + tp)
    if rc > 1:
        raise Stop(f"baseline exit {rc}: no result\n{err.rstrip()}")
    b = _parse(text, "baseline", ["run", "count", "timeout", "head", "checks.R3"])
    base_file = os.path.join(out, "mech-review-baseline.json")
    with open(base_file, "w") as f:
        f.write(text)
    n = b["count"] if b["run"] else 0
    timeout = a.mutant_timeout or ("" if b["timeout"] is None else str(b["timeout"]))  # input || baseline, as CI
    extra = ["--mutant-timeout", timeout] if timeout else []
    extra += ["--mutants-cmd", shlex.quote(mutants_cmd)] if mutants_cmd else []

    def shard(k):
        return _engine(run, env, "mutants", common + ["--shard", f"{k}/{n}"] + knobs + extra + tp)

    envelopes, lines = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(n, 1)) as pool:
        results = list(pool.map(shard, range(n)))
    for k, (rc, text, err) in enumerate(results):
        line = None if rc > 1 else _shard_line(k, n, text)
        if line is None:
            lines.append(f"shard {k}/{n}: no result (exit {rc})" if rc > 1 else f"shard {k}/{n}: no usable result")
            print(f"r3-local: shard {k}/{n} exit {rc}\n{err.rstrip()}", file=sys.stderr)
            continue
        path = os.path.join(out, f"mech-review-mutants-{k}.json")
        with open(path, "w") as f:
            f.write(text)
        envelopes += ["--envelope", f"{k}={path}"]
        lines.append(line)
    rc, text, err = _engine(run, env, "merge", common + ["--shards", str(n), "--baseline", base_file] + envelopes)
    if rc > 1:
        raise Stop(f"merge exit {rc}: no result\n{err.rstrip()}")
    m = _parse(text, "merge", ["summary", "entries", "checks.R3.status", "checks.R3.note"])
    merged_file = os.path.join(out, "mech-review-mutants-merged.json")
    with open(merged_file, "w") as f:
        f.write(text)
    c = m["checks"]["R3"]
    print(m["summary"])
    print(_r3_line(c) if n else f"R3 {c['status']}: {c['note']}")
    for line in lines:
        print(line)
    # a waived one (severity waived) is let through, as a waived fail is
    unconfirmed = [e for e in m["entries"] if e["severity"] == "confirm" and is_unconfirmed(e)]
    for e in m["entries"]:
        if e["severity"] == "fail":
            print(f"fail {e['id']} {e['file']}:{e['line']} {e['problem']}")
    for e in unconfirmed:
        print(f"unconfirmed {e['id']} {e['file']}:{e['line']} {e['problem']}")
    print(f"merged: {merged_file}" if keep else "merged: not kept (temp dir removed; pass --env-dir to keep it)")
    return 1 if unconfirmed else rc


def _minutes(text):
    """--wait-limit: a finite number of minutes, 0 or more (nan would wait for ever)."""
    try:
        v = float(text)
    except ValueError:
        v = -1.0
    if not 0 <= v < float("inf"):
        raise argparse.ArgumentTypeError("want minutes, a number 0 or more")
    return v


def parse(argv):
    p = argparse.ArgumentParser(prog="r3-local.py", description="the workflow's R3 jobs, locally (#35). POSIX only: "
                                "on Windows run it in WSL.", epilog=EXIT)
    p.add_argument("--repo", default=".", help="git repo (default .)")
    p.add_argument("--base", required=True, help="base ref (the PR's base: origin/main)")
    p.add_argument("--head", default="HEAD", help="head ref (default HEAD; a commit: uncommitted changes are not in it)")
    p.add_argument("--stack", required=True, help="python, rust or ts")
    p.add_argument("--test-paths", action="append", default=None, metavar="GLOB",
                   help="test file glob, repeatable (workflow default tests/**)")
    p.add_argument("--mutation-budget", default="10", metavar="MIN", help="minutes per shard (workflow default 10)")
    p.add_argument("--max-mutants", default="40", metavar="N", help="R3 cap (workflow default 40)")
    p.add_argument("--mutant-timeout", default="", metavar="SEC",
                   help="per-mutant timeout (workflow default: empty, the baseline's derived one)")
    p.add_argument("--project-dir", default=".", metavar="DIR", help="project dir under the repo (default .)")
    p.add_argument("--env-dir", metavar="DIR", help="keep the tool and results here (reused); default: temp dir")
    p.add_argument("--wait-limit", default=90.0, type=_minutes, metavar="MIN",
                   help="minutes to wait for another run on this machine (default 90)")
    a = p.parse_args(argv)
    a.project_dir = posixpath.normpath(a.project_dir)  # app/ and ./app are app, as the engine reads it
    return a


def main(argv, run=run_cmd, os_name=os.name, machine_lock=None):
    a = parse(argv)
    if os_name == "nt":
        print("r3-local: POSIX only (on Windows run it in WSL): the venv and the mutation tools need a POSIX host",
              file=sys.stderr)
        return 2
    keep = bool(a.env_dir)
    a.env_dir = os.path.abspath(a.env_dir) if keep else tempfile.mkdtemp(prefix="ekit-r3-")
    try:
        lock = hold(a.env_dir)
        try:
            machine = hold_machine(machine_lock or MACHINE_LOCK, a.wait_limit)
            try:
                return r3(run, a, keep)
            finally:
                machine.close()
        finally:
            lock.close()
    except Stop as e:
        print(f"r3-local: {e}", file=sys.stderr)
        return e.code
    finally:
        if not keep:
            shutil.rmtree(a.env_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
