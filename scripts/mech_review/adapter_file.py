"""Adapter files (#16): load and validate a declarative TOML file that describes one stack, and build its DataAdapter.

Format: docs/mech-review-ci.md#adapter-file. Every problem is an AdapterFileError that names the field
(`lexer.strings[1].quote: want a non-empty string`): never a traceback, never a silent default for a bad value.
tomllib (python 3.11+) is imported only in load(), so the built-in adapters keep working on older pythons."""
import json
import os
import re
import shlex
import string

from . import parser_cmd
from .data_adapter import DataAdapter, ParserAdapter
from .scan import Lexer, ShapeError

FORMAT = 1
BLOCK_STYLES = ("braces", "indent", "keywords")
KINDS = ("eq", "ne", "other")
COVERS = ("line", "next-line", "file")
RESERVED = "auto"  # the stack input that means "find the stack" (resolve.AUTO): never a stack's own name
TARGET_OS = ("linux", "macos", "windows")  # the stack job outputs one of these; the workflow maps it to a fixed runner


class AdapterFileError(ValueError):
    pass


def _err(field, msg):
    raise AdapterFileError(f"{field}: {msg}" if field else msg)


def _table(d, field, allowed, required=()):
    """field: the table's dotted name, "" for the top level (its keys are named bare)."""
    if not isinstance(d, dict):
        _err(field, "want a table")
    for k in d:
        if k not in allowed:
            _err(f"{field}.{k}".removeprefix("."), "unknown key")
    for k in required:
        if k not in d:
            _err(f"{field}.{k}".removeprefix("."), "missing")
    return d


def _str(v, field, empty=False):
    if not isinstance(v, str) or (not empty and not v):
        _err(field, "want a string" if empty else "want a non-empty string")
    return v


def _strs(v, field, nonempty=False):
    if not isinstance(v, list) or any(not isinstance(x, str) or not x for x in v):
        _err(field, "want a list of non-empty strings")
    if nonempty and not v:
        _err(field, "want at least one entry")
    return v


def _bool(v, field):
    if not isinstance(v, bool):
        _err(field, "want true or false")
    return v


def _int(v, field):
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        _err(field, "want a whole number >= 0")
    return v


def _template(v, field, name):
    """plain `{name}` placeholders (and `{{` `}}`) only: a conversion or spec could still fail on a real value (a nested
    field in a spec takes the value's text), so none is allowed. name: the one placeholder name, or a tuple of the
    names allowed. Returns the names used."""
    names = (name,) if isinstance(name, str) else tuple(name)
    want = " or ".join(f"`{{{n}}}`" for n in names)
    _str(v, field)
    try:
        parts = [(f, spec, conv) for _, f, spec, conv in string.Formatter().parse(v) if f is not None]
    except ValueError as e:
        _err(field, f"bad template: {e}")
    for f, _, _ in parts:
        if f not in names:
            _err(field, f"unknown placeholder `{{{f}}}`: want {want}")
    try:
        v.format(**{n: "x" for n in names})
    except (ValueError, IndexError, KeyError) as e:
        _err(field, f"bad template: {e}")
    if any(spec or conv for _, spec, conv in parts):
        _err(field, f"`{v}`: want plain {want} (no `!` conversion or `:` spec)")
    return {f for f, _, _ in parts}


def _idents(v, field, lexer, nonempty=False):
    _strs(v, field, nonempty)
    for i, w in enumerate(v):
        if not all(lexer.is_ident(ch) for ch in w):
            _err(f"{field}[{i}]", f"`{w}` is not a word (letters, digits, _ and lexer.ident_chars)")
    return v


