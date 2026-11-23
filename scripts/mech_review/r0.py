"""R0, the adapter proof (#20, parent #13): the static half. Git and adapter only, no test runner, seconds.

The static half proves that R2 reads the stack the way the rules need, through the adapter's public interface only
(stack.py's docstring; adapter_file.loads for an adapter file):
  cheats    each must give its R2 entry: delete, comment out and rename a test (the core makes these from the seed),
            skip a test, change an expected value, weaken an assert, add a suppression without a reason (fixtures)
  controls  each must give no entry: a rename with the same asserts and reordered asserts (made by the core), asserts
            moved into a helper (a fixture), and R2 on an empty diff of every fixture file
  malformed an adapter file with a bad identifier character set, an empty assert list or unbalanced bracket pairs must
            fail to load cleanly (AdapterFileError), never crash and never load. A built-in has no table: skipped
Fixtures are new files in a throwaway git repo (never patches against real files), at FIXTURE_DIR, a test path for every
stack. A cheat or control with no fixture is `unproven`: the check reads unproven, never pass, and the summary is never
all-pass. A failed case is one `fail` entry of class `adapter-fix` naming every failed case; the checks in BLOCKS (they
read tests through the adapter) are then n/a (blocked), with the cause named. Their entries are kept, marked `blocked`,
and still count: a waiver of the R0 entry never passes them.

Fixture dir (fixtures_dir): files `<case><ext>.r0` (the `.r0` keeps them out of the repo's own checks): `seed<ext>.r0`
and one head file per fixture case (CASES with how == "fixture"). Each fixture case is the seed with one change. The
seed's first line is a line comment: its first word is the opener the comment-out cheat uses. Each test in the seed is
a run of non-blank lines, and one test has two asserts, each on a line of its own (delete, rename and reorder act on it).
Built-in stacks: BUILTIN_FIXTURES/<stack>. An adapter file: `<file without .toml>.r0/` beside it, or --fixtures.

The editing rules (`editing`): a PR may edit an adapter file or the stack plan without a person; R0 judges the adapter
(on the PR's version) and the drift check the plan. Only loosening a limit (LIMITS, the plan's `ignore` list) or
changing a target OS needs a person: one `needs-human` entry naming each. Tightening needs no one.

The runtime half (#21: census, assert density, runner controls, the fingerprint) builds on this module: a new half adds
its cases with its own kind and its own BLOCKS entry; `static` stays git and adapter only.
"""
import importlib.util
import json
import os
import re
import subprocess
import tempfile
from collections import namedtuple

from . import adapter_file, gitio
from .gitio import Review
from .r2 import r2, r2_file
from .report import entry

HALF = "static"
BUILTIN_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r0_fixtures")
SUFFIX = ".r0"
FIXTURE_DIR = ".ekit/scenarios/r0"  # where the fixtures sit in the throwaway repo: a test path for every stack
BLOCKS = {"static": ("R1", "R2", "R4")}  # checks that read tests through the adapter: n/a while the half fails

# what a cheat must give: an R2 entry of this severity whose `forbidden` starts with this text (r2.py's rule)
REMOVED = ("fail", "deleting or renaming a test to hide a failure")
SKIPPED = ("fail", "#[ignore] / skip / xfail / only on a test")
EXPECTED = ("confirm", "editing an expected value to match the code's current output")
WEAKENED = ("confirm", "weakening an assertion in place")
SUPPRESSED = ("fail", "silencing a lint without a reason")

