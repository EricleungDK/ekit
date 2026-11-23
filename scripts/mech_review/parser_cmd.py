"""The parser command of an adapter file (#27): run it on one file and check the facts it prints.

For a language the lexer table cannot describe, an adapter file's `[parser]` names one command in place of patterns.
It gets one file's text on stdin and its path as its last argument, and prints the file's facts as one JSON object on
stdout: the adapter interface (stack.py) serialized. Schema (docs/mech-review-ci.md#parser), every key required,
no other key:
  format          1
  parse_error     null, or {line, message}: the file does not parse; the other lists are then not read
  tests           [{name, line, end_line, markers, body, calls}]  markers: ignore | only | should_panic, each once;
                  body: null or [first, last] lines of the body, within [line, end_line]; calls: names the test calls
  asserts         [{line, test, owner, kind, left, right, text}]  test: a name in tests, or null (outside tests);
                  owner: the innermost test or function holding it, or null; kind: eq | ne | other; left/right: the
                  operands (strings) for eq and ne, null for other; text: the assert, for messages
  suppressions    [{line, end_line, kind, lints, reason}]  kind: the directive; lints: the entry's name for it;
                  reason: true when the suppression gives one
  mutation_skips  [{line, end_line, marker}]
A line is a whole number (never a bool) from 1 to the file's line count; an end is never before its start.

The command is argv (split at load, never a shell string). It runs with the file's text on stdin, a fresh empty temp dir
as its cwd and HOME (no project config, no checkout), a minimal environment (PATH and a UTF-8 locale: no token, no
secret) and a timeout. A command that cannot run, exits non-zero, times out, or prints what the schema refuses is a
ParserError: R2 turns it into one blocking CI entry. Nothing falls back to patterns."""
import json
import os
import re
import signal
import subprocess
import tempfile

FORMAT = 1
MAX_OUTPUT = 16 * 1024 * 1024  # bytes of stdout: more is refused, not read
MAX_ITEMS = 100000  # entries per list
MAX_TEXT = 65536  # characters per string
MAX_DEPTH = 32  # nested arrays and objects: the facts nest 4 deep; checked by the core, whatever python's own limit
MARKERS = ("ignore", "only", "should_panic")
KINDS = ("eq", "ne", "other")
TOP = ("format", "parse_error", "tests", "asserts", "suppressions", "mutation_skips")


SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
# installer: (package name, exact version, install steps (package, version, prefix), the dir its programs land in under
# the prefix, the environment they run with). A closed set: the core builds the install step (#27) into a prefix of
# its own per installer, package and version, and runs the parser program from there only, never from PATH. A version
# is one release, never a range (the package's own dependencies resolve at install time); each name pattern leaves out
# URLs, spaces, options and version syntax.
INSTALLERS = {
    "pip": (r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?",
            r"\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?",
            lambda p, v, d: [["python3", "-m", "venv", d], [f"{d}/bin/python", "-m", "pip", "install", f"{p}=={v}"]],
            "bin", lambda d: {}),
    "npm": (r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", SEMVER,
            lambda p, v, d: [["npm", "install", "--no-save", "--prefix", d, f"{p}@{v}"]],
            "node_modules/.bin", lambda d: {}),
    "cargo": (r"[A-Za-z][A-Za-z0-9_-]{0,63}", SEMVER,
              lambda p, v, d: [["cargo", "install", p, "--version", v, "--locked", "--root", d]],
              "bin", lambda d: {}),
    "gem": (r"[A-Za-z0-9][A-Za-z0-9._-]*", r"\d+(?:\.[0-9A-Za-z]+)*",
            lambda p, v, d: [["gem", "install", p, "-v", v, "--install-dir", d, "--bindir", f"{d}/bin"]],
            "bin", lambda d: {"GEM_HOME": d, "GEM_PATH": d}),
    "go": (r"[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+(?:/(?!\.\.?(?:/|$))[A-Za-z0-9._~-]+)+", "v?" + SEMVER,
           lambda p, v, d: [["env", f"GOBIN={d}/bin", "go", "install", f"{p}@v{v.removeprefix('v')}"]],
           "bin", lambda d: {}),
}
HOME_VAR = "EKIT_PARSER_HOME"  # the dir the prefixes sit under: set by the workflow (#17) and the tests, never a PR


