"""SessionStart hook: record the tree baseline for the finish gate, inject preflight warnings and the kit's always-on rules
(the finish gate and taste-it are orchestrate-only). Every command it prints starts the Python the hook found."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I drops the script dir from sys.path

import launcher  # noqa: E402 - the sys.path line above has to run first
import preflight  # noqa: E402 - imported after the sys.path line above, like the one before it
from mech_review import gitio, stack_plan  # noqa: E402 - imported after the sys.path line above, like the ones before it

RULES = """[ekit] Working rules:
- A test or check goes red → classify it with the failure-triage skill before editing code.
- Same blocker 3× (missing tool, auth, approval denied, quota) → stop retrying; tell the user exactly what's needed.
- A denied or blocked command stays blocked: ask the user, keeping the exact command. Usage limit hit → stop."""

FIX = "edit it with the ci-doctor skill"
MAX_ITEMS = 20  # manifests and messages shown; the rest is a count and the command that lists them
MAX_TEXT = 500  # characters of one repo-controlled value


def shown(text):
    """repo- or PR-controlled text (a path, a plan value) as printable text: every character that is not printable
    (newline, CR, other C0 and C1 controls, DEL, line separators) escaped, so it can never start a session line."""
    out = "".join(c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in str(text))
    return out if len(out) <= MAX_TEXT else f"{out[:MAX_TEXT]}… (cut: {len(out)} characters)"


def has_tomllib():
    try:
        import tomllib  # noqa: F401 - only whether it imports
    except ImportError:
        return False
    return True


def drift(cwd):
    """The `[ekit]` lines for the stack plan's drift (#57): the committed tree at HEAD of the repo holding cwd against
    the plan at HEAD, what CI's drift check reads. Git only: no test runner, no network. Nothing when cwd is in no git
    repo, the repo has no commit, there is no plan, or it is clean; any other failure is one line, never a clean read."""
    os.environ["GIT_NO_LAZY_FETCH"] = "1"  # git 2.44+: a missing object is an error, never a fetch (older: partial_clone)
    try:
        return _drift(cwd)
    except OSError:
        return ["[ekit] Stack plan: git is not on PATH, so the drift check cannot run here; CI still runs it on every PR."]
    except Exception as e:  # noqa: BLE001 - a git error or a bug here must not fail the hook or read as clean
        return [f"[ekit] Stack plan: the drift check could not run here ({type(e).__name__}: {shown(e)}); CI still "
                f"runs it on every PR."]


def in_git(cwd):
    """cwd or a folder above it holds a `.git`, or is a git dir itself (HEAD and objects/: a bare repo, a .git dir).
    Read from the disk, so a git that fails there (dubious ownership, a bad config) is a failure, not "no repo"."""
    d = os.path.abspath(cwd)
    while True:
        if os.path.lexists(os.path.join(d, ".git")) or (
                os.path.isfile(os.path.join(d, "HEAD")) and os.path.isdir(os.path.join(d, "objects"))):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def partial_clone(top):
    """the repo has a promisor remote: git fetches any object it lacks from there (a lazy fetch, a network call)."""
    try:
        found = gitio.git(top, "config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$")
    except gitio.Die:  # exit 1: no such key
        return False
    return any(line.split(" ", 1)[-1].strip().lower() != "false" for line in found.splitlines())


def _drift(cwd):
    if not in_git(cwd):  # a folder outside git: nothing to judge
        return []
    top = gitio.git(cwd, "rev-parse", "--show-toplevel").strip()
    try:
        gitio.resolve(top, "HEAD")
    except gitio.Die:  # no commit yet: no committed plan to read
        return []
    if partial_clone(top):
        return ["[ekit] Stack plan: the drift check is skipped here: this is a partial clone, where git would fetch the "
                "objects it lacks (a network call); CI still runs it on every PR."]
    try:
        d = stack_plan.drift_at(top, "HEAD")
    except stack_plan.PlanError as e:
        if not has_tomllib():
            v = sys.version_info
            return [f"[ekit] Stack plan: the drift check at session start needs python 3.11 or newer (tomllib), this "
                    f"is {v[0]}.{v[1]}: nothing here says what is unchecked. CI still runs the drift check on every PR."]
        return [f"[ekit] Stack plan does not read, so nothing here says what is unchecked: {shown(e)}. Fix it "
                f"({FIX}); CI's drift check stops on it too."]
    if not d.has_plan and gitio.git(top, "ls-tree", "-z", "HEAD", "--", stack_plan.PATH):
        return [f"[ekit] Stack plan: {stack_plan.PATH} is in HEAD's tree but cannot be read as a file (a missing object "
                f"in a partial or broken clone, or not a file), so nothing here says what is unchecked; CI still runs it on every PR."]
    if not d.uncovered and not d.messages:
        return []
    items = [f"- unchecked manifest {shown(p)}: no [[stack]] entry covers it, so mech-review checks nothing there; add an "
              f"entry (its folder, an adapter that lists the manifest) or its folder to `ignore`" for p in d.uncovered]
    items += [f"- {shown(m)}" for m in d.messages]
    if len(items) > MAX_ITEMS:
        cmd = launcher.line(os.path.join(HERE, "mech-review.py"), "drift", "--repo", launcher.shown(top), "--base HEAD",
                            "--head HEAD --format text")
        items[MAX_ITEMS:] = [f"- and {len(items) - MAX_ITEMS} more: run `{shown(cmd)}`"]
    return [f"[ekit] Stack plan drift at HEAD ({stack_plan.PATH}; {FIX}):", *items]


def main():
    raw = sys.stdin.read()
    data = json.loads(raw or "{}")
    cwd = data.get("cwd") or os.getcwd()
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "finish-gate.py"), "--baseline"], input=raw, text=True)
    pf = "\n".join(preflight.checks(cwd, quiet=True))
    ctx = "\n".join([RULES, f"[ekit] Python: {launcher.command()}",
                     f"[ekit] Scenario runner: {launcher.line(os.path.join(HERE, 'scenarios.py'))}",
                     f"[ekit] Preflight (this env):\n{pf}", *drift(cwd)])
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}))


if __name__ == "__main__":
    main()