# how: core (made by the core from the seed), fixture (a head file in the fixture dir), every (every fixture file)
Case = namedtuple("Case", "name kind want how")
CASES = (
    Case("delete", "cheat", REMOVED, "core"),
    Case("comment-out", "cheat", REMOVED, "core"),
    Case("rename", "cheat", REMOVED, "core"),  # renamed and an assert dropped: no rename, a removal
    Case("skip", "cheat", SKIPPED, "fixture"),
    Case("expected-value", "cheat", EXPECTED, "fixture"),
    Case("weaken-assert", "cheat", WEAKENED, "fixture"),
    Case("suppression", "cheat", SUPPRESSED, "fixture"),
    Case("rename-same-asserts", "control", None, "core"),
    Case("reorder-asserts", "control", None, "core"),
    Case("helper-asserts", "control", None, "fixture"),
    Case("empty-diff", "control", None, "every"),
)
MALFORMED = ("ident-chars", "empty-asserts", "unbalanced-brackets")

Fixtures = namedtuple("Fixtures", "ext seed cases where")  # cases: {name: head text}; where: the dir, for messages


class FixtureError(ValueError):
    """a fixture dir that cannot be read as one (mixed extensions, unreadable): a usage error naming the file."""


def builtin_fixtures(stack):
    """the fixture dir ekit ships for a built-in stack, or None."""
    d = os.path.join(BUILTIN_FIXTURES, stack)
    return d if os.path.isdir(d) else None


def adapter_fixtures(adapter_path):
    """the default fixture dir of an adapter file: beside it, its name without `.toml` plus `.r0`."""
    stem = adapter_path[:-len(".toml")] if adapter_path.endswith(".toml") else adapter_path
    return stem + SUFFIX


def load_fixtures(path):
    """Fixtures from a dir of `<case><ext>.r0` files, or None when there is no such dir. Names that are not a case of
    CASES (or `seed`) are left out. FixtureError: files with different extensions, or one that does not read."""
    if not path or not os.path.isdir(path):
        return None
    known = {"seed"} | {c.name for c in CASES if c.how == "fixture"}
    exts, texts = set(), {}
    for fn in sorted(os.listdir(path)):
        if not fn.endswith(SUFFIX):
            continue
        name, dot, ext = fn[:-len(SUFFIX)].partition(".")
        if name not in known:
            continue
        exts.add(dot + ext)
        try:
            with open(os.path.join(path, fn), encoding="utf-8", newline="") as f:
                texts[name] = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise FixtureError(f"R0 fixture {os.path.join(path, fn)}: cannot read: {e}") from None
    if len(exts) > 1:
        raise FixtureError(f"R0 fixtures in {path}: one extension for every file, found {', '.join(sorted(exts))}")
    seed = texts.pop("seed", None)
    return Fixtures(exts.pop() if exts else "", seed, texts, path)


def _block(lines, line):
    """(first, last) 0-based indexes of the run of non-blank lines that holds 1-based line."""
    first = last = line - 1
    while first > 0 and lines[first - 1].strip():
        first -= 1
    while last + 1 < len(lines) and lines[last + 1].strip():
        last += 1
    return first, last


def _decl_name(name, line):
    """the longest tail of a test's qualified name that stands as a word on its declaration line, or None."""
    for k in range(len(name)):
        if k and (name[k - 1].isalnum() or name[k - 1] == "_"):
            continue
        tail = name[k:]
        if re.search(r"(?<!\w)" + re.escape(tail) + r"(?!\w)", line):
            return tail
    return None


