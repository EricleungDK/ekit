"""DataAdapter (#16): the Adapter interface (stack.py) implemented from a validated adapter file, through the generic
scanner (scan.py). R2 side: test files, test fns, asserts, calls, suppressions, parse errors, mutation markers.
Run side (#18, [run] and [commands]): the test command for a checkout, one named test's argv, the verdict of a run.
R3 through a file (the [mutation] tool and its report) is #19."""
import functools
import json
import os
import re
import shlex

from .globs import any_glob
from .scan import Call, line_of, norm
from .stack import Adapter, Assertion, Suppression, TestFn, _callback_inner

DEFAULT_SKIPPED = "test `{name}` marked skipped"
DEFAULT_PROBLEM = "`{lints}` added without a reason"
DEFAULT_HINT = "fix the lint, or give the suppression a reason"


class DataAdapter(Adapter):
    from_file = True

    def __init__(self, cfg, lexer, fn_shapes, run_patterns=None):
        """cfg: the adapter file's tables, validated by adapter_file.parse; lexer, fn_shapes and run_patterns (the
        compiled [run] regexes, None without [run]): built there from them."""
        self.name = cfg["name"]
        self.manifests = tuple(cfg.get("manifests", ()))
        self.target_os = cfg.get("target-os", "linux")
        self.extensions = tuple(cfg["extensions"])
        self.lexer = lexer
        self.tests = cfg["tests"]
        self.chains = cfg["asserts"].get("chain", [])
        self.call_shapes = cfg["asserts"].get("call", [])
        self.fn_shapes = fn_shapes
        self.sups = cfg.get("suppressions", [])
        self.mutation = cfg.get("mutation", {})
        self._skip_res = [re.compile(r"\s*" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"(?![\w])")
                          for phrase in self.mutation.get("skip_comments", [])]
        self.commands = dict(cfg.get("commands", {}))  # install, build, lint, test ("" = none): ci-doctor reads them
        self.run = cfg.get("run")  # None: R2 only (red and all refuse the file)
        self.default_test_cmd = self.commands.get("test", "")
        self._rx = run_patterns or {}
        # R2 asks several methods about the same text (base and head of each file): scan each text once
        self._parse = functools.lru_cache(maxsize=8)(self._scan)

    # ---- parsing ----
    def _scan(self, text):
        m, comments, errors = self.lexer.mask(text)
        calls = self._calls(text, m)
        return m, comments, errors, calls, self._scoped(calls), self.lexer.find_shapes(m, self.fn_shapes)

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
        m, _, _, _, tests, _ = self._parse(text)
        return [TestFn(name, line_of(text, t.start), markers, _callback_inner(text, m, t.start, t.end))
                for name, t, markers in tests]

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
        if matcher in ch["eq"] and margs:
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
        """the texts of the family whose directive made sup (suppressions() only makes them from a family)."""
        s = next(s for s in self.sups if sup.kind in s["directives"])
        return (s.get("problem", DEFAULT_PROBLEM).format(lints=sup.lint_text),
                s.get("hint", DEFAULT_HINT).format(lints=sup.lint_text))

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

    # ---- the run side: [run] and [commands] (R1, R4) ----
    def notes(self):
        """what the result says about the file's [commands]: each of install and build it declares as none ("")."""
        return [f'adapter file declares no {k} command (commands.{k} = "")' for k in ("install", "build")
                if k in self.commands and not self.commands[k].strip()]

    def test_cmd_in(self, crate):
        """the command of the first runner whose `when` holds in the crate dir, else [commands].test."""
        for r in self.run.get("runner", []):
            if "when" in r and _holds(r["when"], crate):
                return r["command"]
        return self.default_test_cmd

    def worktree_setup(self, repo, wt, project_dir):
        """[run].links: each directory (project-dir relative, an install the checkout does not track: node_modules) is
        linked from the caller's checkout into the worktree, when the caller has it as a directory (as the built-in ts
        does) and the worktree does not."""
        for rel in self.run.get("links", []):
            src = os.path.join(repo, project_dir, rel)
            dst = os.path.join(wt, project_dir, rel)
            if os.path.isdir(src) and os.path.isdir(os.path.dirname(dst)) and not os.path.lexists(dst):
                os.symlink(os.path.abspath(src), dst)

    def _runner(self, argv):
        """the first [[run.runner]] whose match is in one of the command's words (one with no match takes any), or None."""
        for r in self.run.get("runner", []):
            if "match" not in r or any(r["match"] in a for a in argv):
                return r
        return None

    def test_argv(self, cmd, path, name):
        """the command's words (the runner's subcommand put in when missing), then [run].test with {path} and {name}:
        the test's qualified name split at tests.separator, each part quoted by [run.name], joined by the runner's
        separator."""
        argv = shlex.split(cmd)
        runner = self._runner(argv) or {}
        sub = runner.get("subcommand")
        if sub and sub["word"] not in argv:
            after = sub.get("after")
            at = next((i for i, a in enumerate(argv) if after and after in a), len(argv) - 1)
            argv = argv[:at + 1] + [sub["word"]] + argv[at + 1:]
        own = self.tests.get("separator", " > ")
        joined = runner.get("separator", own).join(self._quote(seg) for seg in name.split(own))
        return argv + [w.format(path=path, name=joined) for w in self.run["test"]]

    def _quote(self, seg):
        """a name part as the runner reads it: [run.name] escape characters get a backslash, placeholders (it.each's
        `%s`) become `any`. No [run.name]: the part as it is."""
        nm = self.run.get("name", {})
        esc = nm.get("escape", "")

        def escaped(text):
            return "".join("\\" + ch if ch in esc else ch for ch in text)

        if "placeholders" not in self._rx:
            return escaped(seg)
        pieces, at = [], 0  # split at the placeholders' matches that hold text; an empty match replaces nothing
        for m in _matches(self._rx["placeholders"], seg):
            pieces.append(seg[at:m.start()])
            at = m.end()
        return nm["any"].join(escaped(p) for p in pieces + [seg[at:]])  # load: any comes with placeholders

    def _count(self, key, text):
        rx = self._rx.get(key)
        groups = (m.group(1) for m in _matches(rx, text))  # no pattern: no match; an optional group may be None
        return sum(int(g) for g in groups if g is not None and g.isdigit())

    def why(self, verdict, out):
        """the output line a run's verdict came from, when a pattern decided it (env, no_test: what the note or entry
        quotes in place of the first line, a banner), else None."""
        rx = self._rx.get({"env": "env", "none": "no_test"}.get(verdict))
        m = _first(rx, out or "")
        if not m:
            return None
        end = out.find("\n", m.start())
        return out[out.rfind("\n", 0, m.start()) + 1:len(out) if end < 0 else end].strip()

    def outcome(self, rc, out):
        """verdict of one run from [run.outcome]. Counts (passed, failed, skipped) are read from the last summary line
        (summary's group, or the whole match), or from the whole output without summary. A failed count is fail; a
        passed count is pass at exit 0, fail otherwise: pass needs a counted passed test. Then build, no_test and a
        skipped count (none: the test did not run). No count read at all is error; counts of 0 are none at exit 0."""
        if rc is None:
            return "env"
        if rc == "timeout":
            return "timeout"
        out = out or ""
        rx = self._rx
        if _first(rx.get("env"), out):
            return "env"
        if "summary" in rx:
            lines = list(_matches(rx["summary"], out))
            text = (lines[-1].group(rx["summary"].groups) if lines else None)
        else:
            text = out if any(_first(rx.get(k), out) for k in ("passed", "failed", "skipped")) else None
        if text is not None:
            if self._count("failed", text):
                return "fail"
            if self._count("passed", text):
                return "pass" if rc == 0 else "fail"
        if _first(rx.get("build"), out):
            return "build"
        if _first(rx.get("no_test"), out):
            return "none"
        if text is None:
            return "error"
        if self._count("skipped", text):
            return "none"
        return "none" if rc == 0 else "error"


def _matches(rx, text):
    """rx's matches in text that hold text: a zero-width match (a lookaround, `x?`) never counts, so a pattern the load
    probes let through still cannot read a run with no such output as build, env, none or a count."""
    return (m for m in rx.finditer(text) if m.end() > m.start()) if rx else iter(())


def _first(rx, text):
    return next(_matches(rx, text), None)


def _holds(when, crate):
    """a runner's `when` in the crate dir: the file is there; with tables, it is JSON whose tables hold every `has` key
    and no `lacks` key. A file that is missing or not JSON never holds."""
    path = os.path.join(crate, when["file"])
    if not os.path.isfile(path):
        return False
    if not when.get("tables"):
        return True
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return False
    keys = set()
    for t in when["tables"]:
        if isinstance(doc, dict) and isinstance(doc.get(t), dict):
            keys.update(doc[t])
    return all(k in keys for k in when.get("has", [])) and not any(k in keys for k in when.get("lacks", []))
