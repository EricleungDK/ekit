"""R3 through an adapter file's declared mutation tool (#19): [mutation.tool]'s command runs on the changed lines and its
report is read by its format, not by the tool: mutation-testing-elements JSON (the Stryker family, mull), PIT's
mutations.xml, or a line pattern with named groups. With no tool declared, R3 is n/a (NoTool).

Its own module, beside mutants.py (the built-in stacks' tools), whose helpers it uses: mutmut mutates every changed file
whole and writes each mutant as a full copy of its function, so a PR that edits mutants.py pays for all of it (python
3.14's parser is superlinear on that file). Functions here stay short for the same reason. cli.py runs it for an
adapter file (mutants, baseline); the built-ins keep mutants.run.
"""
import json
import os
import posixpath
import re
import shlex
import shutil
import stat
import time
from collections import namedtuple

from . import adapter_file, red
from .gitio import added_lines, git
from .mutants import (DEFAULT_MAX_MUTANTS, HOW, PROBE_TIMEOUT, _check, _crate_path, _files_baseline, _first_line,
                      _payload, _repo_path, _under, crate_check, default_runner, line_ranges, partial_entry, shard_files,
                      shard_index, stryker_desc)
from .report import entry, finalize

MAX_REPORT_BYTES = 64 * 1024 * 1024  # a report larger than this is not read (n/a): no tool's real report comes near it
# Found: one mutant of a report. file: crate-relative path (suffix True: a path tail, PIT's package path), or None for a
# file outside the crate; line: 1-based, or None (unlocated); kind: missed, caught, timeout, unviable, ignored (not
# R3's: the tool's own config or a comment turned it off), pending (never run: untested); fix: survived | nocoverage
# (missed only: the hint); desc: stable across line moves (no line number in it, where the format allows).
Found = namedtuple("Found", "file line kind desc fix suffix silent", defaults=(False,))
ELEMENTS_KIND = {"Killed": ("caught", None), "Survived": ("missed", "survived"), "NoCoverage": ("missed", "nocoverage"),
                 "Timeout": ("timeout", None), "CompileError": ("unviable", None), "RuntimeError": ("unviable", None),
                 "Ignored": ("ignored", None), "Pending": ("pending", None)}
PIT_KIND = {"KILLED": ("caught", None), "SURVIVED": ("missed", "survived"), "NO_COVERAGE": ("missed", "nocoverage"),
            "TIMED_OUT": ("timeout", None), "NON_VIABLE": ("unviable", None), "MEMORY_ERROR": ("unviable", None),
            "RUN_ERROR": ("unviable", None), "STARTED": ("pending", None), "NOT_STARTED": ("pending", None)}
XML_DECL = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.I)
XML_ENCODING = re.compile(rb"""^\s*<\?xml\b[^>]*?\bencoding\s*=\s*["']([^"']*)["']""")
DIGITS = re.compile(r"[0-9]+")  # a line number: ASCII digits only (str.isdigit takes `²`, which int() refuses)


class ReportError(ValueError):
    """the report is not one of its format's: R3 reads it as n/a (env), never as a pass."""