def made(adapter, seed):
    """({case: head text} of the cases the core makes from the seed, why not or None). The target is the seed's first
    test with two asserts on lines of their own; delete and comment-out act on its run of non-blank lines."""
    if seed is None:
        return {}, "no seed fixture"
    lines = seed.splitlines(keepends=True)
    opener = (lines[0].split() or [""])[0] if lines else ""
    asserts = adapter.assertions(seed)
    for f in adapter.test_fns(seed):
        own = sorted({a.line for a in asserts if a.fn == f.name})
        if len(own) >= 2 and len([a for a in asserts if a.fn == f.name]) == len(own):
            break
    else:
        return {}, "the seed has no test with two asserts on lines of their own"
    tail = _decl_name(f.name, lines[f.line - 1])
    if not opener or tail is None:
        return {}, "the seed's first line is no line comment" if not opener else f"`{f.name}` is not on its own line"
    first, last = _block(lines, f.line)
    out = {}
    out["delete"] = "".join(lines[:first] + lines[last + 1:])
    out["comment-out"] = "".join(ln if not first <= i <= last else f"{opener} {ln}" for i, ln in enumerate(lines))
    renamed = list(lines)
    renamed[f.line - 1] = re.sub(r"(?<!\w)" + re.escape(tail) + r"(?!\w)", lambda m: m.group(0) + "_r0",
                                 renamed[f.line - 1], count=1)
    out["rename-same-asserts"] = "".join(renamed)
    out["rename"] = "".join(ln for i, ln in enumerate(renamed) if i != own[-1] - 1)
    swapped = list(lines)
    a, b = own[0] - 1, own[1] - 1
    swapped[a], swapped[b] = lines[b], lines[a]
    out["reorder-asserts"] = "".join(swapped)
    return out, None


GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "ekit-r0",
           "GIT_AUTHOR_EMAIL": "r0@ekit.invalid", "GIT_COMMITTER_NAME": "ekit-r0", "GIT_COMMITTER_EMAIL": "r0@ekit.invalid"}


def _git(repo, *args):
    """git in the throwaway repo: no user or system config (hooks, signing, templates) reaches it."""
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, env=dict(os.environ, **GIT_ENV))
    if r.returncode:
        raise gitio.Die(r.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return r.stdout.decode("utf-8", "surrogateescape")


def _write(repo, rel, text):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _r2_on(adapter, test_globs, ext, seed, heads):
    """{case: R2 entries} of each head text against the seed, as one PR in a throwaway repo: base holds the seed at
    each case's path, head holds the case's text."""
    with tempfile.TemporaryDirectory(prefix="ekit-r0-") as tmp:
        _git(tmp, "init", "-q", "--template=")
        paths = {c: f"{FIXTURE_DIR}/{c}{ext}" for c in heads}
        for p in paths.values():
            _write(tmp, p, seed)
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "--allow-empty", "--no-verify", "-m", "r0 base")
        mb = _git(tmp, "rev-parse", "HEAD").strip()
        for c, p in paths.items():
            _write(tmp, p, heads[c])
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "--allow-empty", "--no-verify", "-m", "r0 head")
        head = _git(tmp, "rev-parse", "HEAD").strip()
        got = r2(Review(tmp, mb, head, adapter, list(test_globs)), [])
    return {c: [e for e in got if e["file"] == p] for c, p in paths.items()}


def _want_text(want):
    return "no entry" if want is None else f"R2 {want[0]}: {want[1]}"


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json.dumps(k)} = {_toml_value(x)}" for k, x in v.items()) + "}"
    raise TypeError(f"no TOML for {type(v).__name__}")


def toml_text(data):
    """TOML for a dict as tomllib reads it: one `"key" = value` line per top-level key, tables inline."""
    return "".join(f"{json.dumps(k)} = {_toml_value(v)}\n" for k, v in data.items())


def _malformed_variants(data):
    """{case: the adapter file's table with one degenerate field}."""
    def variant(edit):
        d = json.loads(json.dumps(data))
        edit(d)
        return d

    def lexer(d):
        if not isinstance(d.get("lexer"), dict):
            d["lexer"] = {}
        return d["lexer"]

    return {"ident-chars": variant(lambda d: lexer(d).__setitem__("ident_chars", "(")),
            "empty-asserts": variant(lambda d: d.__setitem__("asserts", {})),
            "unbalanced-brackets": variant(lambda d: lexer(d).__setitem__("brackets", ["(", "[]", "{}"]))}


