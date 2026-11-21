"""Stop hook: in an orchestrate session, block the stop until the work has its finish report.

Orchestrate-only: silent unless the session was armed by a prompt starting with /ekit:orchestrate-agent (or /orchestrate-agent).
Subagent stops are never gated: the orchestrator owns the report and the taste run.

Work = the working tree's content differs from session start (runner `tree-hash`: commits count, a commit alone
changes nothing; the baseline is per repo). With work done, the stop is allowed when:
- the last assistant message carries the finish report (`## Finish: done` or `## Finish: blocked`), and
- in a repo with .ekit/scenarios/, `check` is a fresh PASS for the current tree (a `blocked` report needs no PASS).
- for a `done` report, every verify command of the session passed on the current tree (`task-verify.py check`):
  the units' commands and the whole job's, whose task carries the full suite. A session with no such command is not
  green. A `blocked` report needs none.
A tree that was reported stays allowed, but a done report on a tree only a blocked one was given for is checked again. A missing report blocks once per tree; scenarios or verify commands that are
not green block every `done` report. stop_hook_active (the stop right after a block) is the loop guard: such a stop is
let through, except one that gives a `done` report again. Saying done twice proves nothing, so its checks run each
time; `## Finish: blocked` is the way out, and Claude Code itself ends a run of consecutive blocks.
Runner errors fail closed (block), except for a `blocked` report. A runner that cannot run on this host (a runner
error, scenarios that failed only on what the host lacks, a verify command `n/a (env)`, and nothing else red) is
named as such, with `## Finish: blocked` and the debt named as the way out. That debt is kept for the tree it was
found on: a blocked report on that tree stands only when its `Verification debt:` block names each item (each
scenario id, each command, the scenario runner), the stop right after a block included; it goes once met or once the
files change, when it is found again for the new files. Printed commands start the Python the hook found (launcher).
A stop while a subagent still runs (the payload's `background_tasks`) is a wait for its report, not the end of the
work: it is allowed and asks nothing. A payload without that list (an older Claude Code) is gated as any stop.
Test seams: EKIT_SCENARIOS_PY overrides the runner path, EKIT_TASK_VERIFY_PY the verifier's.

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir from sys.path
import launcher  # noqa: E402 - the sys.path line above has to run first

STATE = os.environ.get("EKIT_STATE") or os.environ.get("EK_STATE") or os.path.join(
    os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.cache/ekit"), "state"
)
SCEN = os.environ.get("EKIT_SCENARIOS_PY") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios.py")
VERIFY = os.environ.get("EKIT_TASK_VERIFY_PY") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "task-verify.py")
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


def verifier(repo, session):
    r = subprocess.run([sys.executable, "-I", VERIFY, "--repo", repo, "check", session], capture_output=True, text=True)
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
    path = data.get("transcript_path")
    if not path:
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.fstat(f.fileno()).st_size - TAIL))
            lines = f.read().decode(errors="replace").splitlines()
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


def waiting(data):
    """True when a subagent of this session still runs: the session wakes when it reports, so this stop ends nothing.
    Only a running subagent counts. One that finished wakes nothing; a background shell (a dev server) may never end."""
    tasks = data.get("background_tasks")
    return isinstance(tasks, list) and any(
        isinstance(t, dict) and t.get("type") == "subagent" and t.get("status") == "running" for t in tasks)


def block(reason):
    print(json.dumps({"decision": "block", "reason": f"[ekit] {reason}"}))


NA_LINE = re.compile(r"`(.*)`: n/a \(env\): [^`]*")  # task-verify.py check: a command this host cannot run


DEBT_LINE = re.compile(r"[*_]*verification debt[*_]*\s*:\s*(.*)", re.I)
# a line that ends the debt block: a blank line, a heading, a table row, a fence, or another field of the report
END = re.compile(r"\s*$|\s*(#|\||```|~~~)|\s*[*_]*(open|env|tdd|mech|blocker|needs you|run|expect|why|decide|"
                 r"verdict|uncommitted)[*_]*\s*:", re.I)


def debt_items(msg):
    """The items of the report's `Verification debt:` block as the finish skill writes it: one per line, on the
    field's own line or the lines under it (`<cmd> → <reason> → <where>`), up to the block's end. A quoted (`>`) or
    fenced line is no item, nor one that says none."""
    items, fenced, inside = [], False, False
    for line in msg.split("\n"):
        if line.strip().startswith(("```", "~~~")):
            fenced = not fenced
            if inside:
                break
            continue
        if fenced:
            continue
        bare = line.strip().lstrip("-* \t")
        if not inside:
            m = DEBT_LINE.match(bare)  # a quoted line starts with >: never the field
            if m:
                inside = True
                items.append(m.group(1))
            continue
        if END.match(line):
            break
        if not line.lstrip().startswith(">"):
            items.append(bare)
    return [it for it in items if it.strip() and not re.match(r"[`*_\s]*none\b", it.lower())]


def owe(p, items, tree=""):
    """Keep the debt a blocked report on `tree` must name: [(how it is named to the agent, a regex the report's debt
    block must match)]; none: no file."""
    if items:
        write(p, json.dumps({"tree": tree, "items": items}))
    elif os.path.exists(p):
        os.remove(p)


def unnamed(p, msg, tree="", derive=None):
    """The debt items the debt block of the report `msg` does not name ([] when none is owed). A debt found on other
    files is found again for `tree` (derive(): its items now), never dropped for a file touched."""
    try:
        debt = json.loads(read(p) or "{}")
    except ValueError:
        debt = {}
    if not isinstance(debt, dict) or not debt.get("items"):
        return []
    if debt.get("tree") != tree:
        items = derive() if derive else []
        owe(p, items, tree)
        debt = {"items": items}
    block = "\n".join(debt_items(msg))
    return [shown for shown, pattern in debt["items"] if not re.search(pattern, block, re.I)]


def host_debt(top, session):
    """What this host cannot run for the files as they are: the scenarios that failed only on it, the verify
    commands it lacks the shell for: [(how it is named, a regex)]."""
    items = []
    if any(os.path.isdir(os.path.join(top, d, "scenarios")) for d in (".ekit", ".ek")):
        rc, why = runner(top, "check")
        if rc == 1 and why.startswith(NOT_HERE):
            items += [(f"`{i}`", named(i)) for i in (x.split(": ", 1)[0] for x in why[len(NOT_HERE):].split("; "))]
    rc, why = verifier(top, session)
    items += [(f"`{m.group(1)}`", named(m.group(1))) for m in map(NA_LINE.fullmatch, why.splitlines()) if m]
    return items


def named(text):
    """a regex for `text` as a whole token: a scenario id or a command, not a part of a longer word"""
    return r"(?<![\w/.-])" + re.escape(text) + r"(?![\w/.-])"


HOST = "It cannot run on this host → `## Finish: blocked`, naming it as verification debt. "
NOT_HERE = "cannot run here: "  # scenarios.py check: the last run failed only on what this host lacks
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
    top = os.path.normpath(top)  # git says C:/x on Windows: the OS's own spelling, as the runner and verifier get it
    if not baseline and data.get("hook_event_name") == "SubagentStop":
        return  # a subagent's stop (an older install may still register it): nothing to hash
    if not baseline and data.get("stop_hook_active") and report_kind(data) not in ("done", "blocked"):
        return  # the loop guard: the stop after a block ends the turn, unless it claims done again or gives a blocked
        # report, which must still name the debt the gate asked for
    if not baseline and waiting(data):
        return
    key = hashlib.sha1(os.path.realpath(top).encode()).hexdigest()[:12]
    base, reported, gated, debt = (path(session, f"{k}-{key}") for k in ("sbase", "reported", "gated", "debt"))
    rc, cur = runner(top, "tree-hash")
    if baseline:
        prune()
        if read(base) is None:
            write(base, cur if rc == 0 else "")
        return
    run_hint = (f"Run `{launcher.line(SCEN, '--repo', launcher.shown(top), 'run')}` and follow the taste-it skill "
                "(ekit:taste-it). ")
    kind = report_kind(data)
    if kind == "blocked":
        missing = unnamed(debt, last_message(data), cur if rc == 0 else "", lambda: host_debt(top, session))
        if missing:  # the gate said what cannot run here: the way out names it
            return block(f"A blocked report names its verification debt: {', '.join(missing)}. Name them, then stop.")
    if rc != 0:
        if kind == "blocked":
            return owe(debt, [])  # named: met
        owe(debt, [("the scenario runner (scenarios.py cannot run on this host)",
                    r"scenarios\.py|scenario runner|\.ekit/scenarios")])
        return block(f"scenario runner error: {cur.splitlines()[-1] if cur else f'exit {rc}'}. {run_hint}{HOST}{ASK}")
    said, _, on = (read(reported) or "").rpartition(" ")  # "<kind> <tree>"; a bare tree: done (older state)
    if cur == read(base) or (cur == on and (kind != "done" or said in ("", "done"))):
        return  # a done report is checked again on a tree only a blocked report was given for
    if kind != "blocked" and any(os.path.isdir(os.path.join(top, d, "scenarios")) for d in (".ekit", ".ek")):
        rc, why = runner(top, "check")
        if rc == 1 and why.startswith(NOT_HERE):
            ids = [part.split(": ", 1)[0] for part in why[len(NOT_HERE):].split("; ")]
            owe(debt, [(f"`{i}`", named(i)) for i in ids], cur)
            return block(f"Scenarios cannot run on this host: {why[len(NOT_HERE):]}. Give `## Finish: blocked`, "
                         f"naming the scenarios as verification debt. {ASK}")
        if rc == 1:
            return block(f"Scenarios not green: {why}. {run_hint}{ASK}")
        if rc != 0:
            return block(f"scenario runner error: {why.splitlines()[-1] if why else f'exit {rc}'}. {run_hint}{HOST}{ASK}")
    if kind == "done":
        rc, why = verifier(top, session)
        tool = f"{launcher.line(VERIFY)} --repo {launcher.shown(top)}"
        na = [m.group(1) for m in map(NA_LINE.fullmatch, why.splitlines()) if m]
        if rc == 1 and na and len(na) == len(why.splitlines()):  # every red one only lacks this host
            owe(debt, [(f"`{c}`", named(c)) for c in na], cur)
            return block(f"A verify command cannot run on this host: {why}. Give `## Finish: blocked`, naming it as "
                         f"verification debt. {ASK}")
        if rc == 4:
            return block("A done report needs verify commands, and no verify command was declared for this session. "
                         "Declare the units' commands and the full suite for the whole job, each with "
                         f"`{tool} --session {session} declare -- <command>`, run each with `run -- "
                         "<command>` in place of `declare`, then give the finish report again.")
        if rc != 0:
            return block(f"Verify commands not green for the current files: {why}. Run each with `{tool} run -- "
                         "<command>`, fix what it shows, then give the finish report again. It cannot pass here → "
                         "`## Finish: blocked`.")
    if kind:
        write(reported, f"{kind} {cur}")
        owe(debt, [])
        return
    if cur == read(gated):
        return
    write(gated, cur)
    block(f"Work changed since session start and the last message is not a finish report. {ASK}")


if __name__ == "__main__":
    main()
