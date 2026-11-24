"""The report-format readers of R3 through an adapter file (#19): mutation-testing-elements JSON (the Stryker family,
mull), PIT's mutations.xml and a line pattern with named groups. Each reads a report's bytes into the mutants R3 counts
(missed, caught, timeout, unviable, ignored, pending) or refuses it with ReportError naming why: a malformed report is
R3 n/a (env), never a pass and never a crash. Fixtures: tests/fixtures/mutation-reports."""
import json
import os
import time
import unittest
from unittest import mock

import _kit
from scripts.mech_review import mutants as M
from scripts.mech_review.adapter_file import parse

FX = os.path.join(_kit.ROOT, "tests", "fixtures", "mutation-reports")
CRATE = "/work/crate"


def raw(name):
    with open(os.path.join(FX, name), "rb") as f:
        return f.read()


def lines_tool(pattern=r"^(?P<file>\S+):(?P<line>\d+) (?P<status>[A-Z]+) (?P<desc>.+)$", **status):
    d = {"format": 1, "name": "mini", "extensions": [".mini"],
         "lexer": {"block_style": "braces", "brackets": ["()", "{}"]},
         "tests": {"style": "calls", "cases": ["test"]}, "asserts": {"call": [{"names": ["ok"], "kind": "other"}]},
         "mutation": {"tool": {"name": "mut", "command": "mut", "report": "out.txt", "format": "lines", "os": ["linux"],
                               "pattern": pattern,
                               "status": status or {"missed": ["SURVIVED"], "caught": ["KILLED"], "timeout": ["SLOW"],
                                                    "unviable": ["BROKEN"]}}}}
    return parse(d).mutation_tool


def short(rows):
    return [(r.file, r.line, r.kind, r.desc, r.fix) for r in rows]


class Elements(unittest.TestCase):
    def test_the_fixture_maps_each_status(self):
        rows, silent = M.read_elements(raw("elements.json"), CRATE)
        self.assertEqual(silent, 0)
        self.assertEqual(short(rows), [
            ("src/calc.mini", 2, "missed", "ArithmeticOperator `a + b` -> `a - b`", "survived"),
            ("src/calc.mini", 6, "missed", "EqualityOperator `n > 0` -> `n >= 0`", "nocoverage"),
            ("src/calc.mini", 6, "caught", "BooleanLiteral `n > 0` -> `true`", None),
            ("src/calc.mini", 1, "timeout", "BlockStatement `{` -> `{}`", None),
            ("src/calc.mini", 1, "unviable", 'StringLiteral `fn` -> `""`', None),
            ("src/calc.mini", 2, "ignored", "ArithmeticOperator `a + b` -> `a * b`", None),
            ("src/calc.mini", 6, "pending", "ConditionalExpression `n > 0` -> `false`", None)])

    def test_a_survived_mutant_whose_covering_tests_never_completed_is_counted_silent(self):
        doc = json.loads(raw("elements.json"))
        doc["files"]["src/calc.mini"]["mutants"][0]["testsCompleted"] = 0
        _, silent = M.read_elements(json.dumps(doc).encode(), CRATE)
        self.assertEqual(silent, 1)

    def test_paths_absolute_inside_the_crate_are_crate_relative_and_outside_it_none(self):
        doc = {"files": {"/work/crate/src/a.mini": {"source": "x", "mutants": [{"status": "Survived"}]},
                         "/elsewhere/b.mini": {"source": "x", "mutants": [{"status": "Survived"}]},
                         "../c.mini": {"source": "x", "mutants": [{"status": "Survived"}]},
                         "src\\d.mini": {"source": "x", "mutants": [{"status": "Survived"}]}}}
        rows, _ = M.read_elements(json.dumps(doc).encode(), CRATE)
        self.assertEqual([r.file for r in rows], ["src/a.mini", None, None, "src/d.mini"])

    def test_a_mutant_without_a_usable_line_is_unlocated(self):
        for loc in (None, {}, {"start": {"line": True}}, {"start": {"line": 0}}, {"start": {"line": "2"}}):
            with self.subTest(loc):
                m = {"status": "Survived", "mutatorName": "X"}
                if loc is not None:
                    m["location"] = loc
                rows, _ = M.read_elements(json.dumps({"files": {"a.mini": {"mutants": [m]}}}).encode(), CRATE)
                self.assertEqual(rows[0].line, None)

    def test_nesting_deeper_than_the_readers_limit_is_refused_on_every_python(self):  # CI: the runner's python
        # parsed 100000 nested arrays where this machine's raised RecursionError: the limit is the reader's own
        for text in (b"[" * 65 + b"]" * 65, b'{"files": {"a": {"mutants": [' + b"[" * 70 + b"]" * 70 + b"]}}}",
                     b'{"files": {}, "x": "' + b"[" * 100 + b'"}'):
            with self.subTest(text[:20]):
                if b'"x"' in text:  # brackets inside a string are text, not nesting
                    self.assertEqual(M.read_elements(text, CRATE), ([], 0))
                    continue
                with self.assertRaises(M.ReportError) as cm:
                    M.read_elements(text, CRATE)
                self.assertEqual(str(cm.exception), f"not JSON: nested too deep (more than {M.MAX_JSON_DEPTH} levels)")
        self.assertEqual(M.read_elements(b'{"files": {}, "a": ' + b"[" * 60 + b"]" * 60 + b"}", CRATE), ([], 0))

    def test_no_files_is_no_mutant(self):
        self.assertEqual(M.read_elements(b'{"schemaVersion": "2", "files": {}}', CRATE), ([], 0))

    def test_malformed_reports_are_refused_with_the_reason(self):
        cases = {b"not json": "not JSON", b"[1, 2]": "not a JSON object", b'{"x": 1}': "no files object",
                 b'{"files": []}': "no files object", b'{"files": {"a": 1}}': "`a`: no mutants list",
                 b'{"files": {"a": {"mutants": [1]}}}': "a mutant in `a` is not an object",
                 b'{"files": {"a": {"mutants": [{"status": "Zombie"}]}}}': "status `Zombie`",
                 b'{"files": {"a": {"mutants": [{"status": 1}]}}}': "status `1`",
                 b"\xff\xfe": "not UTF-8", b"[" * 100000 + b"]" * 100000: "nested too deep"}
        for text, why in cases.items():
            with self.subTest(text[:30]):
                with self.assertRaises(M.ReportError) as cm:
                    M.read_elements(text, CRATE)
                self.assertIn(why, str(cm.exception))


