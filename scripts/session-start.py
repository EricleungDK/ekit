"""SessionStart hook: record the tree baseline for the finish gate, inject preflight warnings and the kit's always-on rules
(the finish gate and taste-it are orchestrate-only). Every command it prints starts the Python the hook found."""
import json
import os
import subprocess
import sys
import threading

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
SHALLOW = "; in this shallow clone the days retiring count only the history here"
DRIFT_SECONDS = 3  # the drift check's share of the hook (it takes ~0.1 s): past it, one line, the context still goes


def shown(text):
    """repo- or PR-controlled text (a path, a plan value) as printable text: every character that is not printable
    (newline, CR, other C0 and C1 controls, DEL, line separators) escaped, so it can never start a session line."""
    out = "".join(c if c.isprintable() else repr(c)[1:-1] for c in str(text))  # "\n" -> \n, "\u2028" -> \u2028
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
    os.environ.update(LC_ALL="C", LANGUAGE="")  # git's own words, unlocalized: "not a git repository" is read below
    out = []
    worker = threading.Thread(target=lambda: out.append(_guarded(cwd)), daemon=True)  # left behind on overrun
    worker.start()
    worker.join(DRIFT_SECONDS)
    if not out:
        return [f"[ekit] Stack plan: the drift check did not finish in {DRIFT_SECONDS} s here, so nothing here says what "
                f"is unchecked; CI still runs it on every PR."]
    return out[0]


def _guarded(cwd):
    try:
        return _drift(cwd)
    except FileNotFoundError:
        return ["[ekit] Stack plan: git is not on PATH, so the drift check cannot run here; CI still runs it on every PR."]
    except Exception as e:  # noqa: BLE001 - a git error or a bug here must not fail the hook or read as clean
        return [f"[ekit] Stack plan: the drift check could not run here ({type(e).__name__}: {shown(e)}); CI still "
                f"runs it on every PR."]


def partial_clone(top):
    """the repo has a promisor remote: git fetches any object it lacks from there (a lazy fetch, a network call)."""
    try:
        keys = gitio.git(top, "config", "--name-only", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$")
    except gitio.Die:  # exit 1: no such key
        return False
    for key in keys.splitlines():  # one key a line: a remote name may hold a space
        if key == "extensions.partialclone" or gitio.git(top, "config", "--bool", "--get", key).strip() == "true":
            return True  # a promisor set to 0, no, off or false is none: git reads the value as a boolean
    return False


def _drift(cwd):
    try:
        top = gitio.git(cwd, "rev-parse", "--show-toplevel").strip()
    except gitio.Die as e:
        if "not a git repository (or any" in str(e):  # git's search found none (a ceiling, a filesystem boundary too)
            return []
        raise
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
    if not d.has_plan and gitio.git(top, "ls-tree", "HEAD", stack_plan.PATH):  # listed, yet drift_at read none
        return [f"[ekit] Stack plan: {stack_plan.PATH} is in HEAD's tree but cannot be read as a file (a missing "
                f"object in a partial or broken clone, or not a file), so nothing here says what is unchecked; CI still "
                f"runs it on every PR."]
    if not d.uncovered and not d.messages:
        return []
    items = [f"- unchecked manifest {shown(p)}: no [[stack]] entry covers it, so mech-review checks nothing there; add "
             f"an entry (its folder, an adapter that lists the manifest) or its folder to `ignore`" for p in d.uncovered]
    items += [f"- {shown(m)}" for m in d.messages]
    if gitio.git(top, "rev-parse", "--is-shallow-repository").strip() == "true":  # the history is cut
        items = [i + SHALLOW if i.startswith("- retiring ") else i for i in items]
    if len(items) > MAX_ITEMS:
        # the kit's own path and fixed words, no repo-controlled text: printed whole, never cut
        cmd = launcher.line(os.path.join(HERE, "mech-review.py"), "drift --repo . --base HEAD --head HEAD --format text")
        items[MAX_ITEMS:] = [f"- and {len(items) - MAX_ITEMS} more: in the repo root, run `{cmd}`"]
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
