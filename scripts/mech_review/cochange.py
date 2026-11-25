"""Co-change rules (#83): "when these paths change, one of those must change too", as data in `.ekit/co-change.toml`.

R2's path rules read the file at the base branch (a PR is judged by the rules it starts from, as by the base's adapter
file) and give one entry per broken rule. Format: docs/mech-review-ci.md#co-change-rules. Every problem with the file is
a RuleFileError that names the field (`rule[1].trigger[0]: want a glob, a non-empty string`), as for an adapter file.
tomllib (python 3.11+) is imported only when the file exists, so a repo without one runs on older pythons.

Proof and guards (#85). Each rule carries two cases, each the paths one PR changes: `flagged`, a PR the rule must flag,
and `control`, one it must leave alone. R0's static half (`prove`) runs both for every rule at the head, each as a PR in
a throwaway repo (the paths seeded on base, changed on head). R2 (`guards`) checks a change to the rule file: the head's
file reads; a new rule's incident resolves to a commit or PR and it has both cases; a rule that fires in the range is
not weakened (lower severity, a trigger glob gone, a require glob added) or removed in it. Adding and promoting a rule
are not guarded."""
import re
import tempfile
from typing import NamedTuple, Tuple

from . import gitio, tomlfile
from .globs import any_glob
from .report import entry

PATH = ".ekit/co-change.toml"
FORMAT = 1
SEVERITIES = ("confirm", "fail")  # a new rule starts at confirm (listed, never blocking); fail is a promotion
TOP_KEYS = ("format", "rule")
CASES = ("flagged", "control")  # the paths of a PR the rule must flag, and of one it must leave alone (#85)
RULE_KEYS = ("id", "trigger", "require", "reason", "severity", "incident") + CASES
RULE_REQUIRED = ("id", "trigger", "require", "reason", "incident")
SILENCING = "editing the co-change rule file to silence the rule that fires"  # the shortcut of a rule that fires
# per case: does the rule's entry show for it, and its verdict when it reads right and when it reads wrong
CASE_READS = {"flagged": (True, "the rule's entry", "gave no entry (want the rule's entry)"),
              "control": (False, "no entry", "gave the rule's entry (want none)")}

class Rule(NamedTuple):
    """one rule. trigger: globs whose change triggers it; require: globs of which at least one must change in the same
    range; incident: the commit or PR of the mistake it came from; flagged and control: its proof cases (CASES), each
    the paths one PR changes, () when the file gives none."""
    id: str
    trigger: Tuple[str, ...]
    require: Tuple[str, ...]
    reason: str
    severity: str
    incident: str
    flagged: Tuple[str, ...] = ()
    control: Tuple[str, ...] = ()


class RuleFileError(gitio.Die):
    """the rule file does not read: a usage error, so every CLI path that runs R2 exits 2 naming the field."""


def _err(field, msg):
    raise RuleFileError(f"{field}: {msg}" if field else msg)


def _text(v, field):
    if not isinstance(v, str) or not v.strip():
        _err(field, "want a non-empty string")
    return v


def _globs(v, field, what="glob"):
    if not isinstance(v, list) or not v:
        _err(field, f"want a list of {what}s (non-empty strings), at least one")
    for i, g in enumerate(v):
        if not isinstance(g, str) or not g:
            _err(f"{field}[{i}]", f"want a {what}, a non-empty string")
    return tuple(v)


def parse(data):
    """the Rules a parsed rule file (a dict, as tomllib reads it) describes, in file order. RuleFileError names the
    field."""
    tomlfile.keys(data, "", TOP_KEYS, ("format",), _err)
    if type(data["format"]) is not int or data["format"] != FORMAT:
        _err("format", f"`{data['format']}`: want {FORMAT}")
    rules = data.get("rule", [])
    if not isinstance(rules, list) or any(not isinstance(r, dict) for r in rules):
        _err("rule", "want an array of tables ([[rule]])")
    out, seen = [], {}
    for i, r in enumerate(rules):
        f = f"rule[{i}]"
        tomlfile.keys(r, f, RULE_KEYS, RULE_REQUIRED, _err)
        rid = _text(r["id"], f + ".id")
        if not all(ch.isalnum() or ch in "_-." for ch in rid):
            _err(f + ".id", f"`{rid}`: want letters, digits, _, - or .")
        if rid in seen:
            _err(f + ".id", f"`{rid}` is already rule[{seen[rid]}].id")
        seen[rid] = i
        severity = r.get("severity", "confirm")
        if severity not in SEVERITIES:
            _err(f + ".severity", f"`{severity}`: want confirm or fail")
        out.append(Rule(rid, _globs(r["trigger"], f + ".trigger"), _globs(r["require"], f + ".require"),
                        _text(r["reason"], f + ".reason"), severity, _text(r["incident"], f + ".incident"),
                        *(_globs(r[c], f"{f}.{c}", "path") if c in r else () for c in CASES)))
    return out