def _text(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ReportError(f"not UTF-8 ({e.reason} at byte {e.start})") from None


def _report_path(name, crate):
    """a file the report names, as a crate-relative posix path; None when it is outside the crate."""
    p = name.replace("\\", "/")
    if p.startswith("/") or re.match(r"^[A-Za-z]:/", p):
        root = crate.replace("\\", "/").rstrip("/") + "/"
        if not p.startswith(root):
            return None
        p = p[len(root):]
    p = posixpath.normpath(p)
    return None if p == ".." or p.startswith("../") or p.startswith("/") else p


def _line(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else None


MAX_JSON_DEPTH = 64  # the elements report nests about 6 deep; deeper is refused by the reader, not by the interpreter
JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
JSON_BRACKET = re.compile(r"[\[\]{}]")


def _too_deep(text):
    """True when the JSON text's arrays and objects nest more than MAX_JSON_DEPTH deep (brackets in strings are text).
    Python's own limit depends on the interpreter and its stack (3.14 parses 100000 levels on one runner and raises
    RecursionError on another), so the reader keeps its own: the same answer on every machine."""
    depth = 0
    for m in JSON_BRACKET.finditer(JSON_STRING.sub("", text)):
        depth += 1 if m.group() in "[{" else -1
        if depth > MAX_JSON_DEPTH:
            return True
    return False


def read_elements(raw, crate):
    """(mutants, silent) of a mutation-testing-elements JSON report (Stryker, Stryker.NET, mull). silent: Survived
    mutants a test covers that completed no test (the runner never ran them: not a result)."""
    text = _text(raw)
    if _too_deep(text):
        raise ReportError(f"not JSON: nested too deep (more than {MAX_JSON_DEPTH} levels)")
    try:
        doc = json.loads(text)
    except RecursionError:
        raise ReportError("not JSON: nested too deep") from None
    except ValueError as e:
        raise ReportError(f"not JSON: {e}") from None
    if not isinstance(doc, dict):
        raise ReportError("not a JSON object")
    files = doc.get("files")
    if not isinstance(files, dict):
        raise ReportError("no files object")
    out, silent = [], 0
    for name, res in files.items():
        if not isinstance(res, dict) or not isinstance(res.get("mutants"), list):
            raise ReportError(f"`{name}`: no mutants list")
        src = res.get("source") if isinstance(res.get("source"), str) else ""
        path = _report_path(name, crate)
        for m in res["mutants"]:
            if not isinstance(m, dict):
                raise ReportError(f"a mutant in `{name}` is not an object")
            status = m.get("status")
            if not isinstance(status, str) or status not in ELEMENTS_KIND:
                raise ReportError(f"a mutant in `{name}` has status `{status}`: want one of " + ", ".join(ELEMENTS_KIND))
            kind, fix = ELEMENTS_KIND[status]
            loc = m.get("location") if isinstance(m.get("location"), dict) else {}
            start = loc.get("start") if isinstance(loc.get("start"), dict) else {}
            quiet = bool(status == "Survived" and m.get("coveredBy") and not m.get("testsCompleted"))
            silent += quiet
            out.append(Found(path, _line(start.get("line")), kind, stryker_desc(m, src), fix, False, quiet))
    return out, silent


def _child_text(el, tag):
    c = el.find(tag)
    return (c.text or "").strip() if c is not None else None


def read_pit(raw):
    """the mutants of PIT's mutations.xml. A DTD or an entity declaration is refused before parsing (no XXE, no entity
    expansion). PIT names a file by its package and file name: the path is that tail (suffix), matched to the diff."""
    import xml.etree.ElementTree as ET
    _text(raw)  # UTF-8 only: a wide encoding (UTF-16, UTF-32) would hide a declaration from the byte check below
    if b"\x00" in raw:
        raise ReportError("not UTF-8 (a NUL byte: a wide encoding)")
    if XML_DECL.search(raw):
        raise ReportError("has a DTD or an entity declaration: refused")
    enc = XML_ENCODING.match(raw.lstrip(b"\xef\xbb\xbf"))
    if enc and enc.group(1).lower() not in (b"utf-8", b"utf8"):  # utf-7 would hide a declaration from the check above
        raise ReportError(f"declares encoding `{enc.group(1).decode('ascii', 'replace')}`: want UTF-8")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError) as e:  # ValueError: an encoding expat cannot read (multi-byte)
        raise ReportError(f"not XML: {e}") from None
    if root.tag != "mutations":
        raise ReportError(f"root is <{root.tag}>, not <mutations>")
    out = []
    for i, el in enumerate(root, 1):
        if el.tag != "mutation":
            raise ReportError(f"<{el.tag}> in <mutations>: want <mutation> only")
        status = el.get("status")
        if status not in PIT_KIND:
            raise ReportError(f"mutation {i} has status `{status}`: want one of " + ", ".join(PIT_KIND))
        src, cls = _child_text(el, "sourceFile"), _child_text(el, "mutatedClass")
        if not src:
            raise ReportError(f"mutation {i} has no sourceFile")
        if "/" in src or "\\" in src or src in (".", ".."):
            raise ReportError(f"mutation {i} has sourceFile `{src}`: want a file name")
        if not cls:
            raise ReportError(f"mutation {i} has no mutatedClass")
        pkg = cls.rpartition(".")[0]
        path = (pkg.replace(".", "/") + "/" if pkg else "") + src
        ln = _child_text(el, "lineNumber") or ""
        line = int(ln) if DIGITS.fullmatch(ln) and int(ln) >= 1 else None
        kind, fix = PIT_KIND[status]
        mutator = (_child_text(el, "mutator") or "").rpartition(".")[2]
        desc = f"{mutator} in {_child_text(el, 'mutatedMethod') or '?'}: {_child_text(el, 'description') or ''}".strip()
        out.append(Found(path, line, kind, desc, fix, True))
    return out


def read_lines(raw, tool, crate):
    """the mutants a line pattern reads from a report (or the tool's output): named groups file, line, status, and desc
    when the pattern has one (else the matched text). A status word maps to missed, caught, timeout or unviable by
    mutation.tool.status; one in no list is refused. A zero-width match never counts (#18)."""
    text = _text(raw)
    rx = tool["pattern_rx"]
    words = {w: k for k, ws in tool["status"].items() for w in ws}
    out = []
    n, at = 1, 0  # the line number at offset `at`, advanced with the matches (one pass over the text)
    for m in (m for m in rx.finditer(text) if m.end() > m.start()):
        n += text.count("\n", at, m.start())
        at = m.start()
        for g in ("file", "line", "status"):
            if m.group(g) is None:
                raise ReportError(f"line {n}: the pattern matched without its {g} group")
        if not DIGITS.fullmatch(m.group("line")) or int(m.group("line")) < 1:
            raise ReportError(f"line {n}: line `{m.group('line')}` is not a whole number >= 1")
        kind = words.get(m.group("status"))
        if kind is None:
            raise ReportError(f"line {n}: status `{m.group('status')}` is in no mutation.tool.status list")
        desc = m.group("desc") if "desc" in rx.groupindex and m.group("desc") is not None else None
        out.append(Found(_report_path(m.group("file"), crate), int(m.group("line")), kind,
                         " ".join((desc if desc is not None else m.group(0)).split()),
                         "survived" if kind == "missed" else None, False))
    return out


def read_report(tool, raw, crate):
    """(mutants, silent) of a report in the tool's format; ReportError when it is not one."""
    if len(raw) > MAX_REPORT_BYTES:
        raise ReportError(f"more than {MAX_REPORT_BYTES} bytes")
    if tool["format"] == "mutation-testing-elements":
        return read_elements(raw, crate)
    if tool["format"] == "pit-xml":
        return read_pit(raw), 0
    return read_lines(raw, tool, crate), 0


def _tracked_at(repo, head):
    return [p for p in git(repo, "ls-tree", "-r", "-z", "--full-tree", "--name-only", head).split("\0") if p]


def _locate(found, project_dir, tracked):
    """(repo path, why) of a report's mutant: why None (located), "outside" (path None: a file outside the crate), or
    "unlocated" (no line, or a PIT path tail that several tracked files under the crate end with: the path is the
    first of them, so one shard counts it). A tail no tracked file ends with is outside."""
    if found.file is None:
        return None, "outside"
    if not found.suffix:
        return _repo_path(project_dir, found.file), None if found.line is not None else "unlocated"
    hits = sorted(p for p in tracked if _under(p, project_dir)
                  and (_crate_path(project_dir, p) == found.file or p.endswith("/" + found.file)))
    if not hits:
        return None, "outside"
    return hits[0], None if len(hits) == 1 and found.line is not None else "unlocated"



Run = namedtuple("Run", "rv tool cmd base prog prod files changed shard budget mutant_timeout runner")


class DeclaredTool:
    """R3 through an adapter file's [mutation.tool] (#19): the declared command runs on the changed lines (`{mutate}`:
    one `mutate` range per run of changed lines of this shard's files) in a worktree at head, and the report it writes
    is read by its format. MISSED mutants on changed lines are fails, the rest counted. As for Stryker: shards by changed
    production file, mutation-budget stops the run (partial, never a pass), Pending mutants are untested. The tool lists
    no mutant before its run, so max-mutants is not applied: the note says so. mutation.tool.runners (per
    [[run.runner]]): what the runner needs in the project dir, and when the project has none of [mutation].config_files,
    the args added and the config file written (into the worktree; the caller's checkout is never written)."""

    def __init__(self, tool):
        self.t = tool

    def baseline(self, rv, cmd, budget_min, shards, runner=None, max_mutants=DEFAULT_MAX_MUTANTS):
        return _files_baseline(rv, shards)

    def check(self, rv, cmd, budget_min, shard, mutant_timeout, runner, max_mutants=DEFAULT_MAX_MUTANTS):
        r = _start(self.t, rv, cmd, budget_min, shard, mutant_timeout, runner)
        if not isinstance(r, Run):
            return r
        with red.worktree(rv.repo, rv.head) as wt:
            return _in_worktree(r, wt)


def _not_installed(t, cmd):
    return _check("n/a", f"{t['name']} not installed (env): `{cmd}` not runnable (mutation.tool.command); "
                         "install it (setup-command) or set mutants-cmd"), []


def _start(t, rv, cmd, budget_min, shard, mutant_timeout, runner):
    """the run's inputs (a Run), or the result when it ends before a worktree: the OS check, the program lookup."""
    adapter, project_dir = rv.adapter, rv.project_dir
    if adapter.target_os not in t["os"]:
        return _check("n/a", f"{t['name']} does not run on {adapter.target_os} (env): mutation.tool.os lists "
                             f"{', '.join(t['os'])}; the stack's target-os is {adapter.target_os}"), []
    cmd = cmd or t["command"]
    try:
        base = shlex.split(cmd)
    except ValueError:
        base = []
    prog = _program_path(base[0]) if base else None
    if prog is None:
        return _not_installed(t, cmd)
    prod = sorted({ch.new for ch in red.prod_changes(rv) if ch.new and _under(ch.new, project_dir)})
    return Run(rv, t, cmd, [prog] + base[1:], prog, prod, shard_files(prod, shard), added_lines(rv.repo, rv.mb, rv.head),
               shard, None if budget_min is None else budget_min * 60, mutant_timeout, runner)


def _in_worktree(r, wt):
    """the steps in the worktree at head: crate, program guards, probe, runner extras, ranges, the run, its report."""
    crate, bad = crate_check(r.rv, wt)
    if bad:
        return bad
    if not r.files:
        return _check("pass", "0 mutants in the diff (no changed production file in this shard)", 0, 0), []
    stop = _guard_program(r, wt)
    if stop:
        return stop
    r.rv.adapter.worktree_setup(r.rv.repo, wt, r.rv.project_dir)
    stop = _probe(r, crate)
    if stop:
        return stop
    extra, stop = _runner_extra(r, crate)
    if stop:
        return stop
    ranges, stop = _ranges(r)
    if stop:
        return stop
    return _run_tool(r, wt, crate, extra, ranges)


def _guard_program(r, wt):
    """a fail (needs-human) when the program is an interpreter, shell or launcher, or lies in the reviewed checkout."""
    word = shlex.split(r.cmd)[0]
    if any(adapter_file.launcher(w) for w in (word, r.prog, os.path.realpath(r.prog))):
        problem = (f"the mutation tool `{word}` ({os.path.realpath(r.prog)}) is an interpreter, shell or launcher: "
                   "mutants not run")
        return _check("fail", problem), finalize([entry(
            "R3", "", 0, "tool-launcher", "needs-human", "fail", problem,
            "install the tool as a program of its own on PATH (setup-command) or pass mutants-cmd: a launcher "
            "runs what it is given, which can be a file the PR under review changes",
            "running a mutation tool through an interpreter, shell or launcher")])
    # R0's R3 control (#21) runs in a throwaway repo: the reviewed checkout rides in as the adapter's checkout_roots
    inside = _in_checkout(r.prog, (r.rv.repo, wt) + tuple(getattr(r.rv.adapter, "checkout_roots", ())))
    if inside:
        problem = (f"the mutation tool `{word}` resolves to {r.prog} ({inside}), in the reviewed checkout: mutants "
                   "not run")
        return _check("fail", problem), finalize([entry(
            "R3", "", 0, "tool-in-checkout", "needs-human", "fail", problem,
            "install the tool outside the checkout (setup-command, into the runner's temp dir) and put that on "
            "PATH, or pass mutants-cmd: the PR under review must not supply the program that judges it",
            "running a mutation tool the PR can change")])
    return None


def _probe(r, crate):
    """the version probe, when declared: a failing one is not installed."""
    t = r.tool
    if t["version"] is None:
        return None
    rc, text = r.runner(r.base + t["version"], crate, PROBE_TIMEOUT)
    if rc != 0 or (t["version_rx"] is not None and not _matched(t["version_rx"], text)):
        return _not_installed(t, r.cmd)
    return None


def _runner_extra(r, crate):
    """(the mutation.tool.runners table of the crate's runner or {}, None), or (None, n/a) when what it needs is missing."""
    runners = r.tool["runners"]
    name = r.rv.adapter.runner_name(crate) if runners else None
    extra = runners.get(name, {}) if name else {}
    if extra.get("needs") and not os.path.isfile(os.path.join(crate, extra["needs"])):
        return None, (_check("n/a", f"{name} not installed (env): `{extra['needs']}` not runnable "
                                    f"(mutation.tool.runners.{name}.needs); install the project's dependencies "
                                    "(setup-command)"), [])
    return extra, None


def _ranges(r):
    """(the `mutate` ranges of the shard's changed lines, None), or (None, the result): a file name holding mutate_join,
    or no range at all (pass)."""
    t = r.tool
    ranges = []
    for f in r.files:
        crate_f = _crate_path(r.rv.project_dir, f)
        if "mutate" in t and t["mutate_join"] in crate_f:
            return None, (_check("n/a", f"{f}: a file name with `{t['mutate_join']}` in it cannot be passed to "
                                        f"{t['name']} (env): mutation.tool.mutate_join"), [])
        module = module_name(t, crate_f)
        if module == "":
            return None, (_check("n/a", f"{f}: under none of mutation.tool.module_roots ({', '.join(t['module_roots'])}), "
                                        f"so it has no `{{module}}` to pass to {t['name']} (env)"), [])
        for a, _, b in (x.partition("-") for x in line_ranges(ln for ln, _ in r.changed.get(f, []))):
            ranges.append(t["mutate"].format(file=crate_f, first=a, last=b, module=module) if "mutate" in t else crate_f)
    if "mutate" in t and not ranges:
        return None, (_check("pass", "0 mutants in the diff", 0, 0), [])
    return ranges, None


def module_name(t, path):
    """`{module}` of a project-dir relative path (#22): the path under the first of mutation.tool.module_roots that
    holds it, its extension dropped, `/` as `.` (src/main/java/com/x/Calc.java -> com.x.Calc). "" when no root holds
    it; None when mutate has no `{module}`."""
    roots = t.get("module_roots")
    if not roots:
        return None
    for root in roots:
        if path.startswith(root + "/"):
            return os.path.splitext(path[len(root) + 1:])[0].replace("/", ".")
    return ""


def _argv(r, extra, ranges, config):
    """the tool's argv: the program and args with their placeholders; the runner's args with no repo config."""
    t = r.tool
    secs = t["timeout"] if r.mutant_timeout is None else r.mutant_timeout
    words = {"mutate": t["mutate_join"].join(dict.fromkeys(ranges)), "timeout_ms": str(secs * 1000),
             "timeout_s": str(secs), "report": t["report"]}
    argv = r.base + [a.format(**words) for a in t["args"]]
    if config is None:
        argv += [a.format(**words) for a in extra.get("args", [])]
    return argv


def _run_tool(r, wt, crate, extra, ranges):
    """clear the report path, write the runner's config (no repo config), run the tool, then read what it left."""
    t = r.tool
    why = _clear_path(wt, crate, t["report"])  # a report (or link) the PR committed is never read or followed
    if why:
        return _path_fail(f"{t['name']} report {t['report']}", why)
    config = next((c for c in r.rv.adapter.mutation.get("config_files", [])
                   if os.path.lexists(os.path.join(crate, c))), None)
    if config is None and extra.get("config") is not None:
        why = _clear_path(wt, crate, extra["config_file"])
        if why:
            return _path_fail(f"{t['name']} config {extra['config_file']}", why)
        with open(os.path.join(crate, extra["config_file"]), "w", encoding="utf-8") as fh:
            fh.write(extra["config"])
    t0 = time.monotonic()
    rc, text = r.runner(_argv(r, extra, ranges, config), crate, r.budget)
    timing = {"wall_s": round(time.monotonic() - t0, 2)}
    if rc is None:
        return _not_installed(t, r.cmd)
    return _after_run(r, crate, rc, text, timing, config)


def _capped(t):
    return (f"; max-mutants not applied: {t['name']} makes its own mutants (no listing before its run): every changed "
            "line runs, the budget the only stop")


def _no_report(r, rc, text, timing):
    """the result of a run that left no report: partial on a budget hit, the baseline fail, else n/a (env)."""
    t = r.tool
    if rc == "timeout":
        return {"status": "partial", "note": f"budget hit before {t['name']} wrote its report: ? mutants, none read"
                                             + _capped(t), "tested": None, "total": None, "timing": timing}, []
    if t["baseline_rx"] is not None and _matched(t["baseline_rx"], text):
        return _check("fail", "baseline tests fail at head: mutants not run"), finalize([
            entry("R3", "", 0, "baseline", "agent-fixable", "fail", "baseline tests fail at head: mutants not run",
                  "fix the failing tests first: mutation needs an unmutated tree that passes",
                  "a mutation check that did not run")])
    return _check("n/a", f"no {t['name']} report at {t['report']} (env): {_first_line(text) or f'exit {rc}'}; "
                         "check the tool's run log"), []


def _report_rows(t, crate, report):
    """(the report's mutants, None), or (None, the result): a link out of the project dir, unreadable, malformed."""
    real_crate = os.path.realpath(crate)
    if not os.path.realpath(report).startswith(real_crate + os.sep):  # the run (PR code) left a link there
        problem = f"{t['name']} report {t['report']} leads out of the project dir after the run: not read"
        return None, (_check("fail", problem), finalize([entry(
            "R3", "", 0, "report-link", "agent-fixable", "fail", problem,
            "the run left a link at the report path (a test or a build step makes it): remove what makes it",
            "a mutation result read through a link out of the checkout")]))
    try:
        with open(report, "rb") as fh:
            raw = fh.read(MAX_REPORT_BYTES + 1)
        return read_report(t, raw, real_crate)[0], None
    except OSError as e:
        return None, (_check("n/a", f"{t['name']} report {t['report']} cannot be read (env): {e.strerror or e}"), [])
    except ReportError as e:
        return None, (_check("n/a", f"{t['name']} report {t['report']} is malformed (env): {e}; check the tool's "
                                    "version and its run log"), [])


def _after_run(r, crate, rc, text, timing, config):
    """the result of a run from its report: this shard's mutants classified, entries, the check."""
    t = r.tool
    report = os.path.join(crate, t["report"])
    if not os.path.lexists(report):
        return _no_report(r, rc, text, timing)
    rows, stop = _report_rows(t, crate, report)
    if stop:
        return stop
    mine, counts = _classify(r, rows)
    silent = sum(1 for x in mine if x.silent)  # this shard's: another shard's file is that shard's to report
    if silent:
        return _check("n/a", f"{t['name']} completed no test for {silent} covered mutant(s) (env): the test runner "
                             "did not run them; check the tool's test runner setup"), []
    return _result(r, rc, timing, config, mine, counts)


def _classify(r, rows):
    """(this shard's mutants, counts: caught, timeout, unviable, outside, unlocated, found [(file, mutant)]). Each mutant
    is one shard's: its file's, or shard 0's for a file no shard holds (outside the diff)."""
    tracked = _tracked_at(r.rv.repo, r.rv.head) if any(x.suffix for x in rows) else []
    first = shard_index(r.shard)[0] == 0
    counts = {"caught": 0, "timeout": 0, "unviable": 0, "outside": 0, "unlocated": 0, "found": []}
    mine = []
    for x in rows:
        file, why = _locate(x, r.rv.project_dir, tracked)
        if not ((file in r.files) if file in r.prod else first):
            continue
        mine.append(x)
        if x.kind in ("caught", "timeout", "unviable"):
            counts[x.kind] += 1
        if x.kind == "missed":
            _count_missed(r, counts, file, why, x)
    return mine, counts


def _count_missed(r, counts, file, why, x):
    if why == "outside" or (why is None and x.line not in {n for n, _ in r.changed.get(file, [])}):
        counts["outside"] += 1
    elif why == "unlocated":
        counts["unlocated"] += 1
    else:
        counts["found"].append((file, x))


def _missed_entry(file, x):
    hint = (f"add an assert that fails for this mutant: {x.desc}." if x.fix != "nocoverage" else
            "no test reaches this line: add a test that calls it and asserts the result.")
    return entry("R3", file, x.line, f"missed:{file}|{x.desc}", "agent-fixable", "fail",
                 f"MISSED mutant {file}:{x.line}: {x.desc}", hint + HOW, f"MISSED mutant `{x.desc}` in `{file}`")


def _entries(t, counts):
    ents = finalize([_missed_entry(file, x) for file, x in counts["found"]])
    if counts["unlocated"]:
        ents += finalize([entry("R3", "", 0, "unlocated", "agent-fixable", "confirm",
                                f"R3 unlocated: {counts['unlocated']} missed mutant(s) have no location in the "
                                f"{t['name']} report ({t['report']}): not blocking",
                                "read checks.R3.note: the report gives no single file and line for these mutants; "
                                "check them by hand",
                                "counting an unlocated mutant as outside the diff, or as a fail without a look")])
    return ents


def _result(r, rc, timing, config, mine, counts):
    """the check and entries of this shard's mutants: fail with a MISSED, partial when untested or the budget hit."""
    t = r.tool
    ents = _entries(t, counts)
    if not mine and rc != "timeout":
        return {"status": "pass", "note": "0 mutants in the diff", "tested": 0, "total": 0, "timing": timing}, ents
    live = [x for x in mine if x.kind != "ignored"]
    tested = sum(1 for x in live if x.kind != "pending")
    total, fails = len(live), len(counts["found"])
    note = (f"{tested}/{total} tested: {fails} missed in the diff, {counts['outside']} missed outside the diff, "
            f"{counts['unlocated']} unlocated, {counts['caught']} caught, {counts['timeout']} timeout, "
            f"{counts['unviable']} unviable")
    if rc == "timeout":
        note += f"; budget hit after {t['name']} wrote its report"
    if config is not None:
        note += f" (repo config {config})"
    check = _check("fail" if fails else "partial" if tested < total or rc == "timeout" else "pass",
                   note + _capped(t), tested, total)
    check["timing"] = timing
    return check, ents

def _program_path(word):
    """the absolute path of the tool's program, or None (not found): an absolute word as it is, a bare name on PATH's
    absolute entries only (a relative entry would resolve in the checkout the tool runs in), a relative path never
    (#19: a file in the project dir is the PR's)."""
    if os.path.isabs(word):
        return word
    if "/" in word or "\\" in word:
        return None
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and os.path.isabs(d)]
    found = shutil.which(word, path=os.pathsep.join(dirs)) if dirs else None
    # Windows' lookup may answer from the current dir (`.\\mut.exe`): only an absolute answer is a program on PATH
    return found if found and os.path.isabs(found) else None


