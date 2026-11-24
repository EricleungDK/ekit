"""Declared tests (#22): `[tests] style = "declared"`, a test is a [functions] shape with a marker before it (JUnit's
`@Test void adds() {`), grouped by `class NAME {...}` declarations. Through the java reference adapter
(tests/fixtures/adapters/java.toml) and adapter_file.parse on dicts; pure, no git and no toolchain."""
import copy
import os
import unittest

import _kit
from scripts.mech_review import adapter_file
from scripts.mech_review.adapter_file import AdapterFileError, parse

JAVA = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "java.toml")

SRC = '''package com.example;

// @Test void commented() {}
@Disabled("whole class")
class OffTest {
    @Test
    void off() {
        assertEquals(1, 1);
    }
}

public final class CalcTest {
    private static final String S = "@Test void inString() {}";

    @Test
    public void adds() {
        int x = Calc.add(1, 2);
        assertEquals(3, x);
        check(x);
    }

    @org.junit.jupiter.api.Test
    @Disabled("later")
    void skipped() throws Exception {
        assertNotEquals(4, Calc.add(2, 2));
    }

    @ParameterizedTest
    @ValueSource(ints = {1, 2})
    void param(int n) { assertTrue(n > 0); }

    private void check(int x) {
        assertTrue(x > 0);
    }

    void helperNotATest() {
        foo(1) void notMarked();
    }

    @Nested
    class Inner {
        @Test
        void deep() {
            assertThat(Calc.add(1, 1)).isEqualTo(2);
        }
    }
}
'''


def java():
    return adapter_file.load(JAVA)


class DeclaredTests(unittest.TestCase):
    def setUp(self):
        self.a = java()

    def test_marked_functions_are_tests_named_with_their_classes(self):
        self.assertIsNone(self.a.parse_error(SRC))
        self.assertEqual([(t.name, t.line, t.markers, t.body) for t in self.a.test_fns(SRC)], [
            ("OffTest.off", 7, ["ignore"], (8, 8)),
            ("CalcTest.adds", 16, [], (17, 19)),
            ("CalcTest.skipped", 24, ["ignore"], (25, 25)),
            ("CalcTest.param", 30, [], None),
            ("CalcTest.Inner.deep", 43, [], (44, 44)),
        ])

    def test_asserts_belong_to_their_test_or_the_helper_that_holds_them(self):
        got = [(x.line, x.fn, x.kind, x.left, x.right, x.owner) for x in self.a.assertions(SRC)]
        self.assertEqual(got, [
            (8, "OffTest.off", "eq", "1", "1", "OffTest.off"),
            (18, "CalcTest.adds", "eq", "3", "x", "CalcTest.adds"),
            (25, "CalcTest.skipped", "ne", "4", "Calc.add(2,2)", "CalcTest.skipped"),
            (30, "CalcTest.param", "other", None, None, "CalcTest.param"),
            (33, None, "other", None, None, "check"),
            (44, "CalcTest.Inner.deep", "eq", "Calc.add(1,1)", "2", "CalcTest.Inner.deep"),
        ])
        self.assertIn("check", self.a.calls(SRC)["CalcTest.adds"])

    def test_a_skipped_declared_test_keeps_its_body(self):
        bodies = self.a.test_bodies(SRC)
        self.assertEqual(sorted(bodies), ["CalcTest.Inner.deep", "CalcTest.adds", "CalcTest.param", "CalcTest.skipped",
                                          "OffTest.off"])
        self.assertEqual(bodies["CalcTest.skipped"],
                         (24, "voidskipped()throwsException{assertNotEquals(4,Calc.add(2,2));}"))

    def test_a_marker_needs_its_prefix_and_ends_at_other_code(self):
        src = "class T {\n    int x = 1;\n    Test void a() {\n    }\n    x; @Test void b() {\n    }\n}\n"
        self.assertEqual([t.name for t in self.a.test_fns(src)], ["T.b"])

    def test_a_group_word_with_no_name_or_block_is_no_group(self):
        src = "@Test void top() {\n}\nclass\nclass 9x {\n}\n"
        self.assertEqual([t.name for t in self.a.test_fns(src)], ["top"])

    def test_a_dotted_marker_with_no_word_before_its_dot_is_no_marker(self):
        self.assertEqual(self.a.test_fns("class T {\n    @.Test void a() {\n    }\n}\n"), [])
        self.assertEqual(self.a.test_fns("class T {\n    ) void a() {\n    }\n}\n"), [])

    def test_only_markers_and_the_default_separator(self):
        cfg = copy.deepcopy(adapter_file_dict())
        cfg["tests"] = {"style": "declared", "prefix": "@", "cases": ["Test"], "groups": ["class"], "only": ["Focus"]}
        a = parse(cfg)
        src = "class A {\n    @Focus @Test void x() {\n        assertEquals(1, 1);\n    }\n}\n"
        self.assertEqual([(t.name, t.markers) for t in a.test_fns(src)], [("A > x", ["only"])])


