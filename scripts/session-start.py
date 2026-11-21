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

RULES = """[ekit] Working rules:
- A test or check goes red → classify it with the failure-triage skill before editing code.
- Same blocker 3× (missing tool, auth, approval denied, quota) → stop retrying; tell the user exactly what's needed.
- A denied or blocked command stays blocked: ask the user, keeping the exact command. Usage limit hit → stop."""


def main():
    raw = sys.stdin.read()
    data = json.loads(raw or "{}")
    cwd = data.get("cwd") or os.getcwd()
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "finish-gate.py"), "--baseline"], input=raw, text=True)
    pf = "\n".join(preflight.checks(cwd, quiet=True))
    ctx = "\n".join([RULES, f"[ekit] Python: {launcher.command()}",
                     f"[ekit] Scenario runner: {launcher.line(os.path.join(HERE, 'scenarios.py'))}",
                     f"[ekit] Preflight (this env):\n{pf}"])
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}))


if __name__ == "__main__":
    main()
