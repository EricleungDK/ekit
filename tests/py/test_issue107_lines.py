"""#107 B4: splitting source into bodies and counting line numbers use the same line breaks: LF (a CR before it is part
of that break). U+2028, U+2029, U+0085, VT and FF, which str.splitlines() also breaks at, are not line breaks: a file
holding them gives bodies whose lines match their numbers.

Seams: `r2` (a renamed test's body is compared by the lines of its span: a confirm entry), `red` (a parser-backed
file's test bodies say which tests changed: the runner's calls), through cli.main in this process; R3's mutmut line
helpers beside them."""
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants, scan
from test_adapter_cli import MINI, Repo, r2
from test_adapter_run import MINI_FRESH, MINI_RUN, MINI_STUB, Fixture
from test_parser_cli import parser_home, parser_toml
from test_r2_rename import (MINI_LEGIT_BASE, MINI_LEGIT_HEAD, RENAMED, RUST, TS, TS_ADAPTER, TS_SPLIT_LEGIT_BASE,
                            TS_SPLIT_LEGIT_HEAD)
from test_r2_rename import BASE as PY_BASE

ODD = {"U+2028": " ", "U+2029": " ", "U+0085": "\x85", "VT": "\x0b", "FF": "\x0c"}
MANY = 8  # each odd character this many times on one line: a splitter that breaks at it reads 8 lines off


def preamble(comment, ch):
    return f"{comment} notes{ch * MANY}end\n"


