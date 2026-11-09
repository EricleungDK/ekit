"""Human waivers: a `/mech-waive <id> <reason>` PR comment from a person with write access lets one fail entry through.

Applied by the report step only (mech-comment.py), from the PR's comments, never from the PR's own content (body,
commits, files): those are what the checks judge. An entry keeps everything but its severity, which becomes `waived`,
and gains `waiver: {by, reason, url}`. A waiver is per entry id, so it holds across pushes while the same rule breaks
on the same test or file, and stops applying when the id is gone. CI entries (no result) cannot be waived.
Stdlib only.
"""
import re

from .report import CHECKS, summarize

WAIVE = re.compile(r"^[ \t]*/mech-waive[ \t]+(R[1-4]-[0-9a-f]{8})\b[ \t:,-]*(.*)$", re.M)
# who may waive: the repo's own people. A bot, a first-time contributor or an outsider cannot.
HUMAN = ("OWNER", "MEMBER", "COLLABORATOR")
REASON_MAX = 300


def collect(comments):
    """{entry id: {by, reason, url}} from issue comments (API objects, oldest first; a later comment wins).
    A waiver with no reason is ignored: the reason is the record."""
    out = {}
    for c in comments:
        user = c.get("user") or {}
        if user.get("type") == "Bot" or c.get("author_association") not in HUMAN:
            continue
        for m in WAIVE.finditer(c.get("body") or ""):
            reason = " ".join(m.group(2).split())[:REASON_MAX]
            if reason:
                out[m.group(1)] = {"by": user.get("login", ""), "reason": reason, "url": c.get("html_url", "")}
    return out


def apply(env, waivers):
    """The envelope with each waived fail entry marked. A check whose fail entries are all waived reads `waived`
    (it ran and the rule broke; a person let it through). The summary is rebuilt. No waiver that fits: env unchanged."""
    hit = [e for e in env["entries"] if e["severity"] == "fail" and e.get("check") in CHECKS and e["id"] in waivers]
    if not hit:
        return env
    ids = {e["id"] for e in hit}
    entries = [dict(e, severity="waived", waiver=waivers[e["id"]]) if e["id"] in ids and e["severity"] == "fail" else e
               for e in env["entries"]]
    checks = {name: dict(c) for name, c in (env.get("checks") or {}).items()}
    for name in CHECKS:
        c = checks.get(name)
        mine = [e for e in entries if e.get("check") == name]
        n = sum(1 for e in mine if e["severity"] == "waived")
        if c and n and c.get("status") == "fail" and not any(e["severity"] == "fail" for e in mine):
            c["status"] = "waived"
            c["note"] = f"{c.get('note', '')}; {n} waived by a person".lstrip("; ")
    out = dict(env, entries=entries, checks=checks)
    if all(name in checks for name in CHECKS):
        out["summary"] = summarize(env["head"], checks, entries)
    return out