def home():
    """the dir every parser prefix sits under: $EKIT_PARSER_HOME, else ~/.cache/ekit/parsers."""
    return os.environ.get(HOME_VAR) or os.path.join(os.path.expanduser("~"), ".cache", "ekit", "parsers")


def prefix(parser, at):
    """the install dir of the parser's package at its version, under at (home())."""
    return "/".join([at.rstrip("/"), parser["installer"], parser["package"], parser["version"]])


def install_steps(parser, at):
    """the argvs that install the parser at its pinned version into its prefix under at (#17's workflow step runs them
    in order): parser is the [parser] table as adapter_file validated it."""
    return INSTALLERS[parser["installer"]][2](parser["package"], parser["version"], prefix(parser, at))


def program_path(parser, at):
    """where the parser program (the command's first word) is after install_steps: the only place it is run from."""
    return "/".join([prefix(parser, at), INSTALLERS[parser["installer"]][3], parser["command"][0]])


def run_env(parser, at):
    """the variables the installed program needs beside the minimal environment (gem: where its gems are)."""
    return INSTALLERS[parser["installer"]][4](prefix(parser, at))


def installed(parser, at):
    """the parser's argv with its program resolved in its prefix; ParserError when the package did not install it."""
    program = program_path(parser, at)
    if not (os.path.isfile(program) and os.access(program, os.X_OK)):
        raise ParserError(f"not installed by the declared package ({parser['installer']} {parser['package']} "
                          f"{parser['version']}: no program at {program})")
    return [program] + list(parser["command"][1:])


class ParserError(Exception):
    """the parser command failed on one file: it cannot run, exited non-zero, timed out, or printed invalid facts."""


def run(argv, path, text, timeout, roots=(), extra_env=None):
    """the facts (validated, see the module docstring) the command argv prints for the file at path whose text is text.
    roots: the checkout dirs (the reviewed repo, the engine's worktrees): a word of argv that is a path inside one (or a
    `--flag=<path>` word whose value is) is refused before anything runs, since it would run the PR's code or read its
    config. ParserError names what went wrong."""
    for w in argv:
        # every `/` in a word starts a path it may name (the program, `--a=b:/x`): none may lead into a root
        if any(_inside(w[i:], roots) for i, ch in enumerate(w) if ch == "/"):
            raise ParserError(f"`{w}` is inside the checkout: the parser runs no code or config from the PR")
    with tempfile.TemporaryDirectory(prefix="ekit-parser-") as tmp:
        work = os.path.join(tmp, "cwd")
        os.mkdir(work)
        env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": work, "TMPDIR": work, "LANG": "C.UTF-8",
               "LC_ALL": "C.UTF-8", **(extra_env or {})}
        with open(os.path.join(tmp, "stdin"), "w+b") as fin, open(os.path.join(tmp, "stdout"), "w+b") as fout, \
                open(os.path.join(tmp, "stderr"), "w+b") as ferr:
            fin.write(text.encode("utf-8", "surrogateescape"))
            fin.seek(0)
            try:
                proc = subprocess.Popen(list(argv) + [path], stdin=fin, stdout=fout, stderr=ferr, cwd=work, env=env,
                                        start_new_session=True)
            except (OSError, ValueError) as e:
                raise ParserError(f"cannot run `{argv[0]}`: {getattr(e, 'strerror', None) or e}") from None
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill(proc)
                raise ParserError(f"timed out after {timeout}s") from None
            finally:
                _kill(proc)  # whatever it left running in its session
            if rc != 0:
                ferr.seek(0)
                tail = ferr.read()[-400:].decode("utf-8", "replace").strip()
                raise ParserError(f"exited with status {rc}" + (f": {tail}" if tail else ""))
            if os.fstat(fout.fileno()).st_size > MAX_OUTPUT:  # the size, whatever offset the command left
                raise ParserError(f"printed more than {MAX_OUTPUT} bytes")
            fout.seek(0)
            out = fout.read()
    return check(out, text)


