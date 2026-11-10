"""PostToolUseFailure hook: turn a known Bash failure signature into one context line. Silent otherwise.

A signature is a lead, not a verdict: the line names what matched and the check that settles it."""
import json
import os
import re
import subprocess
import sys

ENV = re.compile(
    r"EPERM|Operation not permitted|EROFS|Read-only file system|docker\.sock|"
    r"Could not resolve host|ENOTFOUND|EAI_AGAIN|Temporary failure in name resolution",
    re.I,
)
PORT = re.compile(r"EADDRINUSE|address already in use", re.I)
NOT_FOUND = re.compile(r"(?:^|\s)([\w.-]+): command not found")
FALLBACK = {"python": "python3", "rg": "grep -rn / find", "jq": "python3 -c 'import json'", "pip": "uv pip / python3 -m pip"}
TEST_CMD = re.compile(r"\b(pytest|vitest|jest|playwright test|cargo test|go test|npm (run )?test|pnpm test|yarn test|bun test|unittest)\b")


LOOKUP_TIMEOUT = 5  # seconds a port lookup may take: the hook must never hold the session up


def run(argv):
    """stdout of a lookup tool, or "" when the host has no such tool, it will not run, or it does not answer in time."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=LOOKUP_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def listeners(port, run=run):
    """(pid, command) of the process listening on the port, or None. `ss` on Linux; `lsof` where there is no ss (macOS)."""
    out = os.environ.get("SS_STUB") or run(["ss", "-ltnpH", f"sport = :{port}"])
    m = re.search(r'\("([^"]+)",pid=(\d+)', out)
    if m:
        return m.group(2), m.group(1)
    for line in run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"]).splitlines()[1:]:  # COMMAND PID USER ...
        cols = line.split()
        if len(cols) > 1 and cols[1].isdigit():
            return cols[1], cols[0]
    return None


def classify(cmd, err):
    if PORT.search(err):
        m = re.search(r":(\d{2,5})\b", err)
        port = m and m.group(1)
        owner = port and listeners(port)
        held = f"port {port} held by pid {owner[0]} ({owner[1]})" if owner else f"port {port or '?'} in use"
        return f"[ekit] stale: {held}. If it's a dev server you started, kill that exact PID only; otherwise use another port."
    m = ENV.search(err)
    if m:
        return (f"[ekit] looks like sandbox/env (matched `{m.group(0)}`), not yet a code bug. Leave code as is and rerun "
                "once unsandboxed/escalated. Passes there → record 'passed only unsandboxed'. Fails the same way there → "
                "it is the code or the test: classify it with the failure-triage skill. Can't rerun → verification debt.")
    m = NOT_FOUND.search(err)
    if m:
        tool = m.group(1)
        return f"[ekit] {tool} missing → {FALLBACK.get(tool, 'find an installed alternative or log as verification debt')}."
    if TEST_CMD.search(cmd):
        return "[ekit] test red. Before editing code, classify it with the failure-triage skill."
    return None


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    msg = classify(data.get("tool_input", {}).get("command", ""), data.get("error") or "")
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": msg}}))


if __name__ == "__main__":
    main()