class Renames(unittest.TestCase):
    """a rename whose assertions changed is one confirm entry when its body lines are read at their numbers; read 8
    lines off, the body is another test's text, and the rename reads as a removed test (a fail)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = Repo(os.path.join(self.tmp, "r"))
        self.base = self.repo.commit({"pyproject.toml": "[project]\nname = 'x'\n", "mini.json": "{}\n"}, "base")
        self.n = 0

    def entries(self, path, before, after, stack, adapter=None):
        self.n += 1
        path = path.format(n=self.n)  # a file of its own per case: the cases share the repo
        self.repo.git("checkout", "-q", "--detach", self.base)
        base = self.repo.commit({path: before}, "case base")
        head = self.repo.commit({path: after}, "case head")
        res = r2(self.repo, base, head, adapter=adapter, stack=stack)
        self.assertIn(res.returncode, (0, 1), res.stderr)
        return [(e["severity"], e["problem"]) for e in json.loads(res.stdout)["entries"]]

    def each(self, path, before, after, comment, stack, want, adapter=None):
        for label, ch in ODD.items():
            with self.subTest(char=label, stack=stack, adapter=adapter):
                head = preamble(comment, ch)
                self.assertEqual(self.entries(path, head + before, head + after, stack, adapter), want)



class RenameBodies(Renames):
    def test_python(self):
        self.each("tests/test_c{n}.py", PY_BASE, RENAMED, "#", "python", [
            ("confirm", "test `T::test_the_budget_gone_keeps_every_mutant_missed` renamed to "
                        "`T::test_the_budget_gone_leaves_every_mutant_untested`, assertions changed")])

    def test_ts_built_in_and_its_file(self):
        want = [("confirm", "test `refund is never negative, whatever the input amount is` renamed to "
                            "`refund is capped at the order, whatever the input amount is`, assertions changed")]
        self.each("tests/r{n}.test.ts", TS_SPLIT_LEGIT_BASE, TS_SPLIT_LEGIT_HEAD, "//", "ts", want)
        self.each("tests/r{n}.test.ts", TS_SPLIT_LEGIT_BASE, TS_SPLIT_LEGIT_HEAD, "//", "ts", want, TS_ADAPTER)

    def test_ts_nested(self):
        head = TS.replace("keeps missed", "leaves untested").replace("'fail'", "'partial'")
        self.each("tests/b{n}.test.ts", TS, head, "//", "ts", [
            ("confirm", "test `budget > keeps missed` renamed to `budget > leaves untested`, assertions changed")])

    def test_rust(self):
        self.each("tests/b{n}.rs", RUST, RUST.replace("keeps_missed", "leaves_untested").replace('"fail"', '"partial"'),
                  "//", "rust", [("confirm", "test `keeps_missed` renamed to `leaves_untested`, assertions changed")])

    def test_an_adapter_file(self):
        self.each("tests/c{n}.mini", MINI_LEGIT_BASE, MINI_LEGIT_HEAD, "#", "mini", [
            ("confirm", "test `Calc / refund never negative` renamed to `Calc / refund capped`, assertions changed")],
            MINI)

    def test_crlf_files_read_the_same(self):
        crlf = lambda t: t.replace("\n", "\r\n")
        self.assertEqual(self.entries("tests/r{n}.test.ts", crlf(TS_SPLIT_LEGIT_BASE), crlf(TS_SPLIT_LEGIT_HEAD), "ts"),
                         [("confirm", "test `refund is never negative, whatever the input amount is` renamed to "
                                      "`refund is capped at the order, whatever the input amount is`, assertions "
                                      "changed")])


class PythonBreaks(Renames):
    """#107 review F3: the python built-in's line numbers are ast's, which break at LF, CRLF and a lone CR (and at
    none of the odd characters, FF included): its bodies are cut at those same breaks."""

    WANT = [("confirm", "test `T::test_the_budget_gone_keeps_every_mutant_missed` renamed to "
                        "`T::test_the_budget_gone_leaves_every_mutant_untested`, assertions changed")]

    def python(self, conv):
        return self.entries("tests/test_c{n}.py", conv(PY_BASE), conv(RENAMED), "python")

    def test_lone_cr_crlf_and_mixed_line_ends(self):
        def mixed(t):  # LF, CRLF and CR in turn, line by line
            out = t.split("\n")
            return "".join(ln + ("\n", "\r\n", "\r")[i % 3] for i, ln in enumerate(out[:-1])) + out[-1]
        for label, conv in (("CR", lambda t: t.replace("\n", "\r")), ("CRLF", lambda t: t.replace("\n", "\r\n")),
                            ("mixed", mixed)):
            with self.subTest(ends=label):
                self.assertEqual(self.python(conv), self.WANT)

    def test_lone_cr_after_odd_characters(self):
        for label, ch in ODD.items():
            with self.subTest(char=label):
                head = preamble("#", ch).replace("\n", "\r")
                self.assertEqual(self.python(lambda t: head + t.replace("\n", "\r")), self.WANT)

    def test_a_form_feed_at_the_start_of_a_line_breaks_nothing(self):
        self.assertEqual(self.python(lambda t: t.replace("\n    def test_adds", "\n\x0c    def test_adds")
                                     .replace("\nclass T", "\n\x0c\x0c\nclass T")), self.WANT)


class LineBreakSets(unittest.TestCase):
    def test_the_python_set_is_asts(self):
        import ast
        src = "a = 1\rb = 2\r\nc = 3\n\x0cd = 4  # e\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029\nf = 5\n"
        lines = scan.source_lines(src, scan.PYTHON)
        for node in ast.parse(src).body:  # each statement is on the line ast numbers it
            self.assertEqual(lines[node.lineno - 1].strip().lstrip("\x0c")[:1], ast.unparse(node)[:1])
        self.assertEqual(len(lines), 6)

    def test_lf_breaks_at_lf_only(self):
        self.assertEqual(scan.source_lines("a\rb\r\nc\x85d\ne"), ["a\rb\r", "c\x85d", "e"])


FRESH_CHANGED = MINI_FRESH.replace('test("fresh", {\n    assertEquals(3, add(1, 2))',
                                   'test("fresh", {\n    assertEquals(4, add(2, 2))')


class ParserBodies(Fixture):
    """a parser-backed file: the parser gives each test's lines; R1 and R4 run the tests whose body changed."""

    def setUp(self):
        super().setUp()
        with open(os.environ["MECH_TEST_STUB"], "w") as f:
            f.write(MINI_STUB)
        parser_home(self)
        self.adapter = os.path.join(self.tmp, "parser.toml")
        with open(self.adapter, "w") as f:
            f.write(parser_toml() + MINI_RUN)

    def ran(self, head_text, base_text):
        base = self.commit({"src/calc.mini": "fn add(a, b) { a + b }\n", "tests/calc.mini": base_text,
                            "tests/outcomes": "fresh fail pass\n"})
        head = self.commit({"tests/calc.mini": head_text, "src/calc.mini": "fn add(a, b) { a + b } # fixed\n"})
        r = self.red(base, head, adapter=self.adapter, stack="mini")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return sorted({c.split(" | ", 1)[1] for c in self.calls()})

    def test_only_the_test_whose_body_changed_runs(self):
        for label, ch in ODD.items():
            with self.subTest(char=label):
                head = preamble("#", ch)
                self.assertEqual(self.ran(head + FRESH_CHANGED, head + MINI_FRESH),
                                 ["--file tests/calc.mini --only Calc / fresh"])

    def test_odd_characters_added_to_a_comment_change_no_test(self):
        for label, ch in ODD.items():
            with self.subTest(char=label):
                self.assertEqual(self.ran(preamble("#", ch) + MINI_FRESH, preamble("#", "") + MINI_FRESH), [])