def adapter_file_dict():
    return {"format": 1, "name": "j", "extensions": [".j"],
            "lexer": {"block_style": "braces", "brackets": ["()", "{}"], "line_comments": ["//"]},
            "tests": {"style": "declared", "prefix": "@", "cases": ["Test"]},
            "functions": {"shapes": ["void NAME (...) {...}"]},
            "asserts": {"call": [{"names": ["assertEquals"], "kind": "eq", "operands": [0, 1]}]}}


class DeclaredValidation(unittest.TestCase):
    def err(self, edit):
        d = adapter_file_dict()
        edit(d)
        with self.assertRaises(AdapterFileError) as cm:
            parse(d)
        return str(cm.exception)

    def test_a_valid_declared_file_loads(self):
        self.assertTrue(parse(adapter_file_dict())._declared)

    def test_declared_needs_functions_and_a_prefix(self):
        self.assertEqual(self.err(lambda d: d.pop("functions")),
                         "functions: missing: tests.style declared reads each test as a [functions] shape with a marker")
        self.assertEqual(self.err(lambda d: d["tests"].pop("prefix")),
                         'tests.prefix: missing: style declared needs what starts a marker, e.g. "@"')

    def test_the_prefix_is_punctuation(self):
        for bad in ("a", " ", "(", "}", ".", "@ "):
            with self.subTest(bad):
                self.assertEqual(self.err(lambda d: d["tests"].__setitem__("prefix", bad)),
                                 f"tests.prefix: `{bad}`: want punctuation that is no word character, bracket or "
                                 "member character")
        self.assertEqual(self.err(lambda d: d["tests"].__setitem__("prefix", "")), "tests.prefix: want a non-empty string")

    def test_calls_only_keys_are_refused(self):
        for k, v in (("skip_modifiers", ["skip"]), ("only_modifiers", ["only"]), ("table_modifiers", ["each"]),
                     ("min_args", 2), ("not_after", ["function"])):
            with self.subTest(k):
                self.assertEqual(self.err(lambda d: d["tests"].__setitem__(k, v)),
                                 f"tests.{k}: style calls only: a declared test is no call")

    def test_words_and_texts(self):
        self.assertEqual(self.err(lambda d: d["tests"].__setitem__("cases", [])), "tests.cases: want at least one entry")
        for k in ("groups", "skip", "only"):
            with self.subTest(k):
                self.assertEqual(self.err(lambda d: d["tests"].__setitem__(k, ["a b"])),
                                 f"tests.{k}[0]: `a b` is not a word (letters, digits, _ and lexer.ident_chars)")
        self.assertEqual(self.err(lambda d: d["tests"].__setitem__("separator", "")),
                         "tests.separator: want a non-empty string")
        self.assertIn("tests.skipped_text: unknown placeholder `{x}`",
                      self.err(lambda d: d["tests"].__setitem__("skipped_text", "{x}")))
        self.assertEqual(self.err(lambda d: d["tests"].__setitem__("bogus", 1)), "tests.bogus: unknown key")

    def test_calls_style_has_no_prefix(self):
        def calls(d):
            d["tests"] = {"style": "calls", "cases": ["test"], "prefix": "@"}
        self.assertEqual(self.err(calls),
                         "tests.prefix: style calls has no prefix (declared only: what starts a test's marker)")


if __name__ == "__main__":
    unittest.main()