def _lexer(d):
    f = "lexer"
    _table(d, f, ("block_style", "brackets", "ident_chars", "member", "line_comments", "block_comments", "strings",
                  "regex"), ("block_style", "brackets"))
    style = _str(d["block_style"], f + ".block_style")
    if style not in BLOCK_STYLES:
        _err(f + ".block_style", f"unknown block style `{style}`: want braces")
    if style != "braces":
        _err(f + ".block_style", f"`{style}` is not supported yet: want braces")
    brackets = _strs(d["brackets"], f + ".brackets", nonempty=True)
    owner = {}  # each bracket char belongs to one pair: `(]` beside `[]` is a typo, not a pair
    for i, b in enumerate(brackets):
        if len(b) != 2 or b[0] == b[1]:
            _err(f"{f}.brackets[{i}]", f"`{b}`: want an opener and a closer, e.g. \"()\"")
        for ch in b:
            if ch in owner:
                _err(f"{f}.brackets[{i}]", f"`{ch}` is already in {f}.brackets[{owner[ch]}]")
            owner[ch] = i
    if "()" not in brackets:
        _err(f + ".brackets", "want \"()\": calls are `name(...)`")
    if style == "braces" and "{}" not in brackets:
        _err(f + ".brackets", "want \"{}\": block_style braces opens blocks with `{`")
    ident = _str(d.get("ident_chars", ""), f + ".ident_chars", empty=True)
    member = _str(d.get("member", "."), f + ".member", empty=True)
    if len(member) > 1:
        _err(f + ".member", "want one character or \"\"")
    _strs(d.get("line_comments", []), f + ".line_comments")
    blocks = d.get("block_comments", [])
    if not isinstance(blocks, list):
        _err(f + ".block_comments", "want a list of [open, close] pairs")
    for i, b in enumerate(blocks):
        if not isinstance(b, list) or len(b) != 2 or any(not isinstance(x, str) or not x for x in b):
            _err(f"{f}.block_comments[{i}]", "want [open, close], two non-empty strings")
    strings = d.get("strings", [])
    if not isinstance(strings, list):
        _err(f + ".strings", "want an array of tables ([[lexer.strings]])")
    for i, s in enumerate(strings):
        sf = f"{f}.strings[{i}]"
        _table(s, sf, ("quote", "escape", "multiline", "interpolation", "name"), ("quote",))
        _str(s["quote"], sf + ".quote")
        esc = _str(s.get("escape", ""), sf + ".escape", empty=True)
        if len(esc) > 1:
            _err(sf + ".escape", "want one character or \"\"")
        multiline = _bool(s.get("multiline", False), sf + ".multiline")
        if "interpolation" in s:
            ip = s["interpolation"]
            if not isinstance(ip, list) or len(ip) != 2 or any(not isinstance(x, str) or not x for x in ip):
                _err(sf + ".interpolation", "want [open, close], two non-empty strings")
            if not multiline:
                _err(sf + ".interpolation", "needs multiline = true")
        if "name" in s:
            _str(s["name"], sf + ".name")
    if "regex" in d:
        rf = f + ".regex"
        rx = _table(d["regex"], rf, ("delimiter", "after", "after_words"), ("delimiter",))
        if not isinstance(rx["delimiter"], str) or len(rx["delimiter"]) != 1:
            _err(rf + ".delimiter", "want one character")
        _str(rx.get("after", ""), rf + ".after", empty=True)
        _strs(rx.get("after_words", []), rf + ".after_words")
        rx = {"delimiter": rx["delimiter"], "after": rx.get("after", ""), "after_words": set(rx.get("after_words", []))}
    else:
        rx = None
    bracket_chars = "".join(brackets)
    quotes = {s["quote"][0] for s in strings}
    openers = {c[0] for c in d.get("line_comments", [])} | {b[0][0] for b in blocks}
    if member:
        why = ("a word character" if member.isalnum() or member == "_" else "whitespace" if member.isspace()
               else "a bracket" if member in bracket_chars else None)
        if why:
            _err(f + ".member", f"`{member}` is {why}: want punctuation such as \".\"")
    for ch in ident:
        why = ("whitespace" if ch.isspace() else "a bracket" if ch in bracket_chars else "a string quote" if ch in quotes
               else "a comment opener" if ch in openers else "the member character" if ch == member else None)
        if why:
            _err(f + ".ident_chars", f"`{ch}` cannot be part of a word ({why})")
    return Lexer(brackets, ident, member, d.get("line_comments", []), blocks, strings, rx)


def _tests(d, lexer, functions=False):
    f = "tests"
    style = _str(_table(d, f, TEST_KEYS + ("prefix",), ("style", "cases")).get("style"), f + ".style")
    if style not in ("calls", "declared"):
        _err(f + ".style", f"unknown style `{style}`: want calls or declared")
    if style == "declared":
        return _declared(d, lexer, functions)
    if "prefix" in d:
        _err(f + ".prefix", "style calls has no prefix (declared only: what starts a test's marker)")
    names = set(_idents(d.get("groups", []), f + ".groups", lexer)) | set(_idents(d["cases"], f + ".cases", lexer, True))
    for k in ("skip", "only"):
        for i, w in enumerate(_strs(d.get(k, []), f"{f}.{k}")):
            if w not in names:
                _err(f"{f}.{k}[{i}]", f"`{w}` is not in tests.groups or tests.cases")
    for k in ("skip_modifiers", "only_modifiers", "table_modifiers"):
        _idents(d.get(k, []), f"{f}.{k}", lexer)
    if "separator" in d:
        _str(d["separator"], f + ".separator")
    if "min_args" in d:
        _int(d["min_args"], f + ".min_args")
    _strs(d.get("not_after", []), f + ".not_after")
    if "skipped_text" in d:
        _template(d["skipped_text"], f + ".skipped_text", "name")


TEST_KEYS = ("style", "groups", "cases", "separator", "skip", "only", "skip_modifiers", "only_modifiers",
             "table_modifiers", "min_args", "not_after", "skipped_text")
CALLS_ONLY = ("skip_modifiers", "only_modifiers", "table_modifiers", "min_args", "not_after")


def _declared(d, lexer, functions):
    """[tests] style declared (#22): a test is a [functions] shape with a case marker before it (`@Test`); groups are
    `<word> NAME ...{...}` declarations; skip and only are marker words."""
    f = "tests"
    for k in CALLS_ONLY:
        if k in d:
            _err(f"{f}.{k}", "style calls only: a declared test is no call")
    if not functions:
        _err("functions", "missing: tests.style declared reads each test as a [functions] shape with a marker")
    if "prefix" not in d:
        _err(f + ".prefix", "missing: style declared needs what starts a marker, e.g. \"@\"")
    prefix = _str(d["prefix"], f + ".prefix")
    if any(lexer.is_ident(ch) or ch.isspace() or ch in lexer.opens + lexer.closes + (lexer.member or "") for ch in prefix):
        _err(f + ".prefix", f"`{prefix}`: want punctuation that is no word character, bracket or member character")
    _idents(d["cases"], f + ".cases", lexer, True)
    for k in ("groups", "skip", "only"):
        _idents(d.get(k, []), f"{f}.{k}", lexer)
    if "separator" in d:
        _str(d["separator"], f + ".separator")
    if "skipped_text" in d:
        _template(d["skipped_text"], f + ".skipped_text", "name")


