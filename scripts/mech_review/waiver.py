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
# what the sticky comment's ready-made lines say in place of the reason; left in, it is no reason
PLACEHOLDER = "<why this is OK>"


EDITED_WHY = "the comment was edited after posting; post a new comment"
PLACEHOLDER_WHY = "the reason is still the placeholder; post a new comment with the reason"


def _placeholder(reason):
    """True for a reason wholly wrapped in <...>: PLACEHOLDER, or a template's `<reason>`."""
    return reason.startswith("<") and reason.endswith(">")


def _edited(c):
    """True when GitHub moved updated_at past created_at: the comment was edited. Write access lets anyone edit
    another person's comment while the author shown stays the same. A comment missing either stamp counts as unedited."""
    return bool(c.get("created_at") and c.get("updated_at")) and c["created_at"] != c["updated_at"]


def _commands(comments):
    """(comment, login, entry id, reason) per `/mech-waive` line with a reason, from comments by HUMAN authors only.
    The reason has its whitespace collapsed and is not cut yet."""
    for c in comments:
        user = c.get("user") or {}
        if user.get("type") == "Bot" or c.get("author_association") not in HUMAN or not c.get("body"):
            continue
        for m in WAIVE.finditer(c["body"]):
            reason = " ".join(m.group(2).split())
            if reason:
                yield c, user.get("login", ""), m.group(1), reason


def collect(comments):
    """{entry id: {by, reason, url}} from issue comments (API objects, oldest first; a later comment wins).
    A waiver with no reason is ignored: the reason is the record. The placeholder, or any reason wholly in <...>, is
    none. An edited comment waives nothing (see `rejected`)."""
    out = {}
    for c, login, eid, reason in _commands(comments):
        if not _edited(c) and not _placeholder(reason):
            out[eid] = {"by": login, "reason": reason[:REASON_MAX], "url": c.get("html_url", "")}
    return out


def rejected(comments):
    """[{id, by, why, url}]: the waivers `collect` ignored that a person with write access posted, so the comment can
    tell them why. One per entry id, the later comment's. A waiver with no reason at all, or from an outsider or a bot,
    is not listed: it never could waive."""
    out = {}
    for c, login, eid, reason in _commands(comments):
        why = EDITED_WHY if _edited(c) else PLACEHOLDER_WHY if _placeholder(reason) else None
        if why:
            out[eid] = {"id": eid, "by": login, "why": why, "url": c.get("html_url", "")}
    return list(out.values())


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
            c["note"] = "; ".join(x for x in (c.get("note"), f"{n} waived by a person") if x)
    out = dict(env, entries=entries, checks=checks)
    if all(name in checks for name in CHECKS):
        out["summary"] = summarize(env["head"], checks, entries)
    return out