def _in_checkout(prog, roots):
    """the program's real path when it, or the path it was found at (its dir's links resolved: a link the PR committed
    picks the program whatever it points to), lies in one of roots (the caller's checkout, the worktree); else None."""
    real = os.path.realpath(prog)
    found = os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(prog))), os.path.basename(prog))
    for root in roots:
        top = os.path.realpath(root).rstrip(os.sep) + os.sep
        if any(p.startswith(top) for p in (real, found)):
            return real
    return None


def _clear_path(wt, crate, rel):
    """make rel (a file under the crate dir) free for the run to write, never following a link: each part on the way
    that is a link, or not a dir where one is needed, is removed (the worktree's copy only; the tool makes the dirs it
    writes into, as on a clean checkout); at rel itself a link or file is removed, a dir removed whole. None, or why
    not (an OSError, or a crate dir that leads out of the worktree)."""
    top = os.path.realpath(wt)
    if not os.path.realpath(crate).startswith(top.rstrip(os.sep) + os.sep) and os.path.realpath(crate) != top:
        return "the project dir leads out of the checkout"
    parts = rel.split("/")
    cur = crate
    try:
        for i, part in enumerate(parts):
            cur = os.path.join(cur, part)
            last = i == len(parts) - 1
            try:
                st = os.lstat(cur)
            except FileNotFoundError:
                break  # nothing there, nor below it
            if last and stat.S_ISDIR(st.st_mode):
                shutil.rmtree(cur)
            elif last or not stat.S_ISDIR(st.st_mode):  # a link (to a dir too), a file, anything else
                os.unlink(cur)
                break
    except OSError as e:
        return e.strerror or str(e)
    return None