def _asserts(d, lexer):
    f = "asserts"
    _table(d, f, ("chain", "call"))
    chains, calls = d.get("chain", []), d.get("call", [])
    if not isinstance(chains, list):
        _err(f + ".chain", "want an array of tables ([[asserts.chain]])")
    if not isinstance(calls, list):
        _err(f + ".call", "want an array of tables ([[asserts.call]])")
    if not chains and not calls:
        _err(f, "no assert shape: want [[asserts.chain]] or [[asserts.call]]")
    seen = {}  # a word starts one assert shape only: a second one would silently win
    for i, c in enumerate(chains):
        cf = f"{f}.chain[{i}]"
        _table(c, cf, ("start", "negate", "pass_through", "eq"), ("start", "eq"))
        start = _str(c["start"], cf + ".start")
        if not all(lexer.is_ident(ch) for ch in start):
            _err(cf + ".start", f"`{start}` is not a word (letters, digits, _ and lexer.ident_chars)")
        if start in seen:
            _err(cf + ".start", f"`{start}` is already {seen[start]}")
        seen[start] = cf + ".start"
        _idents(c["eq"], cf + ".eq", lexer, nonempty=True)
        for k in ("negate", "pass_through"):
            _idents(c.get(k, []), f"{cf}.{k}", lexer)
    for i, c in enumerate(calls):
        cf = f"{f}.call[{i}]"
        _table(c, cf, ("names", "kind", "operands"), ("names", "kind"))
        for j, n in enumerate(_idents(c["names"], cf + ".names", lexer, True)):
            if n in seen:
                _err(f"{cf}.names[{j}]", f"`{n}` is already an assert shape")
            seen[n] = cf
        kind = _str(c["kind"], cf + ".kind")
        if kind not in KINDS:
            _err(cf + ".kind", f"`{kind}`: want eq, ne or other")
        if kind != "other":
            ops = c.get("operands")
            if ops is None:
                _err(cf + ".operands", f"missing: kind {kind} needs [left, right] argument indexes")
            if not isinstance(ops, list) or len(ops) != 2 or ops[0] == ops[1]:
                _err(cf + ".operands", "want [left, right]: two different argument indexes")
            for j, o in enumerate(ops):
                _int(o, f"{cf}.operands[{j}]")
        elif "operands" in c:
            _err(cf + ".operands", "kind other has no operands")


def _functions(d, lexer):
    f = "functions"
    _table(d, f, ("shapes",), ("shapes",))
    out = []
    for i, src in enumerate(_strs(d["shapes"], f + ".shapes")):
        try:
            out.append(lexer.parse_shape(src))
        except ShapeError as e:
            _err(f"{f}.shapes[{i}]", f"`{src}`: {e}")
    return out


def _suppressions(v):
    f = "suppressions"
    if not isinstance(v, list):
        _err(f, "want an array of tables ([[suppressions]])")
    for i, s in enumerate(v):
        sf = f"{f}[{i}]"
        _table(s, sf, ("directives", "covers", "lints", "reason_after", "reason_strip", "problem", "hint"),
               ("directives", "covers"))
        dirs = _strs(s["directives"], sf + ".directives", nonempty=True)
        covers = _table(s["covers"], sf + ".covers", dirs)
        for dname in dirs:
            if dname not in covers:
                _err(f"{sf}.covers.{dname}", "missing: want line, next-line or file")
            if covers[dname] not in COVERS:
                _err(f"{sf}.covers.{dname}", f"`{covers[dname]}`: want line, next-line or file")
        lints = s.get("lints", "directive")
        if lints not in ("rules", "directive"):
            _err(sf + ".lints", f"`{lints}`: want rules or directive")
        if "reason_after" in s:
            _str(s["reason_after"], sf + ".reason_after")
            if "reason_strip" in s:
                _err(sf + ".reason_strip", "not with reason_after: the reason is the text after the mark")
        _strs(s.get("reason_strip", []), sf + ".reason_strip")
        for k in ("problem", "hint"):
            if k in s:
                _template(s[k], f"{sf}.{k}", "lints")


def _mutation(d, run=None):
    """[mutation]: R2's skip markers and config files, and the R3 tool (#19). Returns the validated tool or None."""
    f = "mutation"
    _table(d, f, ("skip_comments", "config_files", "config_name", "tool"))
    _strs(d.get("skip_comments", []), f + ".skip_comments")
    if _strs(d.get("config_files", []), f + ".config_files"):
        if "config_name" not in d:
            _err(f + ".config_name", "missing: config_files needs a name for the entry")
    if "config_name" in d:
        _str(d["config_name"], f + ".config_name")
    return _tool(d["tool"], d.get("config_files", []), run) if "tool" in d else None


REPORT_FORMATS = ("mutation-testing-elements", "pit-xml", "lines")  # what R3 reads: report formats, not tools (#19)
TOOL_ARGS = ("mutate", "timeout_ms", "timeout_s", "report")  # [mutation.tool].args placeholders
RANGE = ("file", "first", "last", "module")  # [mutation.tool].mutate placeholders: one changed-line range
STATUS_KINDS = ("missed", "caught", "timeout", "unviable")  # format lines: what each status word means for R3
LINE_GROUPS = ("file", "line", "status")
TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]+")  # the tool's name in notes: ASCII, no space or quote
DEFAULT_TOOL_TIMEOUT = 120  # seconds per mutant when the workflow's mutant-timeout is auto


