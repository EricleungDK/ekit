"""Declared tests (#22): `[tests] style = "declared"`. A test is a named function (a `[functions]` shape) with a
marker before it (`@Test void adds() {`), not a call (`test("adds", fn)`): JUnit, and any language whose tests are
marked declarations. Groups are declarations too: `<word> NAME ... {...}` for a word of tests.groups (`class CalcTest {`),
its markers read the same way (`@Disabled class X` skips the tests in it).

A marker is the prefix, then a word, dotted or not (`@Test`, `@org.junit.jupiter.api.Test`: its last word counts),
then optionally a bracket group (`@Disabled("later")`). The markers of a declaration are those right before its first
word, with plain words (modifiers: `public static`) between them; anything else ends them. Everything is read from the
masked text (scan.Lexer.mask): a marker in a string or a comment never counts."""
from .scan import Call, line_of


def _open_of(lx, m, j):
    """index of the bracket that opens the one closing at m[j], or None (none opens it)."""
    depth = 0
    for i in range(j, -1, -1):
        if m[i] in lx.closes:
            depth += 1
        elif m[i] in lx.opens:
            depth -= 1
            if depth == 0:
                return i
    return None


def _word_before(lx, m, j):
    """start of the identifier that ends at m[j] (inclusive)."""
    while j >= 0 and lx.is_ident(m[j]):
        j -= 1
    return j + 1


def _marker_at(lx, m, start, prefix):
    """start of the marker whose word starts at start (`a.b.Name`: the chain back to the prefix), or None."""
    k = start
    while lx.member and k >= len(lx.member) and m.startswith(lx.member, k - len(lx.member)):
        w = _word_before(lx, m, k - len(lx.member) - 1)
        if w == k - len(lx.member):
            return None
        k = w
    return k - len(prefix) if k >= len(prefix) and m.startswith(prefix, k - len(prefix)) else None


def markers(lx, m, start, prefix):
    """the marker words right before position start (a declaration's first word), nearest first."""
    out, k = [], start
    while True:
        j = k - 1
        while j >= 0 and m[j].isspace():
            j -= 1
        group = j >= 0 and m[j] in lx.closes
        if group:
            j = _open_of(lx, m, j)
            if j is None:
                return out
            j -= 1
            while j >= 0 and m[j].isspace():
                j -= 1
        if j < 0 or not lx.is_ident(m[j]):
            return out
        w = _word_before(lx, m, j)
        at = _marker_at(lx, m, w, prefix)
        if at is None and group:  # a group after a plain word is a call, not a marker
            return out
        if at is not None:
            out.append(m[w:j + 1])
        k = w if at is None else at


def _groups(lx, cfg, m):
    """[(name, start, end, markers)] of the group declarations: a group word, then a NAME word, then its block."""
    words, prefix = set(cfg.get("groups", [])), cfg["prefix"]
    out = []
    for w in lx.words(m):
        if w.group() not in words:
            continue
        name = lx.word_re.match(m, lx.skip_ws(m, w.end()))
        brace = m.find("{", w.end())
        if not name or name.group()[0].isdigit() or brace < 0:
            continue
        out.append((name.group(), w.start(), lx.close_of(m, brace) + 1, markers(lx, m, w.start(), prefix)))
    return out


def tests(lx, cfg, m, fns):
    """[(qualified name, Call, markers)] of the functions (fns: find_shapes' [(name, start, end)]) with a case marker:
    the name joined with its enclosing groups' names by tests.separator; markers `ignore` (a skip marker on the test
    or a group around it) and `only`."""
    cases, skip, only = set(cfg["cases"]), set(cfg.get("skip", [])), set(cfg.get("only", []))
    sep = cfg.get("separator", " > ")
    groups = _groups(lx, cfg, m)
    out = []
    for name, start, end in sorted(fns, key=lambda f: f[1]):  # source order: [functions] finds them shape by shape
        own = markers(lx, m, start, cfg["prefix"])
        if not cases.intersection(own):
            continue
        encl = sorted((g for g in groups if g[1] < start and end <= g[2]), key=lambda g: g[1])
        marks = [g[3] for g in encl] + [own]
        flags = [f for f, words in (("ignore", skip), ("only", only)) if any(words.intersection(x) for x in marks)]
        call = Call("test", name, start, end, "ignore" in flags, "only" in flags, ())
        out.append((sep.join([g[0] for g in encl] + [name]), call, flags))
    return out


def body(text, m, lx, call):
    """(first, last) lines strictly inside the test function's closing block, or None (a body on one or two lines)."""
    close = call.end - 1
    open_ = _open_of(lx, m, close) if 0 <= close < len(m) and m[close] == "}" else None
    if open_ is None:
        return None
    first, last = line_of(text, open_) + 1, line_of(text, close) - 1
    return (first, last) if first <= last else None