def _inside(p, roots):
    """p, as written or resolved, is a root or under one (a sibling `/repo2` is not under `/repo`)."""
    seen = {os.path.normpath(p), os.path.realpath(p)}
    tops = {t for x in roots for t in (os.path.normpath(os.path.abspath(x)), os.path.realpath(x))}
    return any(f == t or f.startswith(t.rstrip(os.sep) + os.sep) for f in seen for t in tops)


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, AttributeError):  # gone already; no process groups (Windows): kill the process alone
        try:
            proc.kill()
        except OSError:
            pass
    proc.wait()


class _Bad(ValueError):
    pass


def _no_dupes(pairs):
    """an object's pairs as a dict: a key given twice is refused (linear: a set of the keys seen), and so is a key that
    could not be echoed safely in a message (a lone surrogate, a control character)."""
    seen = set()
    for k, _ in pairs:
        if _unsafe(k):
            raise _Bad("a key holds a lone surrogate or a control character")
        if k in seen:
            raise _Bad(f"key `{k[:80]}` given twice")
        seen.add(k)
    return dict(pairs)


def _unsafe(v, allowed=frozenset()):
    """why v cannot reach an entry, an id or a comment as it is, else None: a lone surrogate (it has no UTF-8 form), or
    a control character not in allowed."""
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        return "want text without a lone surrogate"
    if any((ord(ch) < 0x20 or 0x7f <= ord(ch) <= 0x9f) and ch not in allowed for ch in v):
        return "want text without control characters"
    return None


def _depth(text):
    """the deepest nesting of arrays and objects in JSON text, brackets inside strings not counted (linear)."""
    depth = deepest = 0
    in_str = escaped = False
    for ch in text:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif ch in "]}":
            depth -= 1
    return deepest


def _no_constant(name):
    raise _Bad(f"`{name}` is not JSON")


def check(raw, text):
    """the facts in raw (the command's stdout, bytes) for a file whose text is text, validated: ParserError otherwise."""
    try:
        body = raw.decode("utf-8")
        if _depth(body) > MAX_DEPTH:
            raise RecursionError
        doc = json.loads(body, object_pairs_hook=_no_dupes, parse_constant=_no_constant)
    except UnicodeDecodeError as e:
        raise ParserError(f"printed invalid JSON: not UTF-8 ({e.reason} at byte {e.start})") from None
    except _Bad as e:
        raise ParserError(f"printed invalid JSON: {e}") from None
    except ValueError as e:
        raise ParserError(f"printed invalid JSON: {e}") from None
    except RecursionError:
        raise ParserError("printed invalid JSON: nested too deep") from None
    try:
        return _facts(doc, text.count("\n") + 1)
    except _Bad as e:
        raise ParserError(f"printed facts the schema refuses: {e}") from None


def _obj(v, field, keys):
    if not isinstance(v, dict):
        raise _Bad(f"{field}: want an object")
    for k in v:
        if k not in keys:
            raise _Bad(f"{field}.{k}: unknown key")
    for k in keys:
        if k not in v:
            raise _Bad(f"{field}.{k}: missing")
    return v


def _list(v, field):
    if not isinstance(v, list):
        raise _Bad(f"{field}: want a list")
    if len(v) > MAX_ITEMS:
        raise _Bad(f"{field}: more than {MAX_ITEMS} entries")
    return v


def _str(v, field, null=False, allowed=frozenset()):
    """a string with something in it besides whitespace; allowed: the control characters it may hold (a multi-line
    assert's text, a parse error's message: tab and line ends)."""
    if v is None and null:
        return None
    if not isinstance(v, str) or not v.strip():
        raise _Bad(f"{field}: want a non-empty string" + (" or null" if null else ""))
    if len(v) > MAX_TEXT:
        raise _Bad(f"{field}: longer than {MAX_TEXT} characters")
    why = _unsafe(v, allowed)
    if why:
        raise _Bad(f"{field}: {why}")
    return v


MULTILINE = frozenset(map(chr, (9, 10, 13)))  # tab, line feed, carriage return