def _tool(d, config_files, run):
    """[mutation.tool]: the command R3 runs on the changed lines, the report it writes and the report's format. Returns
    the table with its defaults filled and its patterns compiled (version_rx, baseline_rx, pattern_rx)."""
    f = "mutation.tool"
    _table(d, f, ("name", "command", "args", "mutate", "mutate_join", "module_roots", "version", "version_pattern",
                  "report", "format", "os", "timeout", "baseline_failed", "pattern", "status", "runners"),
           ("name", "command", "report", "format", "os"))
    name = _str(d["name"], f + ".name")
    if not TOOL_NAME.fullmatch(name):
        _err(f + ".name", f"`{name}`: want letters, digits, _, - or .")
    _command(d["command"], f + ".command")
    _program(shlex.split(d["command"])[0], f + ".command")
    args = _strs(d.get("args", []), f + ".args")
    used = set()
    for i, a in enumerate(args):
        used |= _template(a, f"{f}.args[{i}]", TOOL_ARGS)
    if "mutate" in d:
        if "mutate" not in used:
            _err(f + ".mutate", "never used: no arg has `{mutate}`")
        _module_roots(d, f, _template(d["mutate"], f + ".mutate", RANGE))
    elif "mutate" in used:
        _err(f + ".mutate", "missing: an arg uses `{mutate}`, the changed line ranges")
    elif "module_roots" in d:
        _err(f + ".module_roots", "never used: no mutate has `{module}`")
    _str(d.get("mutate_join", ","), f + ".mutate_join")
    version = _strs(d["version"], f + ".version", nonempty=True) if "version" in d else None
    if "runners" in d:
        _tool_runners(d["runners"], f + ".runners", config_files, run)
    tool = dict(d, args=list(args), mutate_join=d.get("mutate_join", ","), version=version,
                timeout=d.get("timeout", DEFAULT_TOOL_TIMEOUT), runners=dict(d.get("runners", {})))
    tool["version_rx"] = None
    if "version_pattern" in d:
        if version is None:
            _err(f + ".version_pattern", "needs version: the words that print the tool's version")
        tool["version_rx"] = _regex(d["version_pattern"], f + ".version_pattern")
    _filepath(_str(d["report"], f + ".report"), f + ".report")
    fmt = _str(d["format"], f + ".format")
    if fmt not in REPORT_FORMATS:
        _err(f + ".format", f"`{fmt}`: want mutation-testing-elements, pit-xml or lines")
    oses = _strs(d["os"], f + ".os", nonempty=True)
    for i, o in enumerate(oses):
        target_os(o, f"{f}.os[{i}]")
        if o in oses[:i]:
            _err(f"{f}.os[{i}]", f"`{o}` is listed twice")
    t = tool["timeout"]
    if type(t) is not int or t < 1:
        _err(f + ".timeout", "want a whole number of seconds >= 1")
    tool["baseline_rx"] = _regex(d["baseline_failed"], f + ".baseline_failed") if "baseline_failed" in d else None
    tool["pattern_rx"] = _lines_format(d, f) if fmt == "lines" else None
    if fmt != "lines":
        for k, what in (("pattern", "no pattern"), ("status", "no status lists")):
            if k in d:
                _err(f"{f}.{k}", f"format {fmt} has {what} (lines only)")
    return tool


ABSOLUTE = re.compile(r"^(?:/|[A-Za-z]:[\\/])")  # a POSIX or a Windows drive path


def _module_roots(d, f, names):
    """mutate names its file: `{file}`, or `{module}` (#22: the file under one of module_roots, as a dotted name, PIT's
    class name), which needs module_roots: dirs under the project dir, each a path as `report` is."""
    if "file" not in names and "module" not in names:
        _err(f + ".mutate", "no `{file}` or `{module}`: a range names its file")
    if "module" not in names:
        if "module_roots" in d:
            _err(f + ".module_roots", "never used: mutate has no `{module}`")
        return
    if "module_roots" not in d:
        _err(f + ".module_roots", "missing: `{module}` is a file's dotted name under one of these dirs")
    for i, root in enumerate(_strs(d["module_roots"], f + ".module_roots", nonempty=True)):
        _filepath(root, f"{f}.module_roots[{i}]")


def _program(word, field):
    """the tool's program: a bare name (found on PATH when R3 runs) or an absolute path. A relative path is a file in
    the project dir, so the PR under review could supply the program that judges it (#19; #27's rule for a parser)."""
    if ("/" in word or "\\" in word) and not ABSOLUTE.match(word):
        _err(field, f"`{word}` is a path in the project dir, which the PR under review can change: want a program on "
                    "PATH or an absolute path outside it (install the tool with setup-command, or pass mutants-cmd)")
    if launcher(word):
        _err(field, f"`{word}` is an interpreter, shell or launcher: it runs what it is given, which can be a file the PR "
                    "under review changes; install the tool as a program on PATH (setup-command) or pass mutants-cmd")
    return word