def _path_fail(what, why):
    """a path in the checkout the run needs that cannot be cleared: the PR put something there; an R3 fail, never n/a."""
    problem = f"{what}: the checkout's path cannot be cleared ({why}): mutants not run"
    return _check("fail", problem), finalize([entry(
        "R3", "", 0, "report-path", "agent-fixable", "fail", problem,
        "remove what the PR puts on that path (a link, a file where a dir goes): the tool writes there",
        "a mutation check that did not run")])


def _matched(rx, text):
    return any(m.end() > m.start() for m in rx.finditer(text or ""))


class NoTool:
    """an adapter file with no [mutation.tool] (#19, R3 tier 3): R3 is n/a with the reason, never a pass."""

    @staticmethod
    def note(rv):
        return f"stack `{rv.adapter.name}`: the adapter file declares no mutation tool ([mutation.tool]): R3 not run"

    def baseline(self, rv, cmd, budget_min, shards, runner=None, max_mutants=DEFAULT_MAX_MUTANTS):
        return _payload(False, 0, 0, None, _check("n/a", self.note(rv)), [])

    def check(self, rv, cmd, budget_min, shard, mutant_timeout, runner, max_mutants=DEFAULT_MAX_MUTANTS):
        return _check("n/a", self.note(rv)), []


def tool_for(adapter):
    """an adapter file's R3 tool: its declared [mutation.tool], or NoTool (n/a)."""
    tool = getattr(adapter, "mutation_tool", None)
    return DeclaredTool(tool) if tool else NoTool()


def baseline(rv, cmd=None, budget_min=None, shards=4, runner=None, max_mutants=DEFAULT_MAX_MUTANTS):
    """mutants.baseline for an adapter file (rv.adapter): skipped without a production change, else its tool's."""
    if not red.prod_changes(rv):
        return _payload(False, 0, 0, None, _check("skipped", "no production file changed"), [])
    return tool_for(rv.adapter).baseline(rv, cmd, budget_min, shards, runner, max_mutants=max_mutants)


def run(rv, cmd=None, budget_min=None, shard=None, mutant_timeout=None, runner=None, max_mutants=DEFAULT_MAX_MUTANTS):
    """mutants.run for an adapter file (rv.adapter): (check, entries); skipped without a production change, a partial
    check gets its confirm entry, as for the built-ins."""
    runner = runner or default_runner()
    if not red.prod_changes(rv):
        return _check("skipped", "no production file changed"), []
    check, ents = tool_for(rv.adapter).check(rv, cmd, budget_min, shard, mutant_timeout, runner, max_mutants=max_mutants)
    if check["status"] == "partial":
        ents = ents + [partial_entry(check)]
    return check, ents
