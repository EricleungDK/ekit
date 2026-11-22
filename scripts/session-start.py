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


def one_line(e):
    return " ".join(str(e).split())


def has_tomllib():
    try:
        import tomllib  # noqa: F401 - only whether it imports
    except ImportError:
        return False
    return True


def drift(cwd):
    """The `[ekit]` lines for the stack plan's drift (#57): the committed tree at HEAD of the repo holding cwd against
    the plan at HEAD, what CI's drift check reads. Git only: no test runner, no network."""
    try:
        top = gitio.git(cwd, "rev-parse", "--show-toplevel").strip()
        gitio.resolve(top, "HEAD")
    except (gitio.Die, OSError):  # not a git repo, no commit yet, or no git here: no committed plan to read
        return []
    try:
        d = stack_plan.drift_at(top, "HEAD")
    except stack_plan.PlanError as e:
        if not has_tomllib():
            v = sys.version_info
            return [f"[ekit] Stack plan: the drift check at session start needs python 3.11 or newer (tomllib), this "
                    f"is {v[0]}.{v[1]}: nothing here says what is unchecked. CI still runs the drift check on every PR."]
        return [f"[ekit] Stack plan does not read, so nothing here says what is unchecked: {one_line(e)}. Fix it "
                f"({FIX}); CI's drift check stops on it too."]
    except Exception as e:  # noqa: BLE001 - a git error or a bug here must not fail the hook or read as clean
        return [f"[ekit] Stack plan: the drift check could not run here ({type(e).__name__}: {one_line(e)}); CI still "
                f"runs it on every PR."]
    if not d.uncovered and not d.messages:
        return []
    lines = [f"[ekit] Stack plan drift at HEAD ({stack_plan.PATH}; {FIX}):"]
    lines += [f"- unchecked manifest {p}: no [[stack]] entry covers it, so mech-review checks nothing there; add an "
              f"entry (its folder, an adapter that lists the manifest) or its folder to `ignore`" for p in d.uncovered]
    lines += [f"- {m}" for m in d.messages]
    return lines


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