def launcher(word):
    """True when a program word (a bare name or a path, any case, `.exe` `.cmd` `.bat` `.com` or not) is one of
    INTERPRETERS (#27's list, the shells in it): a program that runs the code it is given, never a tool's program."""
    name = re.split(r"[\\/]", word)[-1].lower()
    return bool(INTERPRETERS.fullmatch(re.sub(r"\.(?:exe|cmd|bat|com)$", "", name)))


def _lines_format(d, f):
    """format lines: pattern (python regex, multiline) with named groups file, line and status, and the status words."""
    if "pattern" not in d:
        _err(f + ".pattern", "missing: format lines reads each mutant with it")
    rx = _regex(d["pattern"], f + ".pattern")
    for g in LINE_GROUPS:
        if g not in rx.groupindex:
            _err(f + ".pattern", f"`{d['pattern']}` has no named group `{g}`: want (?P<file>...), (?P<line>...) and "
                                 "(?P<status>...)")
    if "status" not in d:
        _err(f + ".status", "missing: format lines maps each status word to missed, caught, timeout or unviable")
    st = _table(d["status"], f + ".status", STATUS_KINDS, ("missed", "caught"))
    owner = {}
    for k in STATUS_KINDS:
        if k not in st:
            continue
        for i, w in enumerate(_strs(st[k], f"{f}.status.{k}", nonempty=True)):
            if w in owner:
                _err(f"{f}.status.{k}[{i}]", f"`{w}` is already in {f}.status.{owner[w]}")
            owner[w] = k
    return rx


def _tool_runners(d, f, config_files, run):
    """mutation.tool.runners.<[[run.runner]] name>: needs (a file the tool needs in the project dir: the runner's
    binary), and for a project with none of [mutation].config_files the args added and the config file written."""
    if not isinstance(d, dict):
        _err(f, "want a table")
    if run is None:
        _err(f, "needs [run]: a runner is one of [[run.runner]]")
    names = [r["name"] for r in run.get("runner", []) if isinstance(r, dict) and isinstance(r.get("name"), str)]
    for name, r in d.items():
        rf = f"{f}.{name}"
        if name not in names:
            _err(rf, "not a [[run.runner]] name: want " + (" or ".join(names) if names else "a [[run.runner]] first"))
        _table(r, rf, ("needs", "args", "config_file", "config"))
        if "needs" in r:
            _filepath(_str(r["needs"], rf + ".needs"), rf + ".needs")
        for i, a in enumerate(_strs(r.get("args", []), rf + ".args")):
            _template(a, f"{rf}.args[{i}]", TOOL_ARGS)
        if "config" in r and "config_file" not in r:
            _err(rf + ".config_file", "missing: config is written to it")
        if "config_file" in r:
            cf = _filepath(_str(r["config_file"], rf + ".config_file"), rf + ".config_file")
            if cf not in config_files:
                _err(rf + ".config_file", f"`{cf}` is not in mutation.config_files: it is written only when the project "
                                          "has none of them")
            if "config" not in r:
                _err(rf + ".config", "missing: the text written to config_file")
            try:
                doc = json.loads(_str(r["config"], rf + ".config"), parse_constant=_no_constant)
            except (ValueError, RecursionError) as e:
                _err(rf + ".config", f"want a JSON object: {e}")
            if not isinstance(doc, dict):
                _err(rf + ".config", "want a JSON object")


def _no_constant(name):
    raise ValueError(f"`{name}` is not JSON")


def _filepath(v, field):
    """a file under the project dir: relative, no `..`, no empty or `.` part (the engine writes or reads it there)."""
    _relpath(v, field)
    if any(part in ("", ".") for part in v.split("/")):
        _err(field, f"`{v}`: want a file under the project dir, such as out/report.json")
    return v


COMMANDS = {  # [commands]: every key is required ("" says the stack has none), so a missing one is named, never assumed
    "install": "the command that installs the project's dependencies",
    "build": "the command that builds the project",
    "lint": "the command that lints the project",
    "test": "the command that runs the whole test suite",
}
ONE_TEST = ("path", "name")  # [run].test placeholders: the test's file (project-dir relative), the runner's name for it


def _commands(d, run):
    """[commands]: install, build, lint, test. R1 and R4 use test only (with [run], it may not be ""); the others are
    for ci-doctor and the session's verify commands."""
    f = "commands"
    _table(d, f, tuple(COMMANDS))
    for k, what in COMMANDS.items():
        if k not in d:
            _err(f"{f}.{k}", f"missing: want {what}, or \"\" when the stack has none")
        _command(d[k], f"{f}.{k}", blank=True)
    if run and not d["test"].strip():
        _err(f + ".test", "want the whole-suite command: [run] starts every R1 and R4 run from it")
    return d


def _command(v, field, blank=False):
    """a command string, split as the engine splits it (shlex), so unbalanced quotes are a load error, not a crash in
    R1 or R4. blank: "" (and whitespace) allowed, the declared none."""
    _str(v, field, empty=blank)
    if not blank and not v.strip():
        _err(field, "want a command, not blank")
    try:
        shlex.split(v)
    except ValueError as e:
        _err(field, f"`{v}`: unbalanced quotes ({e})")
    return v


EMPTY_PROBES = ("", "\n", "x", " x\n")  # a pattern with a zero-width match in any of these can match no output at all