def loads(raw, where):
    """the Rules of a rule file's bytes; where names it in errors (the path, and the commit it is read at)."""
    data = tomlfile.loads(raw, where, RuleFileError, "the co-change rule file")
    try:
        return parse(data)
    except RuleFileError as e:
        raise RuleFileError(f"{where}: {e}") from None


def at(repo, sha):
    """the Rules of the rule file at sha; [] when there is no file there (nothing changes). RuleFileError: it does not
    read, named."""
    try:
        kind = gitio.git(repo, "cat-file", "-t", f"{sha}:{PATH}").strip()
    except gitio.Die:
        return []
    where = f"co-change rule file {PATH} at {sha[:12]}"
    if kind != "blob":
        raise RuleFileError(f"{where}: not a file")
    return loads(gitio.blob(repo, sha, PATH).encode("utf-8", "surrogateescape"), where)


def _names(globs):
    return ", ".join(f"`{g}`" for g in globs)


def _hit(rule, paths):
    """the paths (sorted) that break rule in a range whose changed paths are paths: [] when none matches a trigger glob
    or one matches a require glob."""
    if any(any_glob(p, rule.require) for p in paths):
        return []
    return sorted({p for p in paths if any_glob(p, rule.trigger)})


def check(rules, paths):
    """one R2 entry (not finalized) per rule broken by a range whose changed paths are paths (old and new of each
    change): a path matches a trigger glob and none matches a require glob. File is the rule file and the key the rule
    id, so the entry's id stays the same across heads whichever trigger paths changed."""
    out = []
    for rule in rules:
        hit = _hit(rule, paths)
        if not hit:
            continue
        more = f" and {len(hit) - 1} more" if len(hit) > 1 else ""
        out.append(entry("R2", PATH, 0, f"co-change:{rule.id}", "agent-fixable", rule.severity,
                         f"co-change rule `{rule.id}`: `{hit[0]}`{more} changed, and none of "
                         f"{_names(rule.require)} did: {rule.reason}",
                         f"change one of {_names(rule.require)} in this range as the rule asks (it came from "
                         f"{rule.incident}); a rule that misfires is changed in a PR of its own", SILENCING))
    return out


SHA = re.compile(r"[0-9a-fA-F]{7,40}")
PR = re.compile(r"#[1-9][0-9]*")


def resolves(repo, head, incident):
    """does incident name a commit head reaches (its sha, 7 to 40 hex digits), or a PR (`#N`) that the message of a
    commit head reaches names (a merge or squash commit names its PR)? Offline: git only."""
    if SHA.fullmatch(incident):
        try:
            sha = gitio.git(repo, "rev-parse", "--verify", "-q", incident + "^{commit}").strip()
            gitio.git(repo, "merge-base", "--is-ancestor", sha, head)
        except gitio.Die:
            return False
        return True
    if PR.fullmatch(incident):
        log = gitio.git(repo, "log", "-F", f"--grep={incident}", "--format=%B", head)
        return re.search(re.escape(incident) + r"(?![0-9])", log) is not None
    return False


def _weaker(old, new):
    """how new (None: gone) weakens old, or None: a lower severity, a trigger glob gone, a require glob added. Globs
    are compared as text, whatever they match."""
    if new is None:
        return "removes it"
    why = []
    if SEVERITIES.index(new.severity) < SEVERITIES.index(old.severity):
        why.append(f"severity {old.severity} -> {new.severity}")
    lost = [g for g in old.trigger if g not in new.trigger]
    if lost:
        why.append(f"trigger loses {_names(lost)}")
    gained = [g for g in new.require if g not in old.require]
    if gained:
        why.append(f"require gains {_names(gained)}")
    return f"weakens it ({'; '.join(why)})" if why else None