class Pit(unittest.TestCase):
    def test_the_fixture_maps_each_status_by_package_path(self):
        rows = M.read_pit(raw("mutations.xml"))
        self.assertEqual(short(rows), [
            ("com/example/Calc.java", 5, "missed", "MathMutator in add: Replaced integer addition with subtraction",
             "survived"),
            ("com/example/Calc.java", 9, "missed", "ConditionalsBoundaryMutator in isPositive: changed conditional "
                                                   "boundary", "nocoverage"),
            ("com/example/Calc.java", 5, "caught", "PrimitiveReturnsMutator in add: replaced int return with 0 for "
                                                   "com/example/Calc::add", None),
            ("com/example/Calc.java", 13, "timeout", "IncrementsMutator in loop: Changed increment from 1 to -1", None),
            ("com/example/Calc.java", 13, "unviable", "VoidMethodCallMutator in loop: removed call", None),
            ("com/example/Calc.java", 5, "pending", "MathMutator in add: Replaced integer addition with multiplication",
             None)])
        self.assertTrue(all(r.suffix for r in rows))

    def test_a_class_in_the_default_package_is_its_file_name(self):
        x = (b"<mutations><mutation status='SURVIVED'><sourceFile>A.java</sourceFile><mutatedClass>A</mutatedClass>"
             b"<lineNumber>3</lineNumber></mutation></mutations>")
        self.assertEqual([(r.file, r.line) for r in M.read_pit(x)], [("A.java", 3)])

    def test_a_dtd_or_an_entity_is_refused_before_parsing(self):
        for x in (b'<?xml version="1.0"?><!DOCTYPE m [<!ENTITY a "aaaa">]><mutations>&a;</mutations>',
                  b'<!doctype mutations SYSTEM "file:///etc/passwd"><mutations/>',
                  b'<mutations><!ENTITY x "y"></mutations>'):
            with self.subTest(x[:30]):
                with self.assertRaises(M.ReportError) as cm:
                    M.read_pit(x)
                self.assertIn("a DTD or an entity declaration: refused", str(cm.exception))

    def test_a_report_in_a_wide_encoding_is_refused_so_no_declaration_hides_from_the_check(self):
        x = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE m [<!ENTITY a "b">]><mutations>&a;</mutations>'
        for raw in (x.encode("utf-16"), x.encode("utf-16-be"), x.encode("utf-32")):
            with self.assertRaises(M.ReportError) as cm:
                M.read_pit(raw)
            self.assertIn("not UTF-8", str(cm.exception))

    def test_a_declared_encoding_other_than_utf8_is_refused_never_a_crash(self):  # review F2
        for enc in (b"shift_jis", b"utf-7", b"euc-jp", b"ISO-8859-1", b"UTF-16"):
            with self.subTest(enc):
                x = b'<?xml version="1.0" encoding="' + enc + b'"?><mutations/>'
                with self.assertRaises(M.ReportError) as cm:
                    M.read_pit(x)
                self.assertEqual(str(cm.exception), f"declares encoding `{enc.decode()}`: want UTF-8")
        for ok in (b'<?xml version="1.0" encoding="UTF-8"?><mutations/>', b"<?xml version='1.0' encoding='utf8'?><mutations/>",
                   b'<?xml version="1.0"?><mutations/>'):
            self.assertEqual(M.read_pit(ok), [])

    def test_a_value_error_from_the_parser_is_a_report_error(self):
        with mock.patch("xml.etree.ElementTree.fromstring", side_effect=ValueError("multi-byte encodings")):
            with self.assertRaises(M.ReportError) as cm:
                M.read_pit(b"<mutations/>")
        self.assertIn("not XML: multi-byte encodings", str(cm.exception))

    def test_a_line_number_that_is_not_ascii_digits_is_unlocated(self):
        for ln in ("\u00b2", "\u0663", "\uff13"):  # superscript two, arabic-indic three, fullwidth three
            x = ("<mutations><mutation status='SURVIVED'><sourceFile>A.java</sourceFile><mutatedClass>A</mutatedClass>"
                 f"<lineNumber>{ln}</lineNumber></mutation></mutations>").encode()
            self.assertEqual(M.read_pit(x)[0].line, None, ln)

    def test_malformed_reports_are_refused_with_the_reason(self):
        ok = b"<sourceFile>A.java</sourceFile><mutatedClass>p.A</mutatedClass><lineNumber>3</lineNumber>"
        cases = {b"<mutations>": "not XML", b"<report/>": "root is <report>, not <mutations>",
                 b"<mutations><x/></mutations>": "<x> in <mutations>",
                 b"<mutations><mutation status='WEIRD'>" + ok + b"</mutation></mutations>": "status `WEIRD`",
                 b"<mutations><mutation>" + ok + b"</mutation></mutations>": "status `None`",
                 b"<mutations><mutation status='KILLED'><lineNumber>3</lineNumber></mutation></mutations>":
                     "no sourceFile",
                 b"<mutations><mutation status='KILLED'><sourceFile>../A.java</sourceFile><mutatedClass>A"
                 b"</mutatedClass></mutation></mutations>": "sourceFile `../A.java`",
                 b"<mutations><mutation status='KILLED'><sourceFile>A.java</sourceFile></mutation></mutations>":
                     "no mutatedClass"}
        for text, why in cases.items():
            with self.subTest(text[:40]):
                with self.assertRaises(M.ReportError) as cm:
                    M.read_pit(text)
                self.assertIn(why, str(cm.exception))

    def test_a_line_that_is_no_whole_number_is_unlocated(self):
        for ln in (b"", b"x", b"0", b"-2"):
            x = (b"<mutations><mutation status='SURVIVED'><sourceFile>A.java</sourceFile><mutatedClass>A</mutatedClass>"
                 b"<lineNumber>" + ln + b"</lineNumber></mutation></mutations>")
            self.assertEqual(M.read_pit(x)[0].line, None, ln)


