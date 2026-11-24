"""Co-change rules (#83): "when these paths change, one of those must change too", as data in `.ekit/co-change.toml`.

R2's path rules read the file at the base branch (a PR is judged by the rules it starts from, as by the base's adapter
file) and give one entry per broken rule. Format: docs/mech-review-ci.md#co-change-rules. Every problem with the file is
a RuleFileError that names the field (`rule[1].trigger: want a list of non-empty strings`), as for an adapter file.
tomllib (python 3.11+) is imported only when the file exists, so a repo without one runs on older pythons."""
from collections import namedtuple

from . import gitio
from .globs import any_glob
from .report import entry

PATH = ".ekit/co-change.toml"
FORMAT = 1
SEVERITIES = ("confirm", "fail")  # a new rule starts at confirm (listed, never blocking); fail is a promotion
TOP_KEYS = ("format", "rule")
RULE_KEYS = ("id", "trigger", "require", "reason", "severity", "incident")
RULE_REQUIRED = ("id", "trigger", "require", "reason", "incident")

# trigger: globs whose change triggers the rule; require: globs of which at least one must change in the same range;
# incident: the commit or PR of the mistake the rule came from
Rule = namedtuple("Rule", "id trigger require reason severity incident")


class RuleFileError(gitio.Die):
    """the rule file does not read: a usage error, so every CLI path that runs R2 exits 2 naming the field."""


def _err(field, msg):
    raise RuleFileError(f"{field}: {msg}" if field else msg)


def _keys(d, field, allowed, required):
    for k in d:
        if k not in allowed:
            _err(f"{field}.{k}" if field else k, "unknown key")
    for k in required:
        if k not in d:
            _err(f"{field}.{k}" if field else k, "missing")


def _text(v, field):
    if not isinstance(v, str) or not v.strip():
        _err(field, "want a non-empty string")
    return v


def _globs(v, field):
    if not isinstance(v, list) or not v:
        _err(field, "want a list of globs (non-empty strings), at least one")
    for i, g in enumerate(v):
        if not isinstance(g, str) or not g:
            _err(f"{field}[{i}]", "want a glob, a non-empty string")
    return tuple(v)


def parse(data):
    """the Rules a parsed rule file (a dict, as tomllib reads it) describes, in file order. RuleFileError names the
    field."""
    _keys(data, "", TOP_KEYS, ("format",))
    if type(data["format"]) is not int or data["format"] != FORMAT:
        _err("format", f"`{data['format']}`: want {FORMAT}")
    rules = data.get("rule", [])
    if not isinstance(rules, list) or any(not isinstance(r, dict) for r in rules):
        _err("rule", "want an array of tables ([[rule]])")
    out, seen = [], {}
    for i, r in enumerate(rules):
        f = f"rule[{i}]"
        _keys(r, f, RULE_KEYS, RULE_REQUIRED)
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
                        _text(r["reason"], f + ".reason"), severity, _text(r["incident"], f + ".incident")))
    return out


def loads(raw, where):
    """the Rules of a rule file's bytes; where names it in errors (the path, and the commit it is read at)."""
    try:
        import tomllib
    except ImportError:
        raise RuleFileError(f"{where}: reading the co-change rule file needs python 3.11 or newer (tomllib)") from None
    try:
        data = tomllib.loads((raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw).decode("utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise RuleFileError(f"{where}: not valid TOML: {e}") from None
    except UnicodeDecodeError as e:  # tomllib decodes the bytes as UTF-8 and lets this through
        raise RuleFileError(f"{where}: not valid TOML: not UTF-8 ({e.reason} at byte {e.start})") from None
    except RecursionError:  # tomllib nests one python frame per array or inline table
        raise RuleFileError(f"{where}: not valid TOML: arrays or tables nested too deep") from None
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


def check(rules, paths):
    """one R2 entry (not finalized) per rule broken by a range whose changed paths are paths (old and new of each
    change): a path matches a trigger glob and none matches a require glob. File is the rule file and the key the rule
    id, so the entry's id stays the same across heads whichever trigger paths changed."""
    paths = sorted(set(paths))
    out = []
    for rule in rules:
        hit = [p for p in paths if any_glob(p, rule.trigger)]
        if not hit or any(any_glob(p, rule.require) for p in paths):
            continue
        more = f" and {len(hit) - 1} more" if len(hit) > 1 else ""
        out.append(entry("R2", PATH, 0, f"co-change:{rule.id}", "agent-fixable", rule.severity,
                         f"co-change rule `{rule.id}`: `{hit[0]}`{more} changed, and none of "
                         f"{_names(rule.require)} did: {rule.reason}",
                         f"change one of {_names(rule.require)} in this range as the rule asks (it came from "
                         f"{rule.incident}); a rule that misfires is changed in a PR of its own",
                         "editing the co-change rule file to silence the rule that fires"))
    return out