def guards(repo, mb, head, rules, paths):
    """R2's guards (#85) when the range mb..head changes the rule file (paths: its changed paths), as raw entries: the
    file at head does not read (agent-fixable); a new rule (an id mb has not) whose incident resolves to no commit or
    PR, or that lacks a case (agent-fixable); a rule of rules (the base's, which judge the range) that fires in the
    range and that the range weakens or removes against mb's version (needs-human). Adding and promoting a rule give
    none. RuleFileError: the file at mb does not read."""
    if PATH not in paths:
        return []
    try:
        now = {r.id: r for r in at(repo, head)}
    except RuleFileError as e:
        return [entry("R2", PATH, 0, "co-change-file", "agent-fixable", "fail",
                      f"the co-change rule file this range writes does not read: {e}",
                      "fix the field it names; the rule file is read at the base for every PR after this one",
                      "deleting the rule file to make the check pass")]
    was = {r.id: r for r in at(repo, mb)}
    out = []
    for r in now.values():
        if r.id in was:
            continue
        if not resolves(repo, head, r.incident):
            out.append(entry("R2", PATH, 0, f"co-change-incident:{r.id}", "agent-fixable", "fail",
                             f"new co-change rule `{r.id}`: incident `{r.incident}` resolves to no commit or PR (want a "
                             f"commit the head reaches, or `#N` that the message of a commit the head reaches names)",
                             "name the commit (its sha) or the PR (`#N`) of the mistake the rule came from, one the "
                             "history of this branch holds", "naming an incident the rule did not come from"))
        missing = [f"no `{c}` case" for c in CASES if not getattr(r, c)]
        if missing:
            out.append(entry("R2", PATH, 0, f"co-change-cases:{r.id}", "agent-fixable", "fail",
                             f"new co-change rule `{r.id}` has " + " and ".join(missing),
                             "add the case: the paths of a PR the rule must flag (`flagged`) or must leave alone "
                             "(`control`); R0 runs both", "a case that does not show the mistake the rule is for"))
    for rule in rules:
        why = _weaker(was[rule.id], now.get(rule.id)) if rule.id in was and _hit(rule, paths) else None
        if why:
            out.append(entry("R2", PATH, 0, f"co-change-weakened:{rule.id}", "needs-human", "fail",
                             f"co-change rule `{rule.id}` fires in this range, and this range {why}",
                             "a person decides: keep the rule as the merge base has it in this PR, and weaken or "
                             "remove it in a PR of its own", SILENCING))
    return out


def _changed(repo, blobs, paths):
    """the paths the PR changes when each of paths holds blobs[0] on base and blobs[1] on head: two trees built in the
    throwaway repo's index, never files on disk. Git leaves out a path it cannot take (`..`, `.git`) and keeps the last
    of a file and a folder of the same name, so a case that does not build as given shows here. One index serves every
    case: the paths of the cases before are the same in both trees, so they are no change."""
    trees = []
    for blob in blobs:
        gitio.git(repo, "update-index", "-z", "--add", "--index-info",
                  data=b"".join(f"100644 {blob}\t{p}\0".encode("utf-8", "surrogateescape") for p in paths))
        trees.append(gitio.git(repo, "write-tree").strip())
    return sorted({p for ch in gitio.changes(repo, *trees) for p in (ch.old, ch.new) if p})


def _proof(rule, repo, blobs):
    """[(case, status, why)] of one rule's two cases."""
    out = []
    for case in CASES:
        paths = getattr(rule, case)
        if not paths:
            out.append((case, "fail", f"no `{case}` case"))
            continue
        changed = _changed(repo, blobs, paths)
        if changed != sorted(set(paths)):
            out.append((case, "fail", f"`{case}` case ({_names(paths)}) builds a PR that changes "
                                      f"{_names(changed) or 'no path'} (want each path as given: a repo path, no `.` "
                                      f"or `..` segment)"))
        else:
            want, right, wrong = CASE_READS[case]
            if bool(_hit(rule, changed)) == want:
                out.append((case, "pass", right))
            else:
                out.append((case, "fail", f"`{case}` case ({_names(paths)}) {wrong}"))
    return out


def prove(repo, head):
    """R0's co-change part (#85): every rule of the rule file at head (the PR's version, as R0 proves the PR's adapter)
    against its two cases, each a PR in a throwaway repo. ({status, note, cases}, raw entries): one R0 `fail` entry per
    rule that fails its proof (a case missing, or one that reads wrong), class agent-fixable; it blocks no check. A file
    that does not read leaves the rules unproven (R2's guard names it). (None, []) with no rule at head."""
    try:
        rules = at(repo, head)
    except RuleFileError as e:
        return {"status": "unproven", "note": f"co-change rules unproven: {e}", "cases": []}, []
    if not rules:
        return None, []
    cases, entries, bad = [], [], []
    with tempfile.TemporaryDirectory(prefix="ekit-r0-cochange-") as tmp:
        gitio.git(tmp, "init", "-q", "--bare", "--template=")
        blobs = [gitio.git(tmp, "hash-object", "-w", "--stdin", data=text).strip() for text in (b"seed\n", b"case\n")]
        for rule in rules:
            got = _proof(rule, tmp, blobs)
            cases += [{"case": f"{rule.id}:{c}", "kind": "co-change", "status": status, "got": why}
                      for c, status, why in got]
            failed = [why for _, status, why in got if status == "fail"]
            if failed:
                bad.append(rule.id)
                entries.append(entry("R0", PATH, 0, f"co-change-proof:{rule.id}", "agent-fixable", "fail",
                                     f"co-change rule `{rule.id}` fails its proof: " + "; ".join(failed),
                                     "give the rule a `flagged` case (the paths of a PR it must flag) and a `control` "
                                     "case (the paths of a PR it must leave alone), and fix the rule or the case that "
                                     "reads wrong", "rewriting a case to match what the rule does, not what it is for"))
    note = f"co-change rules: {len(rules) - len(bad)} of {len(rules)} proved" + (
        "; failed: " + " ".join(bad) if bad else "")
    return {"status": "fail" if bad else "pass", "note": note, "cases": cases}, entries
