#!/usr/bin/env python3
"""verified-commit: is the commit a mech-review result describes the worktree's head, and the pushed one? (#81)

usage: python3 -I scripts/verified-commit.py [--allow-behind] RESULT WORKTREE

RESULT is a mech-review result envelope (the JSON `mech-review.py all` prints; `-` reads stdin). Its `head` must equal
the worktree's HEAD and, when the branch is pushed, the branch's tip on its remote (its upstream, else origin/<branch>),
asked of the remote with `git ls-remote`, never read from a remote-tracking ref that may be stale. A branch the remote
does not have, a detached HEAD or a repo with no such remote is not pushed: the worktree's head alone decides.
--allow-behind: the remote tip may also be an ancestor of the result's head (fixes verified and not pushed yet: the push
to come fast-forwards it to the verified commit); a tip that is not, or that this clone does not have, is still refused.
The Stop gate hashes trees; this check is about commits. git runs with --no-optional-locks.
exit: 0 the same commit; 1 a different commit (both named); 2 no answer (the result cannot be read or has no commit
SHA head, the path is not a git worktree, the remote cannot be asked, usage): a refusal with its reason, never a pass.
"""
import argparse
import json
import re
import subprocess
import sys

SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")  # SHA-1 or SHA-256, as git prints it


class Refusal(Exception):
    """No answer: the reason goes to stderr, exit 2."""


def run_cmd(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True)
    except OSError as e:
        return 127, "", f"{argv[0]}: {e}"
    return p.returncode, p.stdout, p.stderr


def result_head(path):
    """The result's head SHA, or a Refusal naming why there is none."""
    try:
        if path == "-":
            text = sys.stdin.read()
        else:
            with open(path, encoding="utf-8") as f:
                text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Refusal(f"cannot read the result {path}: {e}")
    try:
        env = json.loads(text)
    except ValueError as e:
        raise Refusal(f"the result is not JSON ({path}: {e})")
    if not isinstance(env, dict) or "head" not in env:
        raise Refusal(f"the result has no head ({path})")
    head = env["head"]
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise Refusal(f"the result's head is not a commit SHA ({path}: {head!r})")
    return head


def remote_tip(git):
    """(name, tip) of the worktree's branch on its remote: tip None when it is not pushed (detached HEAD, no such remote,
    the remote has no such branch). The remote itself is asked; a refusal when it cannot be."""
    rc, branch, _ = git("symbolic-ref", "--short", "-q", "HEAD")
    if rc != 0:
        return "detached HEAD", None
    _, remote, _ = git("config", f"branch.{branch}.remote")
    _, ref, _ = git("config", f"branch.{branch}.merge")
    remote, ref = remote or "origin", ref or f"refs/heads/{branch}"
    short = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    name = f"{remote}/{short}"
    _, remotes, _ = git("remote")
    if remote != "." and remote not in remotes.split():
        return f"no remote {remote}", None
    rc, out, err = git("ls-remote", remote, ref)
    if rc != 0:
        raise Refusal(f"cannot ask {remote} for {short}'s tip: {err or f'git ls-remote exit {rc}'}")
    tips = [line.split("\t")[0] for line in out.splitlines() if line.endswith("\t" + ref)]
    return (name, tips[0]) if tips else (f"{remote} has no {short}", None)


def verify(a, run):
    head = result_head(a.result)

    def git(*args):
        rc, out, err = run(["git", "--no-optional-locks", "-C", a.worktree, *args])
        return rc, out.strip(), err.strip()

    rc, wt_head, err = git("rev-parse", "--verify", "HEAD")
    if rc != 0:
        raise Refusal(f"{a.worktree} is not a git worktree ({err})")
    if wt_head != head:
        print(f"refused: the worktree's head {wt_head} is not the result's head {head}")
        return 1
    name, tip = remote_tip(git)
    if tip is None:
        print(f"verified: {head} is the worktree's head; not pushed ({name})")
        return 0
    if tip == head:
        print(f"verified: {head} is the worktree's head and the remote tip of {name}: {head}")
        return 0
    if a.allow_behind:
        rc, _, _ = git("merge-base", "--is-ancestor", tip, head)
        if rc == 0:
            print(f"verified: {head} is the worktree's head; the remote tip of {name} {tip} is behind it (not pushed "
                  f"yet: the push fast-forwards it to {head})")
            return 0
        if rc != 1:
            print(f"refused: the remote tip of {name} {tip} is not in this clone (fetch, then rerun); the result's head "
                  f"is {head}")
            return 1
    print(f"refused: the remote tip of {name} {tip} is not the result's head {head}")
    return 1


def main(argv, run=run_cmd):
    p = argparse.ArgumentParser(prog="verified-commit.py",
                                description="is the verified commit the worktree's head and the pushed one? (#81)")
    p.add_argument("result", metavar="RESULT", help="mech-review result envelope (JSON); - reads stdin")
    p.add_argument("worktree", metavar="WORKTREE", help="the agent's worktree")
    p.add_argument("--allow-behind", action="store_true",
                   help="the remote tip may be an ancestor of the result's head (fixes not pushed yet)")
    a = p.parse_args(argv)
    try:
        return verify(a, run)
    except Refusal as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
