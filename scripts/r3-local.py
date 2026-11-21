#!/usr/bin/env python3
"""r3-local: the workflow's R3 jobs on this machine, before the review request (#35).

usage: python3 -I scripts/r3-local.py --base REF [--head REF] --stack {python,rust,ts} [--repo DIR]
           [--test-paths GLOB ...] [--mutation-budget MIN] [--max-mutants N] [--project-dir DIR] [--env-dir DIR]

Steps, as .github/workflows/mech-review.yml runs them: set up the stack's R3 tool with the workflow's pins (the adapter's
r3_tool: python a venv with pytest and mutmut, ts Stryker in its own npm prefix, rust cargo-mutants), then the engine's
plan, baseline (shard count, per-mutant timeout), every shard at the same time with the CI budget each, and the merge.
Prints the merged summary, R3's status, each shard's note and the fail entries; the merged JSON is written beside the
shard results. Pass the inputs your caller workflow sets (ekit: --test-paths 'tests/**' --test-paths
'.ekit/scenarios/**' --mutation-budget 20). The run tests the head commit: uncommitted changes are not in it.
--env-dir keeps the tool and the results (reused while the pins match); default: a temp dir, removed after the run.
exit: 0 no fail entry; 1 a fail entry; 2 setup failed, usage, git error, or a step produced no result.
"""
import argparse
import concurrent.futures
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir from sys.path

from mech_review.stack import ADAPTERS  # noqa: E402

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mech-review.py")
MARKER = ".ekit-r3-env.json"  # the pins an env dir was set up with


class Stop(Exception):
    pass


def run_cmd(argv, env=None, cwd=None):
    """(exit code, stdout, stderr) of one command; a missing executable is 127, as a shell reports it."""
    try:
        p = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        return 127, "", f"{argv[0]}: {e}\n"
    return p.returncode, p.stdout, p.stderr


def _setup_steps(tool, envdir, project):
    """[(argv, None)] install commands, the dir to put first on PATH (or None), and the mutants cmd (or None)."""
    if tool.kind == "venv":
        venv = os.path.join(envdir, "venv")
        py = os.path.join(venv, "bin", "python")
        steps = [["python3", "-m", "venv", venv], [py, "-m", "pip", "install", "--quiet", *tool.packages]]
        steps += [[py, "-m", "pip", "install", "--quiet", "-r", f]
                  for f in sorted(glob.glob(os.path.join(project, "requirements*.txt")))]
        return steps, os.path.join(venv, "bin"), None
    if tool.kind == "npm":
        prefix = os.path.join(envdir, "stryker")
        steps = [["npm", "install", "--prefix", prefix, "--no-audit", "--no-fund", "--legacy-peer-deps", *tool.packages]]
        return steps, None, os.path.join(prefix, *tool.mutants_cmd.split("/"))
    root = os.path.join(envdir, "cargo")
    steps = [["cargo", "install", "--locked", "--root", root, *p.split("@")[:1], "--version", p.split("@")[1]]
             for p in tool.packages]
    return steps, os.path.join(root, "bin"), None


def setup(run, tool, envdir, project):
    """Install the tool unless envdir already holds these pins. Returns (env for the engine, mutants cmd or None)."""
    steps, bindir, mutants_cmd = _setup_steps(tool, envdir, project)
    want = {"kind": tool.kind, "packages": list(tool.packages)}
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
        for argv in steps:
            rc, _, err = run(argv)
            if rc != 0:
                raise Stop(f"setup failed: {' '.join(argv)} (exit {rc})\n{err.rstrip()}")
        with open(marker, "w") as f:
            json.dump(want, f)
    env = dict(os.environ, **tool.env)
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


def _shard_line(k, n, shard):
    c = shard["checks"]["R3"]
    wall = (c.get("timing") or {}).get("wall_s")
    return f"shard {k}/{n}: {c['note']}" + (f" (wall {wall} s)" if wall is not None else "")


def _r3_line(c):
    if c.get("tested") is None:
        return f"R3 {c['status']}"
    total = "?" if c.get("total") is None else c["total"]
    return f"R3 {c['status']} ({c['tested']}/{total} tested)"


