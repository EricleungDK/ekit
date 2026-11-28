"""The contract envelope: entries and their ids, the one-line summary, the plugin version."""
import hashlib
import json
import os
import re

PLUGIN = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".claude-plugin", "plugin.json"))
CHECKS = ("R1", "R2", "R3", "R4")
# checks an envelope holds only when they apply: D (the stack plan's drift check, #56) only when a plan exists, so a
# repo with no plan reads exactly as before; R0 (the adapter proof, #20) only from the subcommands that run it
FIRST = ("R0",)
OPTIONAL = FIRST + ("D",)
ALL = CHECKS + OPTIONAL


def names(checks):
    """the checks a result reports, in order: R0 when it holds it, R1-R4 always, then each other optional one."""
    return (tuple(c for c in FIRST if c in checks) + CHECKS
            + tuple(c for c in OPTIONAL if c in checks and c not in FIRST))


def ekit_version():
    """The plugin version, or `unknown` when the scripts run without the plugin manifest beside them (a bare copy)."""
    try:
        with open(PLUGIN) as f:
            return json.load(f)["version"]
    except (OSError, ValueError, KeyError):
        return "unknown"


def entry(check, file, line, key, cls, severity, problem, hint, forbidden):
    """key: test fn or rule name (never a line number); the id is assigned in finalize."""
    return {"id": "", "check": check, "class": cls, "severity": severity, "file": file, "line": line,
            "problem": problem, "hint": hint, "forbidden": forbidden, "_key": key}


RESOLUTION_FAILED = ("Could not resolve", "Could not transfer artifact", "Unknown host")  # Maven's: the network, not the PR
GOAL_FAILED = "[ERROR] Failed to execute goal "  # Maven's goal-failure line: the one place RESOLUTION_FAILED counts
BANNERS = ("[INFO] BUILD FAILURE", "[INFO] BUILD SUCCESS")  # what Maven prints after every test's output
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def resolution_failed(output):
    """Maven's goal-failure block says a dependency could not be fetched (#107): an `[ERROR] Failed to execute goal`
    line, with the `[ERROR] <text>` lines that continue it, holds a RESOLUTION_FAILED phrase. Only Maven's own lines
    count: those after its last BUILD banner, which it prints after every test's output (none after BUILD SUCCESS: no
    goal failed), or, with no banner (-q), the last goal-failure line alone. The same words a test prints anywhere else
    never count. Lines split at LF (a CR before it is ignored), colour codes dropped."""
    lines = [ANSI.sub("", l).rstrip() for l in (output or "").split("\n")]
    banners = [i for i, l in enumerate(lines) if l in BANNERS]
    if banners:
        lines = lines[banners[-1] + 1:]
    goals = [i for i, l in enumerate(lines) if l.startswith(GOAL_FAILED)]
    for g in goals if banners else goals[-1:]:
        block = [lines[g]]
        for l in lines[g + 1:]:
            if not l.startswith("[ERROR] ") or l[8:].startswith("-> "):  # "[ERROR]" alone, rstripped, ends it too
                break
            block.append(l)
        if any(s in l for l in block for s in RESOLUTION_FAILED):
            return True
    return False


def no_report(tool, where, why, output=""):
    """(R3 check, entries) when the mutation tool ran and left no report (#22 review round 2): the run did not judge the
    change, and the tool is installed, so it is no toolchain absence: R3 fails with one entry, never n/a (env) or a
    pass. why: the first line of its output, or its exit code. When Maven's goal-failure line shows that a dependency
    could not be fetched (resolution_failed), the entry is a CI one (check CI, class env, as a job with no result is):
    the runner, not the PR; else R3's, agent-fixable."""
    problem = f"{tool} ran and wrote no report ({where}): mutants not read: {why}"
    ci = resolution_failed(output)
    return {"status": "fail", "note": problem}, finalize([entry(
        "CI" if ci else "R3", "", 0, "no-report", "env" if ci else "agent-fixable", "fail", problem,
        "read the tool's run log: the code at head must build and its tests pass under the tool; if the tool or its "
        "setup is at fault, a person repairs it, and a rerun follows a network failure",
        "a mutation check that did not run")])


def finalize(entries):
    """id = <check>-<sha1(check+file+key)[:8]>. The n-th entry (line order, n>=1) with the same check+file+key
    gets key '#n' so repeats are kept; n=0 keeps the plain id. Line numbers never enter an id."""
    groups = {}
    for e in entries:
        groups.setdefault((e["check"], e["file"], e["_key"]), []).append(e)
    out = []
    for (check, file, key), group in groups.items():
        group.sort(key=lambda e: (e["line"] == 0, e["line"]))
        for n, e in enumerate(group):
            k = key if n == 0 else f"{key}#{n}"
            e["id"] = f"{check}-" + hashlib.sha1((check + file + k).encode("utf-8", "surrogateescape")).hexdigest()[:8]
            del e["_key"]
            out.append(e)
    # file-level entries (line 0) sort after line-anchored ones within a file
    return sorted(out, key=lambda e: (e["file"], e["line"] == 0, e["line"], e["id"]))


def _partial_label(check, name):
    """`R3 (tested/total)`; `?` when the total is unknown (budget hit before the mutant list was written)."""
    if check.get("tested") is None:
        return name
    total = check["total"] if check["total"] is not None else "?"
    return f"{name} ({check['tested']}/{total})"


def summarize(head, checks, entries):
    """`all pass <head>` only when every check passed and there are no entries. Otherwise
    `<pass|fail> <head> (<F> fail, <C> confirm[, <W> waived]; ran: <checks>[; partial: R3 (<tested>/<total>)]
    [; unproven: R0][; skipped: <checks>][; n/a: <checks>])`. unproven (#20): R0 ran, a cheat has no fixture: never all pass.
    `, <W> waived` appears only when a person waived an entry (waiver.py); a waived check counts as ran, a partial one too.
    n/a (toolchain absent) is not ran and not skipped: it is named so it never reads as a pass. A check with status
    `fail` makes it `fail` even with no fail entry (one lost on the way must not turn the result green)."""
    order = names(checks)
    fails = sum(1 for e in entries if e["severity"] == "fail")
    waived = sum(1 for e in entries if e["severity"] == "waived")
    confirms = len(entries) - fails - waived
    if not entries and all(checks[c]["status"] == "pass" for c in order):
        return f"all pass {head}"
    skipped = [c for c in order if checks[c]["status"] == "skipped"]
    na = [c for c in order if checks[c]["status"] == "n/a"]
    partial = [c for c in order if checks[c]["status"] == "partial"]
    unproven = [c for c in order if checks[c]["status"] == "unproven"]  # R0: a case with no fixture (#20)
    ran = [c for c in order if c not in skipped and c not in na]
    counts = f"{fails} fail, {confirms} confirm" + (f", {waived} waived" if waived else "")
    parts = f"{counts}; ran: {' '.join(ran) or 'none'}"
    if partial:
        parts += "; partial: " + " ".join(_partial_label(checks[c], c) for c in partial)
    if unproven:
        parts += f"; unproven: {' '.join(unproven)}"
    if skipped:
        parts += f"; skipped: {' '.join(skipped)}"
    if na:
        parts += f"; n/a: {' '.join(na)}"
    failed = fails or any(checks[c]["status"] == "fail" for c in order)  # a failed check never reads pass
    return f"{'fail' if failed else 'pass'} {head} ({parts})"


def envelope(base, head, entries, checks):
    return {"ekit": ekit_version(), "base": base, "head": head, "checks": checks, "entries": entries,
            "summary": summarize(head, checks, entries)}
