"""Generic lexical scanner for adapter files (#16): masking, bracket matching, argument splitting and shapes, all driven
by a lexer table. No parser and no regex from the file: the file names comment forms, string forms and words, and this
module does the reading (the same masking the built-in ts adapter does, with its constants turned into data).

Masked text keeps length and newlines; comments and literal contents are blanked, so brackets, words and calls are read
from code only."""
import re
from collections import namedtuple

Call = namedtuple("Call", "kind name start end skip only args")
Shape = namedtuple("Shape", "elems")
# one shape element: kind word|punct|name|id|group|block|body|run; value: words / literal / opener; opt: may be absent
Elem = namedtuple("Elem", "kind value opt")


class ShapeError(ValueError):
    pass


def norm(s):
    return None if s is None else re.sub(r"\s+", "", s)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


class Lexer:
    """The lexer table of one adapter file, validated (see adapter_file)."""

    def __init__(self, brackets, ident_chars, member, line_comments, block_comments, strings, regex):
        self.pairs = {b[0]: b[1] for b in brackets}
        self.opens = "".join(b[0] for b in brackets)
        self.closes = "".join(b[1] for b in brackets)
        self.ident_chars = ident_chars
        self.member = member
        self.line_comments = line_comments
        self.block_comments = block_comments
        self.strings = strings
        self.regex = regex
        self.word_re = re.compile(r"[\w%s]+" % re.escape(ident_chars))

    def is_ident(self, ch):
        return ch.isalnum() or ch == "_" or ch in self.ident_chars

    # ---- masking ----
    def mask(self, text):
        """(masked, comments [(start, end, body)], errors [(pos, message)])."""
        out = list(text)
        n = len(text)
        comments, errors = [], []

        def blank(a, b):
            for k in range(a, b):
                if out[k] != "\n":
                    out[k] = " "

        prev, word = "", ""  # last significant code char; last identifier when prev is one
        i = 0
        while i < n:
            c = text[i]
            if c.isspace():
                i += 1
                continue
            lc = next((t for t in self.line_comments if text.startswith(t, i)), None)
            if lc:
                j = text.find("\n", i)
                j = n if j < 0 else j
                comments.append((i, j, text[i + len(lc):j]))
                blank(i, j)
                i = j
                continue
            bc = next((b for b in self.block_comments if text.startswith(b[0], i)), None)
            if bc:
                j = text.find(bc[1], i + len(bc[0]))
                if j < 0:
                    errors.append((i, "unterminated block comment"))
                    comments.append((i, n, text[i + len(bc[0]):]))
                    blank(i, n)
                    i = n
                else:
                    comments.append((i, j + len(bc[1]), text[i + len(bc[0]):j]))
                    blank(i, j + len(bc[1]))
                    i = j + len(bc[1])
                continue
            s = next((s for s in self.strings if text.startswith(s["quote"], i)), None)
            if s:
                j, err = self._string_end(text, i, s)
                if err:
                    errors.append((i, err))
                blank(i, j)
                i = j
                prev, word = "x", ""
                continue
            rx = self.regex
            if rx and c == rx["delimiter"] and (prev == "" or prev in rx["after"] or (word and word in rx["after_words"])):
                j = self._regex_end(text, i)
                if j is not None:
                    blank(i, j)
                    i = j
                    prev, word = "x", ""
                    continue
            if self.is_ident(c):
                j = i
                while j < n and self.is_ident(text[j]):
                    j += 1
                word, prev = text[i:j], text[j - 1]
                i = j
                continue
            prev, word = c, ""
            i += 1
        return "".join(out), comments, errors

    @staticmethod
    def _string_end(text, i, s):
        """(end, error or None) of the string literal opening at i. A single-line string ends at the line end, no error."""
        n, q, esc = len(text), s["quote"], s.get("escape") or ""
        j = i + len(q)
        if not s.get("multiline"):
            while j < n and not text.startswith(q, j) and text[j] != "\n":
                j += len(esc) + 1 if esc and text.startswith(esc, j) else 1
            if j < n and text.startswith(q, j):
                return min(j + len(q), n), None
            return min(j, n), None
        interp = s.get("interpolation")
        depth = 0
        while j < n:
            if esc and text.startswith(esc, j):
                j += len(esc) + 1
                continue
            if depth == 0 and text.startswith(q, j):
                break
            if interp and depth == 0 and text.startswith(interp[0], j):
                depth, j = 1, j + len(interp[0])
                continue
            if depth and text.startswith(interp[1], j):
                depth = 0
            j += 1
        if j >= n:
            return n, f"unterminated {s.get('name') or 'string'}"
        return j + len(q), None

    def _regex_end(self, text, i):
        """end of a regex literal opening at i, or None (no closing delimiter on the line: an operator)."""
        n, d = len(text), self.regex["delimiter"]
        j, in_class = i + 1, False
        while j < n and text[j] != "\n":
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == d and not in_class:
                break
            j += 1
        if j < n and text[j] == d:
            j += 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            return j
        return None

    # ---- brackets and arguments (masked text) ----
    def close_of(self, m, i):
        """index of the bracket closing m[i], or len(m)-1."""
        depth = 0
        for j in range(i, len(m)):
            if m[j] in self.opens:
                depth += 1
            elif m[j] in self.closes:
                depth -= 1
                if depth == 0:
                    return j
        return len(m) - 1

    def args_of(self, text, m, i):
        """top-level comma-separated args of the call whose `(` is m[i]; text supplies the original spelling."""
        end = self.close_of(m, i)
        args, depth, start = [], 0, i + 1
        for j in range(i + 1, end):
            if m[j] in self.opens:
                depth += 1
            elif m[j] in self.closes:
                depth -= 1
            elif m[j] == "," and depth == 0:
                args.append(text[start:j].strip())
                start = j + 1
        last = text[start:end].strip()
        if last:
            args.append(last)
        return args

    def balance(self, text, m):
        """None, or (line, message) for the first bracket that does not balance in masked text m."""
        stack = []
        for i, ch in enumerate(m):
            if ch in self.pairs:
                stack.append((ch, i))
            elif ch in self.closes:
                if not stack or self.pairs[stack[-1][0]] != ch:
                    return line_of(text, i), f"unexpected `{ch}`"
                stack.pop()
        if stack:
            ch, i = stack[-1]
            return line_of(text, i), f"`{ch}` is never closed"
        return None

    # ---- words and calls ----
    def words(self, m, start=0, end=None):
        """identifier tokens of masked m (a word right after the member char is a member, not a word)."""
        end = len(m) if end is None else end
        for w in self.word_re.finditer(m, start, end):
            if self.member and w.start() > start and m[w.start() - 1] == self.member:
                continue
            yield w

    @staticmethod
    def skip_ws(m, k):
        while k < len(m) and m[k].isspace():
            k += 1
        return k

    def open_paren(self, m, k):
        """index of the `(` that follows position k after whitespace, or None."""
        k = self.skip_ws(m, k)
        return k if k < len(m) and m[k] == "(" else None

    def member_after(self, m, k):
        """(name, end) of `.name` after k (whitespace allowed around the member char), or None."""
        if not self.member:
            return None
        k = self.skip_ws(m, k)
        if not m.startswith(self.member, k):
            return None
        w = self.word_re.match(m, self.skip_ws(m, k + len(self.member)))
        return (w.group(), w.end()) if w else None

    def called(self, m):
        """bare names called in masked m: `name(` (a method call is not a call)."""
        return {w.group() for w in self.words(m) if not w.group()[0].isdigit() and self.open_paren(m, w.end()) is not None}

    def literal_value(self, raw):
        """a string literal's value (escapes dropped), else the text whitespace-normalized."""
        r = raw.strip()
        for s in self.strings:
            q, esc = s["quote"], s.get("escape") or ""
            if len(r) >= 2 * len(q) and r.startswith(q) and r.endswith(q):
                inner = r[len(q):len(r) - len(q)]
                return re.sub(re.escape(esc) + "(.)", r"\1", inner) if esc else inner
        return " ".join(r.split())

    # ---- shapes ----
    def parse_shape(self, src):
        """a shape string (see docs) as a Shape; ShapeError names the bad element."""
        elems = []
        toks = src.split()
        for t in toks:
            opt = t.endswith("?") and len(t) > 1
            body = t[:-1] if opt else t
            if body == "NAME":
                elems.append(Elem("name", None, opt))
            elif body == "ID":
                elems.append(Elem("id", None, opt))
            elif body == "BODY":
                elems.append(Elem("body", None, opt))
            elif len(body) == 5 and body[1:4] == "..." and self.pairs.get(body[0]) == body[4]:
                elems.append(Elem("group", body[0], opt))
            elif len(body) == 8 and body.startswith("...") and body[4:7] == "..." and self.pairs.get(body[3]) == body[7]:
                elems.append(Elem("block", body[3], opt))
            elif body.endswith("...") and len(body) > 3 and not any(self.is_ident(ch) for ch in body[:-3]):
                elems.append(Elem("run", body[:-3], opt))
            elif all(self.is_ident(ch) or ch == "|" for ch in body) and all(body.split("|")):
                elems.append(Elem("word", tuple(body.split("|")), opt))
            elif body and not any(self.is_ident(ch) or ch == "." for ch in body):
                elems.append(Elem("punct", body, opt))
            else:
                raise ShapeError(f"unknown element `{t}`")
        if sum(1 for e in elems if e.kind == "name") != 1:
            raise ShapeError("want exactly one NAME")
        if any(e.kind == "name" and e.opt for e in elems):
            raise ShapeError("NAME cannot be optional")
        if not elems or elems[-1].kind not in ("group", "block", "body") or elems[-1].opt:
            raise ShapeError("must end with a body: `{...}`, `...{...}` or BODY")
        first = next((e for e in elems if not e.opt), None)
        if first is None or first.kind != "word":
            raise ShapeError("the first required element must be a word")
        for a, b in zip(elems, elems[1:] + [None]):
            if a.kind == "run" and (b is None or b.kind != "punct"):
                raise ShapeError(f"`{a.value}...` must be followed by a literal")
        return Shape(tuple(elems))

    def _body_after(self, m, j):
        """(start, end) of a body at j: a `{ ... }` block, or an expression to `;`, a line end or a closing bracket."""
        j = self.skip_ws(m, j)
        if j < len(m) and m[j] == "{":
            return j, self.close_of(m, j) + 1
        depth, k = 0, j
        while k < len(m):
            ch = m[k]
            if ch in self.opens:
                depth += 1
            elif ch in self.closes:
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and ch in ";\n":
                break
            k += 1
        return j, k

    def _match(self, m, elems, idx, pos, got):
        """(end, name, head end) when elems[idx:] match at pos, else None. Whitespace may sit between elements."""
        if idx == len(elems):
            return pos, got.get("name"), got.get("head", pos)
        e = elems[idx]
        if e.opt:
            r = self._step(m, elems, idx, pos, dict(got))
            return r if r is not None else self._match(m, elems, idx + 1, pos, got)
        return self._step(m, elems, idx, pos, got)

    def _step(self, m, elems, idx, pos, got):
        e = elems[idx]
        k = self.skip_ws(m, pos) if idx else pos
        if e.kind in ("word", "name", "id"):
            w = self.word_re.match(m, k)
            if not w or (e.kind == "word" and w.group() not in e.value) or (e.kind != "word" and w.group()[0].isdigit()):
                return None
            if e.kind == "name":
                got["name"] = w.group()
            return self._match(m, elems, idx + 1, w.end(), got)
        if e.kind == "punct":
            return self._match(m, elems, idx + 1, k + len(e.value), got) if m.startswith(e.value, k) else None
        if e.kind == "run":
            if not m.startswith(e.value, k):
                return None
            stop = elems[idx + 1].value[0]
            j = k + len(e.value)
            s = j
            while j < len(m) and m[j] not in ("\n", stop):
                j += 1
            return self._match(m, elems, idx + 1, j, got) if j > s else None
        got.setdefault("head", k)
        if e.kind == "group":
            if k >= len(m) or m[k] != e.value:
                return None
            return self._match(m, elems, idx + 1, self.close_of(m, k) + 1, got)
        if e.kind == "block":
            b = m.find(e.value, k)
            if b < 0:
                return None
            return self._match(m, elems, idx + 1, self.close_of(m, b) + 1, got)
        _, end = self._body_after(m, k)
        return self._match(m, elems, idx + 1, end, got)

    def find_shapes(self, m, shapes):
        """[(name, start, end)] for each shape, in shape order; matches of one shape do not overlap (head)."""
        out = []
        for sh in shapes:
            after = 0
            for w in self.words(m):
                if w.start() < after:
                    continue
                r = self._match(m, sh.elems, 0, w.start(), {})
                if r:
                    end, name, head = r
                    out.append((name, w.start(), end))
                    after = head
        return out
