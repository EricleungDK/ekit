"""Stop hook: in an orchestrate session, block the stop until the work has its finish report.

Orchestrate-only: silent unless the session was armed by a prompt starting with /ekit:orchestrate-agent (or /orchestrate-agent).
Subagent stops are never gated: the orchestrator owns the report and the taste run.

Work = the working tree's content differs from session start (runner `tree-hash`: commits count, a commit alone
changes nothing; the baseline is per repo). With work done, the stop is allowed when:
- the last assistant message carries the finish report (`## Finish: done` or `## Finish: blocked`), and
- in a repo with .ekit/scenarios/, `check` is a fresh PASS for the current tree (a `blocked` report needs no PASS).
A tree that was reported stays allowed. A missing report blocks once per tree; scenarios that are not green block
every stop. stop_hook_active is the loop guard. Runner errors fail closed (block).
Test seam: EKIT_SCENARIOS_PY overrides the runner path.

`finish-gate.py --baseline` (stdin: hook payload) records the tree state at session start instead.
`finish-gate.py --arm` (UserPromptSubmit payload) arms the session when the prompt invokes orchestrate-agent.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

STATE = os.environ.get("EKIT_STATE") or os.environ.get("EK_STATE") or os.path.join(
    os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.cache/ekit"), "state"
)
SCEN = os.environ.get("EKIT_SCENARIOS_PY") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios.py")
KEEP_DAYS = 14
TAIL = 400_000  # bytes of transcript read to find the last assistant message

ARM = re.compile(r"(?:\A\s*|<command-name>)/(?:ekit:)?orchestrate-agent(?![\w-])")
FINISH = re.compile(r"^\s{0,3}#{1,6}\s*Finish:\s*(done|blocked)\b", re.M | re.I)


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def path(session, kind):
    os.makedirs(STATE, exist_ok=True)
    return os.path.join(STATE, f"{session}.{kind}")


def read(p):
    try:
        with open(p) as f:
            return f.read()
    except OSError:
        return None


def write(p, v):
    with open(p, "w") as f:
        f.write(v)


def prune():
    """Session state older than KEEP_DAYS goes: the directory would otherwise grow by a few files per session."""
    cutoff = time.time() - KEEP_DAYS * 86400
    try:
        for name in os.listdir(STATE):
            p = os.path.join(STATE, name)
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except OSError:
        pass


def runner(repo, cmd):
    r = subprocess.run([sys.executable, "-I", SCEN, "--repo", repo, cmd], capture_output=True, text=True)
    return r.returncode, (r.stdout.strip() or r.stderr.strip())


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def last_message(data):
    """The assistant's final message: the payload's `last_assistant_message`, else the text after the last user
    entry (prompt or tool result) in the transcript. "" when neither can be read."""
    msg = data.get("last_assistant_message")
    if isinstance(msg, str) and msg:
        return msg
    try:
        with open(data.get("transcript_path") or "", "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    parts = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue  # a cut first line, or not JSON
        if not isinstance(e, dict) or e.get("isSidechain"):
            continue
        if e.get("type") == "user":
            break
        if e.get("type") == "assistant":
            parts.append(_text((e.get("message") or {}).get("content")))
    return "\n".join(reversed(parts))


def report_kind(data):
    """`done` or `blocked` when the last message carries the finish report header, else None."""
    m = FINISH.search(last_message(data))
    return m.group(1).lower() if m else None


def block(reason):
    print(json.dumps({"decision": "block", "reason": f"[ekit] {reason}"}))


ASK = ("Give the finish report (finish skill): it opens with `## Finish: done` or `## Finish: blocked`, then each "
       "criterion with evidence, verification debt, and what stays uncommitted and why. Then stop.")


def main():
    data = json.load(sys.stdin)
    session, cwd = data.get("session_id", "none"), data.get("cwd") or os.getcwd()
    if "--arm" in sys.argv:
        if ARM.search(data.get("prompt") or ""):
            write(path(session, "armed"), "1")
        return
    baseline = "--baseline" in sys.argv
    if not baseline and read(path(session, "armed")) is None:
        return
    top = (git(cwd, "rev-parse", "--show-toplevel") or "").strip()
    if not top:
        return
    key = hashlib.sha1(os.path.realpath(top).encode()).hexdigest()[:12]
    base, reported, gated = (path(session, f"{k}-{key}") for k in ("sbase", "reported", "gated"))
    rc, cur = runner(top, "tree-hash")
    if baseline:
        prune()
        if read(base) is None:
            write(base, cur if rc == 0 else "")
        return
    if data.get("stop_hook_active") or data.get("hook_event_name") == "SubagentStop":
        return
    run_hint = f"Run `python3 {SCEN} --repo {top} run` and follow the taste-it skill (ekit:taste-it). "
    if rc != 0:
        return block(f"scenario runner error: {cur.splitlines()[-1] if cur else f'exit {rc}'}. {run_hint}{ASK}")
    if cur in (read(base), read(reported)):
        return
    kind = report_kind(data)
    if kind != "blocked" and any(os.path.isdir(os.path.join(top, d, "scenarios")) for d in (".ekit", ".ek")):
        rc, why = runner(top, "check")
        if rc == 1:
            return block(f"Scenarios not green: {why}. {run_hint}{ASK}")
        if rc != 0:
            return block(f"scenario runner error: {why.splitlines()[-1] if why else f'exit {rc}'}. {run_hint}{ASK}")
    if kind:
        write(reported, cur)
        return
    if cur == read(gated):
        return
    write(gated, cur)
    block(f"Work changed since session start and the last message is not a finish report. {ASK}")


if __name__ == "__main__":
    main()