def _line(v, field, n_lines, start=1):
    if type(v) is not int or not start <= v <= n_lines:
        raise _Bad(f"{field}: want a whole number from {start} to {n_lines}")
    return v


def _span(d, field, n_lines):
    first = _line(d["line"], field + ".line", n_lines)
    return first, _line(d["end_line"], field + ".end_line", n_lines, first)


def _facts(doc, n_lines):
    _obj(doc, "facts", TOP)
    if type(doc["format"]) is not int or doc["format"] != FORMAT:
        raise _Bad(f"format: want {FORMAT}")
    out = {k: [] for k in TOP[2:]}
    pe = doc["parse_error"]
    if pe is not None:
        _obj(pe, "parse_error", ("line", "message"))
        out["parse_error"] = (_line(pe["line"], "parse_error.line", n_lines), _str(pe["message"], "parse_error.message", allowed=MULTILINE))
    else:
        out["parse_error"] = None
    spans = {}  # test name: [(line, end_line)], to place each assert in its test
    for i, t in enumerate(_list(doc["tests"], "tests")):
        f = f"tests[{i}]"
        _obj(t, f, ("name", "line", "end_line", "markers", "body", "calls"))
        line, end = _span(t, f, n_lines)
        markers = _list(t["markers"], f + ".markers")
        for j, m in enumerate(markers):
            if m not in MARKERS:
                raise _Bad(f"{f}.markers[{j}]: want ignore, only or should_panic")
            if m in markers[:j]:
                raise _Bad(f"{f}.markers[{j}]: `{m}` given twice")
        body = t["body"]
        if body is not None:
            if not isinstance(body, list) or len(body) != 2:
                raise _Bad(f"{f}.body: want null or [first, last]")
            b0 = _line(body[0], f + ".body[0]", end, line)
            body = (b0, _line(body[1], f + ".body[1]", end, b0))
        calls = {_str(c, f"{f}.calls[{j}]") for j, c in enumerate(_list(t["calls"], f + ".calls"))}
        name = _str(t["name"], f + ".name")
        spans.setdefault(name, []).append((line, end))
        out["tests"].append((name, line, end, list(markers), body, calls))
    for i, a in enumerate(_list(doc["asserts"], "asserts")):
        f = f"asserts[{i}]"
        _obj(a, f, ("line", "test", "owner", "kind", "left", "right", "text"))
        test = _str(a["test"], f + ".test", null=True)
        if test is not None and test not in spans:
            raise _Bad(f"{f}.test: `{test}` is not a name in tests")
        line = _line(a["line"], f + ".line", n_lines)
        if test is not None and not any(b <= line <= e for b, e in spans[test]):
            where = ", ".join(f"lines {b} to {e}" for b, e in spans[test][:5])
            raise _Bad(f"{f}.line: {line} is outside test `{test}` ({where})")
        kind = a["kind"]
        if kind not in KINDS:
            raise _Bad(f"{f}.kind: want eq, ne or other")
        if kind == "other":
            if a["left"] is not None or a["right"] is not None:
                raise _Bad(f"{f}: kind other has no operands: want left and right null")
            left = right = None
        else:
            left, right = (_str(a[k], f"{f}.{k}", allowed=MULTILINE) for k in ("left", "right"))
        out["asserts"].append((line, test, _str(a["owner"], f + ".owner", null=True),
                               kind, left, right, _str(a["text"], f + ".text", allowed=MULTILINE)))
    for i, s in enumerate(_list(doc["suppressions"], "suppressions")):
        f = f"suppressions[{i}]"
        _obj(s, f, ("line", "end_line", "kind", "lints", "reason"))
        if not isinstance(s["reason"], bool):
            raise _Bad(f"{f}.reason: want true or false")
        out["suppressions"].append((*_span(s, f, n_lines), _str(s["kind"], f + ".kind"), _str(s["lints"], f + ".lints"),
                                    s["reason"]))
    for i, s in enumerate(_list(doc["mutation_skips"], "mutation_skips")):
        f = f"mutation_skips[{i}]"
        _obj(s, f, ("line", "end_line", "marker"))
        out["mutation_skips"].append((*_span(s, f, n_lines), _str(s["marker"], f + ".marker")))
    return out
