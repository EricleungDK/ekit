#!/usr/bin/env python3
"""orch-status: is an agent's worktree stuck? One call, for one or more worktrees (#38).

usage: python3 -I scripts/orch-status.py <worktree>...

Per worktree: the branch; commits ahead of the pushed branch (its upstream, else origin/<branch>; never pushed: ahead
of origin/main); the last commit's age and subject; dirty files; live test and mutation processes (pytest, unittest,
mutmut, tests/run.sh, scenarios.py, mech-review.py, r3-local.py, verify-wsl, cargo test/mutants, stryker, vitest, jest)
whose cwd is in the worktree or whose command names it; CI check counts of the branch's PR (`gh pr checks`).
Processes come from /proc, else powershell on Windows, else `ps`; with none of them the line says so. git and gh run
in each worktree. exit: 0; 2 when a path is not a git worktree (the others are still reported).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

TEST_PROC = re.compile(r"pytest|unittest|mutmut|tests/run\.sh|scenarios\.py|mech-review\.py|r3-local\.py|verify-wsl"
                       r"|cargo[ -](?:test|mutants)|stryker|vitest|jest")
BUCKETS = ("pass", "fail", "pending", "skipping", "cancel")
CMD_MAX = 120
DIRTY_MAX = 5


def run_cmd(argv, env=None, cwd=None):
    try:
        p = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        return 127, "", f"{argv[0]}: {e}\n"
    return p.returncode, p.stdout, p.stderr


def age(seconds):
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h{s % 3600 // 60}m"


def proc_list(root="/proc", ticks=None):
    """Processes from a /proc tree: pid, age, cwd (None when unreadable), command line."""
    if ticks is None:
        ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    with open(os.path.join(root, "uptime")) as f:
        uptime = float(f.read().split()[0])
    out = []
    for name in os.listdir(root):
        if not name.isdigit():
            continue
        d = os.path.join(root, name)
        try:
            with open(os.path.join(d, "cmdline"), "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            with open(os.path.join(d, "stat")) as f:
                start = int(f.read().rsplit(")", 1)[1].split()[19]) / ticks
        except (OSError, ValueError, IndexError):
            continue  # gone, or not ours to read
        try:
            cwd = os.readlink(os.path.join(d, "cwd"))
        except OSError:
            cwd = None
        if cmd:
            out.append({"pid": int(name), "age": age(uptime - start), "cwd": cwd, "cmd": cmd})
    return out


def ps_list(run):
    rc, text, _ = run(["ps", "-axo", "pid=,etime=,command="])
    if rc != 0:
        return f"unavailable (ps exit {rc})"
    out = []
    for line in text.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            out.append({"pid": int(parts[0]), "age": parts[1], "cwd": None, "cmd": parts[2]})
    return out


def win_list(run):
    rc, text, _ = run(["powershell", "-NoProfile", "-Command",
                       "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"])
    if rc != 0:
        return f"unavailable (powershell exit {rc})"
    items = json.loads(text or "[]")
    items = [items] if isinstance(items, dict) else items
    return [{"pid": p["ProcessId"], "age": None, "cwd": None, "cmd": p["CommandLine"]} for p in items if p["CommandLine"]]


def processes(run, proc_root="/proc", which=shutil.which, os_name=os.name):
    """The host's process list, or a note why there is none (never an exception: Windows has no /proc and may lack ps)."""
    if os.path.exists(os.path.join(proc_root, "uptime")):
        return proc_list(proc_root)
    if os_name == "nt":  # before ps: Git Bash's ps takes no -o
        return win_list(run)
    if which("ps"):
        return ps_list(run)
    return "unavailable on this host (no /proc, ps or powershell)"


def _mine(p, wt):
    cwd = p["cwd"]
    if cwd and (cwd == wt or cwd.startswith(wt.rstrip(os.sep) + os.sep)):
        return True
    return re.search(r"(?<![\w.-])" + re.escape(os.path.basename(wt)) + r"(?![\w.-])", p["cmd"]) is not None


def _cut(cmd):
    return cmd if len(cmd) <= CMD_MAX else cmd[:CMD_MAX - 3] + "..."


def report(run, procs, wt):
    """Lines for one worktree, and whether it is one."""
    def git(*args):
        rc, out, err = run(["git", "-C", wt, *args])
        return rc, out.rstrip("\n"), err.strip()

    rc, branch, err = git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return [f"{wt}: not a git worktree ({err})"], False
    lines = [f"{wt} [{branch}]"]
    rc, up, _ = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if rc != 0:
        up = f"origin/{branch}"
        rc, _, _ = git("rev-parse", "--verify", "--quiet", f"refs/remotes/{up}")
    if rc == 0:
        _, n, _ = git("rev-list", "--count", f"{up}..HEAD")
        lines.append(f"  commits: {n} ahead of {up}" + (" (all pushed)" if n == "0" else ""))
    elif git("rev-parse", "--verify", "--quiet", "refs/remotes/origin/main")[0] == 0:
        _, n, _ = git("rev-list", "--count", "origin/main..HEAD")
        lines.append(f"  commits: not pushed; {n} ahead of origin/main")
    else:
        lines.append("  commits: not pushed (no origin/main)")
    _, last, _ = git("log", "-1", "--format=%cr: %s")
    lines.append(f"  last commit: {last}")
    _, dirty, _ = git("status", "--porcelain", "--untracked-files=all")
    files = [x[3:] for x in dirty.splitlines() if x.strip()]
    if files:
        more = f" (+{len(files) - DIRTY_MAX} more)" if len(files) > DIRTY_MAX else ""
        lines.append(f"  dirty: {len(files)} file(s): {', '.join(files[:DIRTY_MAX])}{more}")
    else:
        lines.append("  dirty: none")
    if isinstance(procs, str):
        lines.append(f"  processes: {procs}")
    else:
        live = [p for p in procs if p["pid"] != os.getpid() and TEST_PROC.search(p["cmd"]) and _mine(p, wt)]
        lines.append(f"  processes: {len(live)} live" if live else "  processes: none")
        for p in live:
            lines.append(f"    pid {p['pid']}" + (f" ({p['age']})" if p["age"] else "") + f" {_cut(p['cmd'])}")
    rc, out, err = run(["gh", "pr", "checks", branch, "--json", "name,state,bucket"], cwd=wt)
    if rc in (0, 8) and out.strip():  # 8: some checks pending
        counts = {}
        for c in json.loads(out):
            counts[c["bucket"]] = counts.get(c["bucket"], 0) + 1
        ci = ", ".join(f"{counts[b]} {b}" for b in BUCKETS if b in counts)
        lines.append(f"  CI: {ci or 'no checks yet'}")
    else:
        lines.append(f"  CI: no PR ({err.strip()})")
    return lines, True


def main(argv, run=run_cmd, procs=None):
    p = argparse.ArgumentParser(prog="orch-status.py", description="is an agent's worktree stuck? (#38)")
    p.add_argument("worktrees", nargs="+", metavar="WORKTREE")
    a = p.parse_args(argv)
    plist = procs() if procs else processes(run)
    rc = 0
    for wt in a.worktrees:
        lines, ok = report(run, plist, os.path.abspath(wt))
        rc = rc if ok else 2
        print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