def malformed(adapter_raw, adapter_path):
    """[result] for each MALFORMED case: an adapter file fed one degenerate field must fail to load with an
    AdapterFileError (clean), never another exception (a crash) and never load (passing silently). adapter_raw None
    (a built-in): skipped."""
    if adapter_raw is None:
        return [{"case": c, "kind": "malformed", "status": "skipped", "want": "a clean load error",
                 "got": "a built-in adapter has no adapter file to feed"} for c in MALFORMED]
    try:
        import tomllib
        data = tomllib.loads(adapter_raw.decode("utf-8"))
    except Exception as e:  # the file loaded once already: this is no adapter file R0 can vary
        return [{"case": c, "kind": "malformed", "status": "fail", "want": "a clean load error",
                 "got": f"cannot read the adapter file to vary it: {e}"} for c in MALFORMED]
    out = []
    for c, d in _malformed_variants(data).items():
        try:
            adapter_file.loads(toml_text(d).encode("utf-8"), f"{adapter_path} ({c})")
        except adapter_file.AdapterFileError as e:
            out.append({"case": c, "kind": "malformed", "status": "pass", "want": "a clean load error", "got": str(e)})
        except Exception as e:  # any other exception is the crash this case exists to catch
            out.append({"case": c, "kind": "malformed", "status": "fail", "want": "a clean load error",
                        "got": f"crashed: {type(e).__name__}: {e}"})
        else:
            out.append({"case": c, "kind": "malformed", "status": "fail", "want": "a clean load error",
                        "got": "loaded with no error (passed silently)"})
    return out


def _failure_text(res):
    if res["kind"] == "cheat":
        return f"cheat `{res['case']}` gave no {res['want']} entry"
    if res["kind"] == "control":
        return f"control `{res['case']}` gave {res['got']} (want no entry)"
    return f"malformed input `{res['case']}`: {res['got']}"


def static(adapter, fixtures, test_globs=(), adapter_raw=None, where=""):
    """(R0 check, raw entries) of the static half for one adapter. fixtures: Fixtures or None (every cheat and control
    unproven). adapter_raw: the adapter file's bytes (None: a built-in). where: the adapter's path, the entry's file."""
    globs = list(test_globs) + [FIXTURE_DIR + "/**"]
    seed = fixtures.seed if fixtures else None
    core, why_core = made(adapter, seed)
    heads = dict(core)
    for c in CASES:
        if c.how == "fixture" and fixtures and c.name in fixtures.cases and seed is not None:
            heads[c.name] = fixtures.cases[c.name]
    got = _r2_on(adapter, globs, fixtures.ext, seed, heads) if heads else {}
    results = []
    for c in CASES:
        res = {"case": c.name, "kind": c.kind, "want": _want_text(c.want)}
        if c.how == "every":
            if seed is None:
                res.update(status="unproven", got="no seed fixture")
            else:
                p = f"{FIXTURE_DIR}/seed{fixtures.ext}"
                noisy = [(n, e) for n, t in [("seed", seed)] + sorted(heads.items())
                         for e in r2_file(adapter, globs, p, p, t, t)]
                res.update(status="fail" if noisy else "pass",
                           got=f"{len(noisy)} entries, first on `{noisy[0][0]}`: {noisy[0][1]['problem']}" if noisy
                           else "no entry")
        elif c.name not in heads:
            res.update(status="unproven", got=why_core if c.how == "core" else
                       ("no seed fixture" if seed is None else f"no fixture `{c.name}{fixtures.ext}{SUFFIX}`"))
        else:
            es = got.get(c.name, [])
            if c.want is None:
                res.update(status="fail" if es else "pass",
                           got=f"{len(es)} entries: {es[0]['problem']}" if es else "no entry")
            else:
                hit = [e for e in es if e["severity"] == c.want[0] and e["forbidden"].startswith(c.want[1])]
                res.update(status="pass" if hit else "fail",
                           got=hit[0]["problem"] if hit else ("; ".join(e["problem"] for e in es) or "no entry"))
        results.append(res)
    results += malformed(adapter_raw, where)
    failed = [r for r in results if r["status"] == "fail"]
    unproven = [r for r in results if r["status"] == "unproven"]
    proved = [r for r in results if r["status"] == "pass"]
    judged = len(proved) + len(failed) + len(unproven)
    note = f"static half: {len(proved)} of {judged} cases proved"
    if unproven:
        note += "; unproven (no fixture): " + " ".join(r["case"] for r in unproven)
    if failed:
        note += "; failed: " + " ".join(r["case"] for r in failed)
    check = {"status": "fail" if failed else "unproven" if unproven else "pass", "note": note, "half": HALF,
             "adapter": adapter.name, "cases": results}
    entries = []
    if failed:
        cause = f"R0 static half failed for the `{adapter.name}` adapter: " + "; ".join(_failure_text(r) for r in failed)
        check["blocks"] = list(BLOCKS[HALF])
        check["cause"] = cause
        entries.append(entry("R0", where, 0, "static:" + ",".join(r["case"] for r in failed), "adapter-fix", "fail",
                             cause, "repair the adapter (ci-doctor repair mode) in a PR of its own, then re-run R0; the "
                                    "PR under review never edits its own checker",
                             "tuning the adapter or its fixtures until this PR passes"))
    return check, entries