PY_SRC = """import os
# notes{odd}end


def add(a, b=1):
    total = a + b
    return total


class Calc:
    def scale(self, a):
        factor = 2
        return a * factor
"""


class MutmutLines(unittest.TestCase):
    """R3 (python) places a mutant by the function's lines in the file: those lines are the file's LF lines."""

    def test_spans_and_lines_are_the_files(self):
        for label, ch in ODD.items():
            with self.subTest(char=label):
                src = PY_SRC.format(odd=ch * MANY)
                self.assertEqual(mutants.scope_span(src, "calc.x_add__mutmut_1"), (5, 7))
                self.assertEqual(mutants.scope_span(src, "calc.x\u01c1Calc\u01c1scale__mutmut_1"), (11, 13))
                self.assertEqual(mutants.locate(src, "calc.x_add__mutmut_1", "total = a + b"), 6)
                self.assertEqual(mutants.line_at(src, "calc.x_add__mutmut_1", 1, "total = a + b"), 6)

    def test_a_python_file_with_lone_cr_or_crlf_ends_is_read_at_asts_lines(self):
        for label, end in (("CR", "\r"), ("CRLF", "\r\n")):
            with self.subTest(ends=label):
                src = PY_SRC.format(odd="\x85" * MANY).replace("\n", end)
                self.assertEqual(mutants.scope_span(src, "calc.x_add__mutmut_1"), (5, 7))
                self.assertEqual(mutants.scope_span(src, "calc.x\u01c1Calc\u01c1scale__mutmut_1"), (11, 13))
                self.assertEqual(mutants.locate(src, "calc.x_add__mutmut_1", "total = a + b"), 6)
                self.assertEqual(mutants.line_at(src, "calc.x_add__mutmut_1", 1, "total = a + b"), 6)
                self.assertEqual(mutants.mutant_blocks("def x_a__mutmut_orig(a):\r    return a\r")["x_a__mutmut_orig"],
                                 ["def x_a__mutmut_orig(a):", "    return a"])

    def test_mutated_copies_split_at_no_odd_character(self):
        text = "def x_add__mutmut_orig(a):\n    s = 'a b'\n    return s\n"
        self.assertEqual(mutants.mutant_blocks(text)["x_add__mutmut_orig"],
                         ["def x_add__mutmut_orig(a):", "    s = 'a b'", "    return s"])


if __name__ == "__main__":
    unittest.main()