def _regex(v, field, groups=None):
    """a python regex over the runner's output (multiline: ^ and $ match at line ends), compiled here so a bad one is a
    load error. groups: the capturing groups it must have (a tuple of allowed counts), None for any."""
    _str(v, field)
    try:
        rx = re.compile(v, re.M)
    except re.error as e:
        _err(field, f"bad regex `{v}`: {e}")
    if groups is not None and rx.groups not in groups:
        want = {(0,): "no capturing group: use (?:...)", (1,): "one capturing group: the count, e.g. `(\\d+) passed`",
                (0, 1): "at most one capturing group: the part counts are read from"}[groups]
        _err(field, f"`{v}` has {rx.groups} capturing groups: want {want}")
    if any(m.start() == m.end() for probe in EMPTY_PROBES for m in rx.finditer(probe)):
        _err(field, f"`{v}` matches empty text: want a pattern that needs some output to match")
    return rx


def _when(d, field):
    """a runner's `when`: `file` exists in the project dir; with `tables`, the file is JSON and `has` / `lacks` name keys
    that must (must not) be in one of those tables (package.json's dependencies, devDependencies)."""
    _table(d, field, ("file", "tables", "has", "lacks"), ("file",))
    _str(d["file"], field + ".file")
    _relpath(d["file"], field + ".file")
    if any(part in ("", ".") for part in d["file"].split("/")):
        _err(field + ".file", f"`{d['file']}`: want a file name under the project dir, such as package.json")
    _strs(d.get("tables", []), field + ".tables")
    for k in ("has", "lacks"):
        if _strs(d.get(k, []), f"{field}.{k}") and not d.get("tables"):
            _err(f"{field}.{k}", "needs tables: the JSON tables the names are looked up in")


def _relpath(v, field):
    if v.startswith("/") or "\\" in v or ".." in v.split("/"):
        _err(field, f"`{v}`: want a path under the project dir (no .., not absolute)")


def _run(d):
    """[run]: how R1 and R4 run one test and read the result. Returns the compiled patterns (outcome, name)."""
    f = "run"
    _table(d, f, ("test", "name", "runner", "outcome", "links", "list"), ("test", "outcome"))
    words = _strs(d["test"], f + ".test", nonempty=True)
    used = set()
    for i, w in enumerate(words):
        used |= _template(w, f"{f}.test[{i}]", ONE_TEST)
    if "name" not in used:
        _err(f + ".test", "no `{name}`: the words must name the one test to run")
    for i, p in enumerate(_strs(d.get("links", []), f + ".links")):
        _relpath(p, f"{f}.links[{i}]")
    compiled = {}
    if "name" in d:
        nf = f + ".name"
        nm = _table(d["name"], nf, ("escape", "placeholders", "any"))
        _str(nm.get("escape", ""), nf + ".escape", empty=True)
        if "placeholders" in nm:
            compiled["placeholders"] = _regex(nm["placeholders"], nf + ".placeholders", (0,))
            if "any" not in nm:
                _err(nf + ".any", "missing: placeholders needs the text they become, e.g. \".*\"")
        if "any" in nm:
            _str(nm["any"], nf + ".any", empty=True)
            if "placeholders" not in nm:
                _err(nf + ".placeholders", "missing: any is what placeholders become")
    runners = d.get("runner", [])
    if not isinstance(runners, list):
        _err(f + ".runner", "want an array of tables ([[run.runner]])")
    seen, catch_all = {}, None
    for i, r in enumerate(runners):
        rf = f"{f}.runner[{i}]"
        _table(r, rf, ("name", "match", "command", "when", "subcommand", "separator"), ("name",))
        name = _str(r["name"], rf + ".name")
        if name in seen:
            _err(rf + ".name", f"`{name}` is already {seen[name]}")
        seen[name] = rf
        if catch_all is not None:
            _err(rf, f"never picked for a command: {catch_all} has no match, so it takes every command")
        if "match" in r:
            _str(r["match"], rf + ".match")
        else:
            catch_all = rf
        if "command" in r:
            _command(r["command"], rf + ".command")
            if "when" not in r:
                _err(rf + ".command", "never used: a runner's command is picked by its when")
        if "when" in r:
            _when(r["when"], rf + ".when")
            if "command" not in r:
                _err(rf + ".command", "missing: when picks this runner's command for the checkout")
        if "subcommand" in r:
            sc = _table(r["subcommand"], rf + ".subcommand", ("word", "after"), ("word",))
            _str(sc["word"], rf + ".subcommand.word")
            if "after" in sc:
                _str(sc["after"], rf + ".subcommand.after")
        if "separator" in r:
            _str(r["separator"], rf + ".separator")
    if "list" in d:
        compiled["list"] = _list(d["list"], f + ".list", seen)
    of = f + ".outcome"
    out = _table(d["outcome"], of, ("summary", "passed", "failed", "skipped", "build", "no_test", "env"),
                 ("passed", "failed"))
    for k in ("passed", "failed", "skipped"):
        if k in out:
            compiled[k] = _regex(out[k], f"{of}.{k}", (1,))
    if "summary" in out:
        compiled["summary"] = _regex(out["summary"], of + ".summary", (0, 1))
    for k in ("build", "no_test", "env"):
        if k in out:
            compiled[k] = _regex(out[k], f"{of}.{k}")
    return compiled


LIST_GROUPS = ("file", "name")  # [run.list].pattern's named groups: name required, file optional