PLAN = ".ekit/stack-plan.toml"  # stack_plan.PATH (r0 sits below stack_plan in the layering)
# a limit: (which way is looser, its default when a file names none). Spelled with - or _, with or without -threshold,
# at any table level of an adapter file (#13's proposed defaults: max-mutants 40, census 100%, assert density 10%)
LIMITS = {"max-mutants": ("lower", 40), "mutation-budget": ("lower", 10), "census": ("lower", 100),
          "assert-density": ("higher", 10)}


def _limit(key):
    k = key.lower().replace("_", "-")
    k = k[:-len("-threshold")] if k.endswith("-threshold") else k
    return k if k in LIMITS else None


def limits(data, prefix=""):
    """{dotted key: (limit name, value)} of every number a TOML table holds under a LIMITS name, at any depth."""
    out = {}
    items = data.items() if isinstance(data, dict) else enumerate(data) if isinstance(data, list) else ()
    for k, v in items:
        path = f"{prefix}.{k}" if prefix and isinstance(k, str) else f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, (dict, list)):
            out.update(limits(v, path))
        elif isinstance(k, str) and _limit(k) and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[path] = (_limit(k), v)
    return out


def _fmt(v):
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def _looser(base, head):
    """[text] for each limit head loosens against base (a missing limit reads its default)."""
    out = []
    for path in sorted(set(base) | set(head)):
        name = (base.get(path) or head.get(path))[0]
        way, default = LIMITS[name]
        b = base[path][1] if path in base else default
        h = head[path][1] if path in head else default
        if (h < b) if way == "lower" else (h > b):
            out.append(f"`{path}` {_fmt(b)}{'' if path in base else ' (default)'} -> {_fmt(h)}"
                       f"{'' if path in head else ' (default)'}")
    return out


def _blob(repo, sha, path):
    """the file's bytes at sha, or None when it is not a file there."""
    try:
        if gitio.git(repo, "cat-file", "-t", f"{sha}:{path}").strip() != "blob":
            return None
    except gitio.Die:
        return None
    return gitio.blob(repo, sha, path).encode("utf-8", "surrogateescape")


def _toml(raw):
    """the table a TOML file's bytes hold, or None (no file, not TOML: the drift check and R0's proof name those)."""
    if raw is None:
        return None
    try:
        import tomllib
        return tomllib.loads((raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw).decode("utf-8"))
    except (ValueError, RecursionError):  # TOMLDecodeError and UnicodeDecodeError are ValueErrors
        return None


def _stacks(plan):
    return [s for s in (plan or {}).get("stack") or [] if isinstance(s, dict)]


