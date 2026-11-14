#!/usr/bin/env python3
"""Task verification: a task whose description carries a `Verify: \\`<command>\\`` line completes only after that
command passed on the files as they are now.

`task-verify.py [--repo DIR] run -- CMD...` runs CMD in the repo root and records its exit code with the tree hash.
The agent runs it, through the Bash tool, so the command passes the session's permission rules and sandbox.

`task-verify.py --hook` (stdin: hook payload) is the TaskCreated and TaskCompleted hook. It runs nothing but git:
- TaskCreated: the task's Verify command is kept for the session. An edit of the description later does not change
  what the task is checked with.
- TaskCompleted: allowed when a recorded run of that command exited 0 and the tree it ran on is unchanged; otherwise
  exit 2, and the reason goes to the agent on stderr. A task without a Verify line is never gated.

Records sit in the repo's common git dir (<git dir>/ekit/verify.json, or $EKIT_STATE/verify/<repo key>/), so a run in a
linked worktree is seen from the main checkout. Each record names its worktree: a pass counts while that worktree's
files are the ones the command ran on. The tree hash is the scenario runner's: a commit alone changes nothing.

A teammate's turn end fires TaskCompleted too (agent teams). There the block is given once per tree and reason:
a block on every try would hold the turn open for good.
"""
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I drops the script dir from sys.path

import scenarios  # noqa: E402 - the sys.path line above has to run first

STATE = os.environ.get("EKIT_STATE") or os.environ.get("EK_STATE") or os.path.join(
    os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.cache/ekit"), "state"
)
LINE = re.compile(r"^[ \t]*(?:[-*][ \t]+)?\**verify:\**[ \t]*(\S.*?)[ \t]*$", re.I | re.M)
QUOTED = re.compile(r"`([^`]*)`")  # the whole value in one pair of backticks


def declared(description):
    """The command of the first `Verify:` line, whitespace collapsed; None when the text has no such line."""
    m = LINE.search(str(description))
    if not m:
        return None
    cmd = m.group(1)
    quoted = QUOTED.fullmatch(cmd)
    if quoted:
        cmd = quoted.group(1)
    return " ".join(cmd.split()) or None


def git(repo, *args):
    """stdout of a git query; empty when git fails (not a repo)."""
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout.strip()


def tree(top):
    """The tree hash of the worktree at `top`: empty when the worktree is gone, None when it cannot be hashed."""
    try:
        return scenarios.tree_hash(top)
    except SystemExit:
        return None


def records_path(top):
    common = os.path.realpath(os.path.join(top, git(top, "rev-parse", "--git-common-dir")))
    state = scenarios.env("STATE")
    if state:
        return os.path.join(state, "verify", hashlib.sha1(common.encode()).hexdigest(), "verify.json")
    return os.path.join(common, "ekit", "verify.json")


def load(path):
    """The recorded runs: one per worktree and command. Anything else in the file reads as no runs."""
    try:
        with open(path) as f:
            recs = json.load(f)
    except (OSError, ValueError):
        return []
    return recs if isinstance(recs, list) else []


def record(top, cmd, rc):
    """Replaces this worktree's earlier run of `cmd`."""
    path = records_path(top)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    recs = [r for r in load(path) if (r["top"], r["cmd"]) != (top, cmd)]
    recs.append({"cmd": cmd, "top": top, "tree": tree(top), "rc": rc})
    tmp = f"{path}.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(recs, f)
    os.replace(tmp, path)


def cmd_run(repo, words):
    top = git(repo, "rev-parse", "--show-toplevel")
    if not top:
        print(f"task-verify: not a git repo: {repo}", file=sys.stderr)
        return 2
    cmd = words[0] if len(words) == 1 else shlex.join(words)
    rc = subprocess.run(cmd, shell=True, cwd=top).returncode
    record(top, " ".join(cmd.split()), rc)  # hashed after the run: what the command left is what the hook will see
    print(f"task-verify: `{cmd}` exited {rc}", file=sys.stderr)
    return rc


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def write(path, text):
    os.makedirs(STATE, exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def why_not(top, cmd):
    """None when a recorded run of `cmd` passed on files that are still the same; else what is missing."""
    runs = [r for r in load(records_path(top)) if r["cmd"] == cmd]
    if not runs:
        return "no run recorded"
    passed = [r for r in runs if r["rc"] == 0]
    if any(r["tree"] and tree(r["top"]) == r["tree"] for r in passed):
        return None
    if not passed:
        return f"the run exited {runs[-1]['rc']}"
    return "the files changed since the passing run"


def hook():
    data = json.load(sys.stdin)
    session, task = data.get("session_id"), hashlib.sha1(str(data.get("task_id")).encode()).hexdigest()
    now = declared(data.get("task_description"))
    kept = os.path.join(STATE, f"{session}.task-{task}")
    if data.get("hook_event_name") == "TaskCreated":
        if now:
            write(kept, now)
        return 0
    cmd = read(kept) or now
    if not cmd:
        return 0
    top = git(data.get("cwd") or os.getcwd(), "rev-parse", "--show-toplevel")
    if not top:
        return 0
    why = why_not(top, cmd)
    if why is None:
        return 0
    if data.get("teammate_name"):
        seen, mark = os.path.join(STATE, f"{session}.taskblock-{task}"), f"{tree(top)} {why}"
        if read(seen) == mark:
            return 0
        write(seen, mark)
    print(f"[ekit] Task \"{data.get('task_subject')}\" is not verified for the current files: {why}. "
          f"Run `python3 {os.path.abspath(__file__)} run -- {cmd}` in the checkout that holds the work, fix what it "
          "shows, and mark the task completed once it exits 0. The command is the one the task was created with: "
          "a different one is the user's call. It cannot pass here → leave the task open and report it blocked "
          "(finish skill).", file=sys.stderr)
    return 2


USAGE = "usage: task-verify.py [--repo DIR] run -- CMD... | task-verify.py --hook"


def main():
    a = sys.argv[1:]
    if a == ["--hook"]:
        return hook()
    repo = os.getcwd()
    try:
        if a[0] == "--repo":
            repo, a = os.path.abspath(a[1]), a[2:]
        if a[0] != "run" or a[1] != "--" or not any(w.strip() for w in a[2:]):
            raise IndexError
    except IndexError:  # a word is missing, or is not the one the usage line names
        print(USAGE, file=sys.stderr)
        return 2
    return cmd_run(repo, a[2:])


if __name__ == "__main__":
    sys.exit(main())