def _list(d, field, runners):
    """[run.list] (#21): the command that lists every test the runner collects (R0's census), and how a line of its
    output reads: `pattern`, a regex with a named group `name` (the runner's full name for the test) and optionally
    `file` (its file, project-dir relative); `separator`: how the listing joins group and test names (default the
    runner's, else tests.separator); `runner`: the [[run.runner]] whose listing this is (another runner: no census).
    Returns the compiled pattern."""
    _table(d, field, ("command", "pattern", "separator", "runner"), ("command", "pattern"))
    _command(d["command"], field + ".command")
    rx = _regex(d["pattern"], field + ".pattern")
    if "name" not in rx.groupindex:
        _err(field + ".pattern", f"`{d['pattern']}` has no named group `name`: want (?P<name>...) for the test's name")
    extra = sorted(set(rx.groupindex) - set(LIST_GROUPS))
    if extra:
        _err(field + ".pattern", f"`{d['pattern']}` has the group `{extra[0]}`: want only `name` and `file`")
    if "separator" in d:
        _str(d["separator"], field + ".separator")
    if "runner" in d:
        _str(d["runner"], field + ".runner")
        if d["runner"] not in runners:
            _err(field + ".runner", f"`{d['runner']}` is no [[run.runner]] name")
    return rx


# [limits] (#20): the check limits a stack sets; R0's editing rules need a person for a looser one. Range per key.
LIMIT_KEYS = {"max-mutants": (1, None), "mutation-budget": (1, None), "assert-density": (0, 100), "census": (0, 100)}


def limits(d):
    """{key: whole number} of a [limits] table, each validated (AdapterFileError names the field)."""
    _table(d, "limits", tuple(LIMIT_KEYS))
    for k, v in d.items():
        lo, hi = LIMIT_KEYS[k]
        if type(v) is not int or v < lo or (hi is not None and v > hi):
            _err(f"limits.{k}", f"want a whole number >= {lo}" if hi is None else f"want a whole number from {lo} to {hi}")
    return dict(d)


def target_os(v, field="target-os"):
    """one of TARGET_OS, exactly (no case folding: the value is passed on to the workflow as it is)."""
    _str(v, field)
    if v not in TARGET_OS:
        _err(field, f"`{v}`: want linux, macos or windows")
    return v


# [parser] (#27): one command in place of the patterns. These tables describe source as patterns: not with [parser]
PATTERN_TABLES = ("lexer", "tests", "functions", "asserts", "suppressions")
PARSER_TIMEOUT = (1, 600, 30)  # seconds per file: min, max, default
SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish", "pwsh", "powershell", "cmd")
# programs that run code they are given (a script, stdin, an option): never the parser, which is a program the package
# installs. With SHELLS; any case, `.exe` or not
INTERPRETERS = re.compile(r"(?:python|pypy|perl|php|lua|luajit|ruby|jruby|node|tclsh|wish)[0-9.]*|nodejs|deno|bun|irb|"
                          r"rscript|r|java|jshell|kotlin|scala|groovy|osascript|env|busybox|[gmn]?awk|sed|xargs|nohup|"
                          r"timeout|nice|time|sudo|doas|su|exec|"
                          # REPLs, script runners and package managers: each evaluates what it is given
                          r"ipython|ptpython|bpython|ts-node|tsx|py|npx|pnpx|bunx|yarn|pnpm|npm|uvx|pipx|pdm|poetry|"
                          r"hatch|rye|cargo|go|gem|bundle|rake|mix|elixir|iex|erl|escript|julia|swift|dotnet|mono|ghci|"
                          r"runghc|clojure|clj|sbcl|guile|racket|node-repl|" + "|".join(SHELLS))
PROGRAM = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # a bare name: no path, so it resolves in the package's prefix
# `--name` or `--name=value`: a value of plain characters, not starting with / ~ or -, with no `..` segment (between
# `=`, `/` or `:` and the next of those or the end)
OPTION = re.compile(r"--[a-z][a-z0-9-]*(?:=(?![/~-])(?!(?:[^/:]*[/:])*\.\.(?:[/:]|$))[A-Za-z0-9._:/@+-]+)?")


def _parser(data):
    """the [parser] table, validated: {command: argv, installer, package, version, timeout, skipped_text}."""
    f = "parser"
    d = _table(data["parser"], f, ("command", "installer", "package", "version", "timeout", "skipped_text"),
               ("command", "installer", "package", "version"))
    for t in PATTERN_TABLES:
        if t in data:
            _err(t, "not with [parser]: the parser command gives the facts, a file declares no patterns beside it")
    if "skip_comments" in data.get("mutation", {}):
        _err("mutation.skip_comments", "not with [parser]: the parser command gives the mutation skips")
    argv = _argv(d["command"], f + ".command")
    if not PROGRAM.fullmatch(argv[0]):
        _err(f + ".command", f"`{argv[0]}`: want a bare program name the package installs (no path), such as "
                             f"`rb-test-facts`")
    if INTERPRETERS.fullmatch(re.sub(r"\.exe$", "", argv[0].lower())):
        _err(f + ".command", f"`{argv[0]}` is an interpreter or shell: want the parser program the package installs "
                             f"(it would run code it is given)")
    for w in argv[1:]:
        if not OPTION.fullmatch(w):
            _err(f + ".command", f"`{w}`: want a long option, `--name` or `--name=value` (name: a-z, 0-9, -; value: "
                                 f"letters, digits and . _ : / @ + -, not starting with / ~ or -, no `..`)")
    installer = _str(d["installer"], f + ".installer")
    if installer not in parser_cmd.INSTALLERS:
        _err(f + ".installer", f"`{installer}`: want " + ", ".join(list(parser_cmd.INSTALLERS)[:-1]) + " or go")
    name_re, version_re = parser_cmd.INSTALLERS[installer][:2]
    package = _str(d["package"], f + ".package")
    if not re.fullmatch(name_re, package):
        _err(f + ".package", f"`{package}`: want a {installer} package name (no URL, space, option or version)")
    version = _str(d["version"], f + ".version")
    if not re.fullmatch(version_re, version):
        _err(f + ".version", f"`{version}`: want one pinned version for {installer}, such as \"1.4.2\" (no range, "
                             f"no `latest`)")
    lo, hi, timeout = PARSER_TIMEOUT
    if "timeout" in d:
        timeout = d["timeout"]
        if type(timeout) is not int or not lo <= timeout <= hi:
            _err(f + ".timeout", f"want a whole number of seconds from {lo} to {hi}")
    if "skipped_text" in d:
        _template(d["skipped_text"], f + ".skipped_text", "name")
    return {"command": argv, "installer": installer, "package": package, "version": version, "timeout": timeout,
            "skipped_text": d.get("skipped_text")}