class Lines(unittest.TestCase):
    def test_the_fixture_maps_each_declared_status(self):
        rows = M.read_lines(raw("lines.txt"), lines_tool(), CRATE)
        self.assertEqual(short(rows), [
            ("src/calc.mini", 2, "missed", "replace + with -", "survived"),
            ("src/calc.mini", 6, "missed", "replace > with >=", "survived"),
            ("src/calc.mini", 6, "caught", "replace > with <", None),
            ("src/calc.mini", 1, "timeout", "empty body", None),
            ("src/calc.mini", 1, "unviable", "drop fn", None)])

    def test_without_a_desc_group_the_matched_text_is_the_description(self):
        rows = M.read_lines(b"a.mini:3 SURVIVED\n", lines_tool(r"^(?P<file>\S+):(?P<line>\d+) (?P<status>\w+)$"), CRATE)
        self.assertEqual(short(rows), [("a.mini", 3, "missed", "a.mini:3 SURVIVED", "survived")])

    def test_a_zero_width_match_never_counts(self):
        tool = lines_tool(r"(?=(?P<file>a\.mini):(?P<line>\d+) (?P<status>SURVIVED))")
        self.assertEqual(M.read_lines(b"a.mini:3 SURVIVED\n", tool, CRATE), [])

    def test_a_status_in_no_list_is_refused(self):
        with self.assertRaises(M.ReportError) as cm:
            M.read_lines(b"a.mini:3 ODD x\n", lines_tool(), CRATE)
        self.assertEqual(str(cm.exception), "line 1: status `ODD` is in no mutation.tool.status list")

    def test_a_line_that_is_no_whole_number_or_a_group_that_took_no_part_is_refused(self):
        tool = lines_tool(r"^(?P<file>\S+):(?P<line>\w+) (?P<status>[A-Z]+)(?: (?P<desc>.+))?$")
        with self.assertRaises(M.ReportError) as cm:
            M.read_lines(b"ok\na.mini:x SURVIVED d\n", tool, CRATE)
        self.assertEqual(str(cm.exception), "line 2: line `x` is not a whole number >= 1")
        tool = lines_tool(r"^(?:-|(?P<file>[a-z.]+)):(?P<line>\d+) (?P<status>[A-Z]+)$")
        with self.assertRaises(M.ReportError) as cm:
            M.read_lines(b"-:3 SURVIVED\n", tool, CRATE)
        self.assertEqual(str(cm.exception), "line 1: the pattern matched without its file group")

    def test_a_line_that_is_not_ascii_digits_is_refused_never_a_crash(self):  # review F3
        tool = lines_tool(r"^(?P<file>\S+):(?P<line>\S+) (?P<status>[A-Z]+) (?P<desc>.+)$")
        for ln in ("\u00b2", "\u0663"):
            with self.assertRaises(M.ReportError) as cm:
                M.read_lines(f"a.mini:{ln} SURVIVED x\n".encode(), tool, CRATE)
            self.assertEqual(str(cm.exception), f"line 1: line `{ln}` is not a whole number >= 1")

    def test_a_large_report_reads_in_linear_time_with_its_line_numbers(self):
        n = 80000
        raw = "".join(f"src/a.mini:{i % 500 + 1} KILLED mutant {i}\n" for i in range(n)).encode()
        t0 = time.monotonic()
        rows = M.read_lines(raw, lines_tool(), CRATE)
        self.assertEqual(len(rows), n)
        self.assertLess(time.monotonic() - t0, 5.0)  # quadratic line counting took 32 s here
        bad = raw + b"src/a.mini:1 ODD x\n"
        with self.assertRaises(M.ReportError) as cm:
            M.read_lines(bad, lines_tool(), CRATE)
        self.assertEqual(str(cm.exception), f"line {n + 1}: status `ODD` is in no mutation.tool.status list")

    def test_not_utf8_is_refused(self):
        with self.assertRaises(M.ReportError):
            M.read_lines(b"\xff a.mini:3 SURVIVED x", lines_tool(), CRATE)


class Dispatch(unittest.TestCase):
    def test_read_report_picks_the_format_and_refuses_a_report_too_big_to_read(self):
        tool = lines_tool()
        self.assertEqual(len(M.read_report(tool, raw("lines.txt"), CRATE)[0]), 5)
        with mock.patch.object(M, "MAX_REPORT_BYTES", 10):
            with self.assertRaises(M.ReportError) as cm:
                M.read_report(tool, raw("lines.txt"), CRATE)
        self.assertIn("more than 10 bytes", str(cm.exception))
        self.assertEqual(len(M.read_report(dict(tool, format="pit-xml"), raw("mutations.xml"), CRATE)[0]), 6)
        self.assertEqual(len(M.read_report(dict(tool, format="mutation-testing-elements"), raw("elements.json"),
                                           CRATE)[0]), 7)


if __name__ == "__main__":
    unittest.main()