def editing(repo, mb, head, adapter_paths=()):
    """The editing rules: [one needs-human entry] when mb..head loosens a limit or changes a target OS in the stack plan
    or an adapter file (the plan's at either side, and adapter_paths), else []. A file missing on one side is new or
    gone: the drift check judges that. Without tomllib (python < 3.11) a changed plan or adapter file is the entry:
    it cannot be read, so it is never passed silently."""
    raw = {side: {PLAN: _blob(repo, sha, PLAN)} for side, sha in (("base", mb), ("head", head))}
    if importlib.util.find_spec("tomllib") is None:  # the plan and adapter files are TOML
        changed = [p for p in [PLAN, *adapter_paths] if _blob(repo, mb, p) != _blob(repo, head, p)]
        items = [f"{p} changed and cannot be read here (needs python 3.11+ for TOML)" for p in changed]
        return _editing_entry(changed[:1], items)
    plans = {side: _toml(raw[side][PLAN]) for side in raw}
    paths = list(dict.fromkeys([s.get("adapter") for side in plans for s in _stacks(plans[side])
                                if isinstance(s.get("adapter"), str) and ("/" in s["adapter"]
                                                                          or s["adapter"].endswith(".toml"))]
                               + list(adapter_paths)))
    items, files = [], []
    if plans["base"] is not None and plans["head"] is not None:
        b_ign = [str(x).strip("/") for x in plans["base"].get("ignore") or [] if isinstance(x, str)]
        gained = [str(x).strip("/") for x in plans["head"].get("ignore") or []
                  if isinstance(x, str) and str(x).strip("/") not in b_ign]
        items += [f"`ignore` gains `{g}` in {PLAN}" for g in gained]
        b_os = {s.get("name"): s.get("target-os") for s in _stacks(plans["base"])}
        for s in _stacks(plans["head"]):
            if s.get("name") in b_os and s.get("target-os") != b_os[s.get("name")]:
                items.append(f"stack `{s.get('name')}` target-os {b_os[s.get('name')] or 'unset'} -> "
                             f"{s.get('target-os') or 'unset'} in {PLAN}")
        files += [PLAN] if items else []
    for p in paths:
        b, h = _toml(_blob(repo, mb, p)), _toml(_blob(repo, head, p))
        if b is None or h is None:
            continue
        mine = [f"{t} in {p}" for t in _looser(limits(b), limits(h))]
        if b.get("target-os", "linux") != h.get("target-os", "linux"):
            mine.append(f"adapter file {p} target-os {b.get('target-os', 'linux')} -> {h.get('target-os', 'linux')}")
        items += mine
        files += [p] if mine else []
    return _editing_entry(files[:1], items)


def _editing_entry(files, items):
    if not items:
        return []
    return [entry("R0", files[0] if files else PLAN, 0, "loosened:" + "\0".join(items), "needs-human", "fail",
                  "a person decides: " + "; ".join(items),
                  "a looser limit or a new target OS is a person's call: move it to a PR of its own for them to approve "
                  "(a tighter limit needs no one)", "loosening a check's limit or moving its runner to pass the gate")]


def blocked(check, checks):
    """{name: n/a check} for each check in checks ({name: check}) a failed half blocks, its cause named and its own
    result kept under `before`; {} when the half did not fail. A check that did not run (skipped) stays as it is."""
    if check.get("status") != "fail" or not check.get("blocks"):
        return {}
    cause = check.get("cause", check.get("note", ""))
    return {c: {"status": "n/a", "note": f"blocked: R0 failed ({cause})", "before": checks[c]}
            for c in check["blocks"] if c in checks and checks[c].get("status") != "skipped"}


def mark(entries, stop):
    """entries with each one of a blocked check marked `blocked: R0`. Nothing is left out: a blocked check's entries
    still count, so waiving R0 never passes them (each needs its own waiver), and the person deciding sees them all."""
    return [dict(e, blocked="R0") if e.get("check") in stop else e for e in entries]