def r3(run, a):
    adapter = ADAPTERS.get(a.stack)
    tool = adapter.r3_tool if adapter else None
    if tool is None:
        raise Stop(f"no R3 tool for stack {a.stack} (built-in stacks: {', '.join(sorted(ADAPTERS))})")
    repo = os.path.abspath(a.repo)
    base, head = _sha(run, repo, a.base), _sha(run, repo, a.head)
    _, dirty, _ = run(["git", "-C", repo, "status", "--porcelain"])
    if dirty.strip():
        print(f"r3-local: uncommitted changes are not in the run (it tests {head})", file=sys.stderr)
    env, mutants_cmd = setup(run, tool, a.env_dir, os.path.normpath(os.path.join(repo, a.project_dir)))
    common = ["--repo", repo, "--base", base, "--head", head, "--stack", a.stack]
    tp = [x for g in a.test_paths for x in ("--test-paths", g)]
    knobs = ["--mutation-budget", a.mutation_budget, "--max-mutants", a.max_mutants, "--project-dir", a.project_dir]
    out = os.path.join(a.env_dir, "out")
    os.makedirs(out, exist_ok=True)

    rc, text, err = _engine(run, env, "plan", common + tp)
    if rc != 0:
        raise Stop(f"plan exit {rc}: no result\n{err.rstrip()}")
    if not json.loads(text)["run"]:
        print("R3 not run: no production file changed in scope (plan)")
        return 0
    rc, text, err = _engine(run, env, "baseline", common + knobs + ["--shards", "4"] + tp)
    if rc > 1:
        raise Stop(f"baseline exit {rc}: no result\n{err.rstrip()}")
    base_file = os.path.join(out, "mech-review-baseline.json")
    with open(base_file, "w") as f:
        f.write(text)
    b = json.loads(text)
    n = b["count"] if b["run"] else 0
    extra = [] if b["timeout"] is None else ["--mutant-timeout", str(b["timeout"])]
    extra += ["--mutants-cmd", mutants_cmd] if mutants_cmd else []

    def shard(k):
        return _engine(run, env, "mutants", common + ["--shard", f"{k}/{n}"] + knobs + extra + tp)

    envelopes, lines = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(n, 1)) as pool:
        results = list(pool.map(shard, range(n)))
    for k, (rc, text, err) in enumerate(results):
        if rc > 1:
            lines.append(f"shard {k}/{n}: no result (exit {rc})")
            print(f"r3-local: shard {k}/{n} exit {rc}\n{err.rstrip()}", file=sys.stderr)
            continue
        path = os.path.join(out, f"mech-review-mutants-{k}.json")
        with open(path, "w") as f:
            f.write(text)
        envelopes += ["--envelope", f"{k}={path}"]
        lines.append(_shard_line(k, n, json.loads(text)))
    rc, text, err = _engine(run, env, "merge", common + ["--shards", str(n), "--baseline", base_file] + envelopes)
    if rc > 1:
        raise Stop(f"merge exit {rc}: no result\n{err.rstrip()}")
    merged_file = os.path.join(out, "mech-review-mutants-merged.json")
    with open(merged_file, "w") as f:
        f.write(text)
    m = json.loads(text)
    c = m["checks"]["R3"]
    print(m["summary"])
    print(_r3_line(c) if n else f"R3 {c['status']}: {c['note']}")
    for line in lines:
        print(line)
    for e in m["entries"]:
        if e["severity"] == "fail":
            print(f"fail {e['id']} {e['file']}:{e['line']} {e['problem']}")
    print(f"merged: {merged_file}")
    return rc


def parse(argv):
    p = argparse.ArgumentParser(prog="r3-local.py", description="the workflow's R3 jobs, locally (#35)")
    p.add_argument("--repo", default=".", help="git repo (default .)")
    p.add_argument("--base", required=True, help="base ref (the PR's base: origin/main)")
    p.add_argument("--head", default="HEAD", help="head ref (default HEAD)")
    p.add_argument("--stack", required=True, help="python, rust or ts")
    p.add_argument("--test-paths", action="append", default=[], metavar="GLOB", help="test file glob, repeatable")
    p.add_argument("--mutation-budget", default="10", metavar="MIN", help="minutes per shard (workflow default 10)")
    p.add_argument("--max-mutants", default="40", metavar="N", help="R3 cap (workflow default 40)")
    p.add_argument("--project-dir", default=".", metavar="DIR", help="project dir under the repo (default .)")
    p.add_argument("--env-dir", metavar="DIR", help="keep the tool and results here (reused); default: temp dir")
    return p.parse_args(argv)


def main(argv, run=run_cmd):
    a = parse(argv)
    tmp = None
    if not a.env_dir:
        tmp = a.env_dir = tempfile.mkdtemp(prefix="ekit-r3-")
    try:
        return r3(run, a)
    except Stop as e:
        print(f"r3-local: {e}", file=sys.stderr)
        return 2
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
