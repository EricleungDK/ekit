#!/usr/bin/env python3
"""Task verification: work is checked with verify commands that were named before it was called done.

A verify command belongs to a session. It gets there in one of two ways:
- `task-verify.py [--repo DIR] declare -- CMD...`, run by the agent. The session is $CLAUDE_CODE_SESSION_ID, which
  Claude Code sets for Bash commands. This works in every session.
- a task whose description carries a line ``Verify: `<command>` ``, in a harness with a task list (the hook below).
A command stays once it is there: no call takes one away, and a task keeps the command it was first seen with.

`task-verify.py [--repo DIR] run -- CMD...` runs CMD in the repo root and records its exit code with the tree hash.
The agent runs it, through the Bash tool, so the command passes the session's permission rules and sandbox.

`task-verify.py --hook` (stdin: hook payload) is the TaskCreated and TaskCompleted hook. It runs nothing but git:
- TaskCreated: the task's Verify command becomes a command of the session.
- TaskCompleted: allowed when a recorded run of the task's command exited 0 and the tree it ran on is unchanged;
  otherwise exit 2, and the reason goes to the agent on stderr. A task without a Verify line is never gated.

`task-verify.py [--repo DIR] check SESSION` is the Stop gate's question at a `## Finish: done` report: did every
verify command of the session pass on the files as they are now? Exit 0 when so; else 1, with one line per command
that did not, or one line saying the session has none.

Commands and runs sit in the repo's common git dir (<git dir>/ekit/, or $EKIT_STATE/verify/<repo key>/): the hook
process and a sandboxed Bash command agree on that place, and a linked worktree shares it with the main checkout.
A sandbox that keeps the git dir read-only cannot write there: `declare` and `run` then exit 3 and say so, and the
same command outside the sandbox is the next step.
Each run names its worktree: a pass counts while that worktree's files are the ones the command ran on. The tree
hash is the scenario runner's: a commit alone changes nothing.

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


def store(top):
    """The directory that holds this repo's verify commands and runs."""
    common = os.path.realpath(os.path.join(top, git(top, "rev-parse", "--git-common-dir")))
    state = scenarios.env("STATE")
    if state:
        return os.path.join(state, "verify", hashlib.sha1(common.encode()).hexdigest())
    return os.path.join(common, "ekit")


def load(path, kind):
    """The JSON value in the file when it is a `kind` (list of runs, dict of sessions); else an empty one."""
    try:
        with open(path) as f:
            value = json.load(f)
    except (OSError, ValueError):
        return kind()
    return value if isinstance(value, kind) else kind()


def save(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(value, f)
    os.replace(tmp, path)


def runs_of(top):
    return load(os.path.join(store(top), "verify.json"), list)


def record(top, cmd, rc):
    """Replaces this worktree's earlier run of `cmd`."""
    runs = [r for r in runs_of(top) if (r["top"], r["cmd"]) != (top, cmd)]
    runs.append({"cmd": cmd, "top": top, "tree": tree(top), "rc": rc})
    save(os.path.join(store(top), "verify.json"), runs)


def keep(top, session, key, cmd):
    """The session's command under `key`: the one already there, else `cmd`, which is then kept (None is not)."""
    path = os.path.join(store(top), "declared.json")
    sessions = load(path, dict)
    mine = sessions.setdefault(session, {})
    if key not in mine and cmd:
        mine[key] = cmd
        save(path, sessions)
    return mine.get(key)


def commands(top, session):
    """The session's verify commands, each once."""
    return sorted(set(load(os.path.join(store(top), "declared.json"), dict).get(session, {}).values()))


def spelled(words):
    """The command line the words stand for, whitespace collapsed: one word is a shell line already."""
    return " ".join((words[0] if len(words) == 1 else shlex.join(words)).split())


def cmd_run(top, words):
    cmd = spelled(words)
    rc = subprocess.run(cmd, shell=True, cwd=top).returncode
    record(top, cmd, rc)  # hashed after the run: what the command left is what the hook will see
    print(f"task-verify: `{cmd}` exited {rc}", file=sys.stderr)
    return rc


def cmd_declare(top, words):
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        print("task-verify: CLAUDE_CODE_SESSION_ID is not set: run this as a Claude Code Bash command, or set it to "
              "the session id", file=sys.stderr)
        return 2
    cmd = spelled(words)
    keep(top, session, f"cmd:{cmd}", cmd)
    print(f"task-verify: `{cmd}` is a verify command of this session", file=sys.stderr)
    return 0


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
    runs = [r for r in runs_of(top) if r["cmd"] == cmd]
    if not runs:
        return "no run recorded"
    passed = [r for r in runs if r["rc"] == 0]
    if any(r["tree"] and tree(r["top"]) == r["tree"] for r in passed):
        return None
    if not passed:
        return f"the run exited {runs[-1]['rc']}"
    return "the files changed since the passing run"


def cmd_check(top, session):
    cmds = commands(top, session)
    if not cmds:
        print("no verify command was declared for this session")
        return 1
    red = [f"`{cmd}`: {why}" for cmd, why in ((cmd, why_not(top, cmd)) for cmd in cmds) if why]
    if red:
        print("\n".join(red))
        return 1
    return 0


def hook():
    data = json.load(sys.stdin)
    session, task = data.get("session_id"), data.get("task_id")
    top = git(data.get("cwd") or os.getcwd(), "rev-parse", "--show-toplevel")
    if not top:
        return 0
    cmd = keep(top, session, f"task:{task}", declared(data.get("task_description")))
    if not cmd or data.get("hook_event_name") == "TaskCreated":
        return 0
    why = why_not(top, cmd)
    if why is None:
        return 0
    if data.get("teammate_name"):
        name = hashlib.sha1(f"{session} {task}".encode()).hexdigest()
        seen, mark = os.path.join(STATE, f"{name}.taskblock"), f"{tree(top)} {why}"
        if read(seen) == mark:
            return 0
        write(seen, mark)
    print(f"[ekit] Task \"{data.get('task_subject')}\" is not verified for the current files: {why}. "
          f"Run `python3 {os.path.abspath(__file__)} run -- {cmd}` in the checkout that holds the work, fix what it "
          "shows, and mark the task completed once it exits 0. The command is the one the task was created with: "
          "a different one is the user's call. It cannot pass here → leave the task open and report it blocked "
          "(finish skill).", file=sys.stderr)
    return 2


USAGE = "usage: task-verify.py [--repo DIR] declare -- CMD... | run -- CMD... | check SESSION | task-verify.py --hook"


def main():
    a = sys.argv[1:]
    if a == ["--hook"]:
        return hook()
    repo = os.getcwd()
    try:
        if a[0] == "--repo":
            repo, a = os.path.abspath(a[1]), a[2:]
        check = a[0] == "check" and len(a) == 2
        if not check and (a[0] not in ("declare", "run") or a[1] != "--" or not any(w.strip() for w in a[2:])):
            raise IndexError
    except IndexError:  # a word is missing, or is not the one the usage line names
        print(USAGE, file=sys.stderr)
        return 2
    top = git(repo, "rev-parse", "--show-toplevel")
    if not top:
        print(f"task-verify: not a git repo: {repo}", file=sys.stderr)
        return 2
    if check:
        return cmd_check(top, a[1])
    try:
        return (cmd_declare if a[0] == "declare" else cmd_run)(top, a[2:])
    except OSError as e:
        print(f"task-verify: nothing recorded, cannot write {e.filename}: {e.strerror}. A sandbox keeps the git dir "
              "read-only: run this same command outside the sandbox.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