def _argv(v, field):
    """a command string split as a shell would split words (no shell runs it): non-empty, balanced quotes. The words are
    then held to the allowlist (PROGRAM, OPTION), which has no NUL."""
    _str(v, field)
    try:
        argv = shlex.split(v)
    except ValueError as e:
        _err(field, f"`{v}`: {e}")
    if not argv:
        _err(field, "want a command, not only whitespace")
    return argv


def parse(data):
    """the DataAdapter a parsed adapter file (a dict, as tomllib reads it) describes; AdapterFileError names the field."""
    _table(data, "", ("format", "name", "manifests", "extensions", "target-os", "lexer", "tests", "functions", "asserts",
                      "suppressions", "mutation", "limits", "parser", "commands", "run"),
           ("format", "name", "extensions") + (() if isinstance(data, dict) and "parser" in data
                                               else ("lexer", "tests", "asserts")))
    if type(data["format"]) is not int or data["format"] != FORMAT:
        _err("format", f"`{data['format']}`: want {FORMAT}")
    name = _str(data["name"], "name")
    if not all(ch.isalnum() or ch in "_-" for ch in name):
        _err("name", f"`{name}`: want letters, digits, _ or -")
    if name == RESERVED:
        _err("name", f"`{name}` is reserved (stack: auto finds the stack): want another name")
    _strs(data.get("manifests", []), "manifests")
    if "target-os" in data:
        target_os(data["target-os"])
    exts = _strs(data["extensions"], "extensions", nonempty=True)
    for i, e in enumerate(exts):
        if not e.startswith(".") or len(e) < 2:
            _err(f"extensions[{i}]", f"`{e}`: want a file extension such as \".ts\"")
        if e in exts[:i]:
            _err(f"extensions[{i}]", f"`{e}` is listed twice")
    run = data.get("run") if isinstance(data.get("run"), dict) else None
    if "parser" in data:
        parser = _parser(data)
        tool = _mutation(data.get("mutation", {}), run)
    else:
        lexer = _lexer(data["lexer"])
        _tests(data["tests"], lexer, "functions" in data)
        shapes = _functions(data["functions"], lexer) if "functions" in data else []
        _asserts(data["asserts"], lexer)
        _suppressions(data.get("suppressions", []))
        tool = _mutation(data.get("mutation", {}), run)
    if "run" in data and "commands" not in data:
        _err("commands", "missing: [run] needs [commands] (install, build, lint, test): R1 and R4 start from its test")
    if "commands" in data:  # the run side (#18) is the same beside [parser] (#27): it reads runner output, not source
        _commands(data["commands"], "run" in data)
    patterns = _run(data["run"]) if "run" in data else None
    adapter = ParserAdapter(data, parser, patterns) if "parser" in data else DataAdapter(data, lexer, shapes, patterns)
    adapter.limits = limits(data.get("limits", {}))
    adapter.mutation_tool = tool
    return adapter


def load(path):
    """the DataAdapter the adapter file at path describes. AdapterFileError: unreadable, not TOML, invalid, or no tomllib."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise AdapterFileError(f"adapter file {path}: cannot read: {e.strerror or e}") from None
    return loads(raw, path)


def loads(raw, path):
    """the DataAdapter of an adapter file's bytes (path names it in errors: a file on disk, or a repo path at a ref)."""
    try:
        import tomllib
    except ImportError:
        raise AdapterFileError(f"adapter file {path}: reading an adapter file needs python 3.11 or newer (tomllib)") from None
    try:
        # a UTF-8 BOM (some Windows editors write one) is not part of the TOML text
        data = tomllib.loads((raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw).decode("utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise AdapterFileError(f"adapter file {path}: not valid TOML: {e}") from None
    except UnicodeDecodeError as e:  # tomllib decodes the bytes as UTF-8 and lets this through
        raise AdapterFileError(f"adapter file {path}: not valid TOML: not UTF-8 ({e.reason} at byte {e.start})") from None
    except RecursionError:  # tomllib nests one python frame per array or inline table
        raise AdapterFileError(f"adapter file {path}: not valid TOML: arrays or tables nested too deep") from None
    try:
        return parse(data)
    except AdapterFileError as e:
        raise AdapterFileError(f"adapter file {path}: {e}") from None
