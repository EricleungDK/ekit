"""Adapter files (#16): load and validate a declarative TOML file that describes one stack, and build its DataAdapter.

Format: docs/mech-review-ci.md#adapter-file. Every problem is an AdapterFileError that names the field
(`lexer.strings[1].quote: want a non-empty string`): never a traceback, never a silent default for a bad value.
tomllib (python 3.11+) is imported only in load(), so the built-in adapters keep working on older pythons."""
import string

from .data_adapter import DataAdapter
from .scan import Lexer, ShapeError

FORMAT = 1
BLOCK_STYLES = ("braces", "indent", "keywords")
KINDS = ("eq", "ne", "other")
COVERS = ("line", "next-line", "file")
TARGET_OS = ("linux", "macos", "windows")  # the stack job outputs one of these; the workflow maps it to a fixed runner


class AdapterFileError(ValueError):
    pass


def _err(field, msg):
    raise AdapterFileError(f"{field}: {msg}" if field else msg)


def _table(d, field, allowed, required=()):
    if not isinstance(d, dict):
        _err(field, "want a table")
    for k in d:
        if k not in allowed:
            _err(f"{field}.{k}" if field else k, "unknown key")
    for k in required:
        if k not in d:
            _err(f"{field}.{k}" if field else k, "missing")
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
    field in a spec takes the value's text), so none is allowed. Each template has one placeholder name."""
    _str(v, field)
    try:
        parts = [(f, spec, conv) for _, f, spec, conv in string.Formatter().parse(v) if f is not None]
    except ValueError as e:
        _err(field, f"bad template: {e}")
    for f, _, _ in parts:
        if f != name:
            _err(field, f"unknown placeholder `{{{f}}}`: want `{{{name}}}`")
    try:
        v.format(**{name: "x"})
    except (ValueError, IndexError, KeyError) as e:
        _err(field, f"bad template: {e}")
    if any(spec or conv for _, spec, conv in parts):
        _err(field, f"`{v}`: want plain `{{{name}}}` (no `!` conversion or `:` spec)")
    return v


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


def _tests(d, lexer):
    f = "tests"
    _table(d, f, ("style", "groups", "cases", "separator", "skip", "only", "skip_modifiers", "only_modifiers",
                  "table_modifiers", "min_args", "not_after", "skipped_text"), ("style", "cases"))
    style = _str(d["style"], f + ".style")
    if style != "calls":
        _err(f + ".style", f"unknown style `{style}`: want calls")
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


def _mutation(d):
    f = "mutation"
    _table(d, f, ("skip_comments", "config_files", "config_name"))
    _strs(d.get("skip_comments", []), f + ".skip_comments")
    if _strs(d.get("config_files", []), f + ".config_files"):
        if "config_name" not in d:
            _err(f + ".config_name", "missing: config_files needs a name for the entry")
    if "config_name" in d:
        _str(d["config_name"], f + ".config_name")


def target_os(v, field="target-os"):
    """one of TARGET_OS, exactly (no case folding: the value is passed on to the workflow as it is)."""
    _str(v, field)
    if v not in TARGET_OS:
        _err(field, f"`{v}`: want linux, macos or windows")
    return v


def parse(data):
    """the DataAdapter a parsed adapter file (a dict, as tomllib reads it) describes; AdapterFileError names the field."""
    _table(data, "", ("format", "name", "manifests", "extensions", "target-os", "lexer", "tests", "functions", "asserts",
                      "suppressions", "mutation"), ("format", "name", "extensions", "lexer", "tests", "asserts"))
    if type(data["format"]) is not int or data["format"] != FORMAT:
        _err("format", f"`{data['format']}`: want {FORMAT}")
    name = _str(data["name"], "name")
    if not all(ch.isalnum() or ch in "_-" for ch in name):
        _err("name", f"`{name}`: want letters, digits, _ or -")
    _strs(data.get("manifests", []), "manifests")
    if "target-os" in data:
        target_os(data["target-os"])
    exts = _strs(data["extensions"], "extensions", nonempty=True)
    for i, e in enumerate(exts):
        if not e.startswith(".") or len(e) < 2:
            _err(f"extensions[{i}]", f"`{e}`: want a file extension such as \".ts\"")
        if e in exts[:i]:
            _err(f"extensions[{i}]", f"`{e}` is listed twice")
    lexer = _lexer(data["lexer"])
    _tests(data["tests"], lexer)
    shapes = _functions(data["functions"], lexer) if "functions" in data else []
    _asserts(data["asserts"], lexer)
    _suppressions(data.get("suppressions", []))
    _mutation(data.get("mutation", {}))
    return DataAdapter(data, lexer, shapes)


def load(path):
    """the DataAdapter the adapter file at path describes. AdapterFileError: unreadable, not TOML, invalid, or no tomllib."""
    try:
        import tomllib
    except ImportError:
        raise AdapterFileError(f"adapter file {path}: reading an adapter file needs python 3.11 or newer (tomllib)") from None
    try:
        with open(path, "rb") as f:
            raw = f.read()
        # a UTF-8 BOM (some Windows editors write one) is not part of the TOML text
        data = tomllib.loads((raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw).decode("utf-8"))
    except OSError as e:
        raise AdapterFileError(f"adapter file {path}: cannot read: {e.strerror or e}") from None
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
