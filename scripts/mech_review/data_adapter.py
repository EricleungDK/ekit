"""DataAdapter (#16): the Adapter interface (stack.py) implemented from a validated adapter file, through the generic
scanner (scan.py). R2 side only: test files, test fns, asserts, calls, suppressions, parse errors, mutation markers.
The run side (test command, outcomes) is #18; R2 is all `--adapter` drives for now."""
import os
import re

from .globs import any_glob
from .scan import Call, Lexer, line_of, norm
from .stack import Adapter, Assertion, Suppression, TestFn

DEFAULT_SKIPPED = "test `{name}` marked skipped"
DEFAULT_PROBLEM = "`{lints}` added without a reason"
DEFAULT_HINT = "fix the lint, or give the suppression a reason"


class DataAdapter(Adapter):
    from_file = True

    def __init__(self, cfg, source="<adapter file>"):
        """cfg: the adapter file's tables, validated by adapter_file.parse (shapes already parsed)."""
        self.cfg = cfg
        self.source = source
        self.name = cfg["name"]
        self.manifests = tuple(cfg.get("manifests", ()))
        self.extensions = tuple(cfg["extensions"])
        lx = cfg["lexer"]
        self.lexer = Lexer(lx["brackets"], lx.get("ident_chars", ""), lx.get("member", "."), lx.get("line_comments", ()),
                           lx.get("block_comments", ()), lx.get("strings", ()), lx.get("regex"))
        self.tests = cfg["tests"]
        self.chains = cfg["asserts"].get("chain", [])
        self.call_shapes = cfg["asserts"].get("call", [])
        self.fn_shapes = cfg.get("functions", {}).get("shapes", [])
        self.sups = cfg.get("suppressions", [])
        self.mutation = cfg.get("mutation", {})
        skip_words = [w for w in self.mutation.get("skip_comments", [])]
        self._skip_res = [re.compile(r"\s*" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"(?![\w])")
                          for phrase in skip_words]
        self._cache = {}

    # ---- parsing, once per text ----
    def _parse(self, text):
        hit = self._cache.get(text)
        if hit is None:
            m, comments, errors = self.lexer.mask(text)
            calls = self._calls(text, m)
            hit = (m, comments, errors, calls, self._scoped(calls), self.lexer.find_shapes(m, self.fn_shapes))
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[text] = hit
        return hit

    def _not_after(self, m, start):
        """the name at start follows a word that makes it a declaration (`function it(`): not a call. Read backwards on
        the masked text as it is: whitespace may sit before the name and between a word and punctuation (`function *`),
        and the char before the matched entry must not be a word char (`asyncfunction` is not `function`)."""
        is_ident = self.lexer.is_ident
        for w in self.tests.get("not_after", []):
            j, k = start - 1, len(w) - 1
            while k >= 0:
                # whitespace is skipped only at a token edge: before the name, or beside punctuation
                if k == len(w) - 1 or not is_ident(w[k]) or not is_ident(w[k + 1]):
                    while j >= 0 and m[j].isspace():
                        j -= 1
                if j < 0 or m[j] != w[k]:
                    break
                j, k = j - 1, k - 1
            if k < 0 and (j < 0 or not is_ident(m[j])):
                return True
        return False

    def _calls(self, text, m):
        lx, t = self.lexer, self.tests
        groups, cases = set(t.get("groups", [])), set(t["cases"])
        table = set(t.get("table_modifiers", []))
        out = []
        for w in lx.words(m):
            ident = w.group()
            if ident not in groups and ident not in cases:
                continue
            k, mods = w.end(), []
            while lx.member and m.startswith(lx.member, k):
                mw = lx.word_re.match(m, k + len(lx.member))
                if not mw:
                    break
                mods.append(mw.group())
                k = mw.end()
            open_ = lx.open_paren(m, k)
            if open_ is None or self._not_after(m, w.start()):
                continue
            if table & set(mods):
                open_ = lx.open_paren(m, lx.close_of(m, open_) + 1)
                if open_ is None:
                    continue
            args = lx.args_of(text, m, open_)
            is_group = ident in groups
            skip = (ident in t.get("skip", []) or any(x in t.get("skip_modifiers", []) for x in mods)
                    or (not is_group and len(args) < t.get("min_args", 0)))
            only = ident in t.get("only", []) or any(x in t.get("only_modifiers", []) for x in mods)
            name = lx.literal_value(args[0]) if args else ""
            out.append(Call("group" if is_group else "test", name, w.start(), lx.close_of(m, open_) + 1, skip, only, args))
        return out

    def _scoped(self, calls):
        """[(qualified name, Call, markers)]: a test's name joined with its enclosing groups by the separator."""
        sep = self.tests.get("separator", " > ")
        groups = [c for c in calls if c.kind == "group"]
        out = []
        for t in (c for c in calls if c.kind == "test"):
            encl = sorted((g for g in groups if g.start < t.start and t.end <= g.end), key=lambda g: g.start)
            markers = []
            if t.skip or any(g.skip for g in encl):
                markers.append("ignore")
            if t.only or any(g.only for g in encl):
                markers.append("only")
            out.append((sep.join([g.name for g in encl] + [t.name]), t, markers))
        return out

    # ---- the Adapter interface ----
    def classify(self, path, test_globs):
        if not path.endswith(self.extensions):
            return None
        return "test" if any_glob(path, test_globs) else "prod"

    def parse_error(self, text):
        m, _, errors, _, _, _ = self._parse(text)
        if errors:
            pos, msg = errors[0]
            return line_of(text, pos), msg
        return self.lexer.balance(text, m)

    def test_fns(self, text):
        _, _, _, _, tests, _ = self._parse(text)
        return [TestFn(name, line_of(text, t.start), markers) for name, t, markers in tests]

    def test_bodies(self, text):
        _, _, _, _, tests, _ = self._parse(text)
        return {name: (line_of(text, t.start), norm(text[t.start:t.end])) for name, t, _ in tests if not t.skip or t.args[1:]}

    def calls(self, text):
        m, _, _, _, tests, fns = self._parse(text)
        out = {}
        for name, t, _ in tests:
            out[name] = self.lexer.called(m[t.start:t.end])
        for name, s, e in fns:
            out.setdefault(name, set()).update(self.lexer.called(m[s:e]))
        return out

    def assertions(self, text):
        m, _, _, _, tests, fns = self._parse(text)
        lx = self.lexer
        spans = [(n, t.start, t.end) for n, t, _ in tests]
        owners = spans + list(fns)
        found = []  # (pos, end, kind, left, right)
        starts = {c["start"]: c for c in self.chains}
        shapes = {}
        for c in self.call_shapes:
            for n in c["names"]:
                shapes[n] = c
        for w in lx.words(m):
            ident = w.group()
            if ident in starts:
                r = self._chain(text, m, w, starts[ident])
            elif ident in shapes:
                r = self._call(text, m, w, shapes[ident])
            else:
                continue
            if r:
                found.append(r)
        out = []
        for pos, end, kind, left, right in found:
            test = next((n for n, s, t_end in reversed(spans) if s <= pos < t_end), None)
            hits = [o for o in owners if o[1] <= pos < o[2]]
            owner = max(hits, key=lambda o: o[1])[0] if hits else None
            out.append(Assertion(line_of(text, pos), test, test is not None, kind, left, right,
                                 " ".join(text[pos:end].split()), owner))
        return out

    def _chain(self, text, m, w, ch):
        """`start(actual).[negate|pass_through]*.matcher(expected)`: eq/ne for an eq matcher with an argument."""
        lx = self.lexer
        open_ = lx.open_paren(m, w.end())
        if open_ is None:
            return None
        close = lx.close_of(m, open_)
        args = lx.args_of(text, m, open_)
        left = norm(args[0]) if args else None
        pos_after, negated, matcher, margs = close + 1, False, None, []
        while True:
            mm = lx.member_after(m, pos_after)
            if not mm:
                break
            word, pos_after = mm
            if word in ch.get("negate", []):
                negated = True
            elif word in ch.get("pass_through", []):
                continue
            else:
                matcher = word
                break
        end = pos_after
        if matcher:
            mp = lx.open_paren(m, pos_after)
            if mp is not None:
                margs = lx.args_of(text, m, mp)
                end = lx.close_of(m, mp) + 1
        if matcher in ch.get("eq", []) and margs:
            return w.start(), end, "ne" if negated else "eq", left, norm(margs[0])
        return w.start(), end, "other", None, None

    def _call(self, text, m, w, shape):
        """`name(a, b)`: the shape's kind, operands by index."""
        lx = self.lexer
        open_ = lx.open_paren(m, w.end())
        if open_ is None:
            return None
        args = lx.args_of(text, m, open_)
        end = lx.close_of(m, open_) + 1
        ops = shape.get("operands")
        if shape["kind"] in ("eq", "ne") and ops and len(args) > max(ops):
            return w.start(), end, shape["kind"], norm(args[ops[0]]), norm(args[ops[1]])
        return w.start(), end, "other", None, None

    def suppressions(self, text):
        _, comments, _, _, _, _ = self._parse(text)
        total = text.count("\n") + 1
        out = []
        for start, end, body in comments:
            first, last = line_of(text, start), line_of(text, end)
            for sup in self.sups:
                hit = self._directive(body, sup)
                if hit is None:
                    continue
                kind, rest = hit
                if sup.get("reason_after"):
                    rules, _, reason = rest.partition(sup["reason_after"])
                    reason = reason.strip()
                else:
                    rules, reason = rest, rest.strip()
                    for chars in sup.get("reason_strip", []):
                        reason = reason.lstrip(chars).strip()
                lints = " ".join([kind] + rules.split()) if sup.get("lints") == "rules" else kind
                cover = sup["covers"][kind]
                region_end = {"line": last, "next-line": last + 1}.get(cover, total)
                out.append(Suppression(first, region_end, kind, lints, lints, bool(reason)))
                break
        return out

    @staticmethod
    def _directive(body, sup):
        """(directive, rest) when the comment body starts with one of the directives (longest first), else None."""
        s = body.lstrip()
        for d in sorted(sup["directives"], key=len, reverse=True):
            if s.startswith(d):
                nxt = s[len(d):len(d) + 1]
                if not nxt or not (nxt.isalnum() or nxt in "_-"):
                    return d, s[len(d):]
        return None

    def suppression_text(self, sup):
        for s in self.sups:
            if sup.kind in s["directives"]:
                return (s.get("problem", DEFAULT_PROBLEM).format(lints=sup.lint_text),
                        s.get("hint", DEFAULT_HINT).format(lints=sup.lint_text))
        return Adapter.suppression_text(self, sup)

    def ignored_text(self, name):
        return self.tests.get("skipped_text", DEFAULT_SKIPPED).format(name=name)

    def mutation_skips(self, text):
        _, comments, _, _, _, _ = self._parse(text)
        return [(line_of(text, start), line_of(text, end), " ".join(body.split())) for start, end, body in comments
                if any(r.match(body) for r in self._skip_res)]

    def mutation_config(self, path, load):
        if os.path.basename(path) in self.mutation.get("config_files", []):
            return self.mutation["config_name"]
        return None
