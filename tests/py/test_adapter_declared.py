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
        self.assertEqual([t.name for t in self.a.test_fns("@Test void top() {\n}\nclass")], ["top"])
        self.assertEqual([t.name for t in self.a.test_fns("@Test void top() {\n}\nclass A\n")], ["top"])
        src = "class 9x {\n    @Test void a() {\n    }\n}\nclass B {\n    @Test void b() {\n    }\n}\n"
        self.assertEqual([t.name for t in self.a.test_fns(src)], ["a", "B.b"])

    def test_groups_nest_in_source_order_and_hold_a_test_that_ends_at_their_brace(self):
        src = "class Z {\n    class A {\n        @Test void t() {\n        }\n    }\n}\nclass C {@Test void c() {\n}}\n"
        self.assertEqual([t.name for t in self.a.test_fns(src)], ["Z.A.t", "C.c"])

    def test_markers_side_by_side_or_with_a_space_before_their_group(self):
        for src in ("class T {\n    @Disabled@Test void a() {\n    }\n}\n",
                    'class T {\n    @Disabled ("x") @Test void a() {\n    }\n}\n'):
            with self.subTest(src):
                self.assertEqual([(t.name, t.markers) for t in self.a.test_fns(src)], [("T.a", ["ignore"])])

    def test_a_file_with_no_group_words(self):
        a = parse(adapter_file_dict())
        self.assertEqual([t.name for t in a.test_fns("class A {\n    @Test void a() {\n    }\n}\n")], ["a"])

    def test_a_dotted_marker_with_no_word_before_its_dot_is_no_marker(self):
        self.assertEqual(self.a.test_fns("class T {\n    @.Test void a() {\n    }\n}\n"), [])
        self.assertEqual(self.a.test_fns("class T {\n    ) void a() {\n    }\n}\n"), [])
        self.assertEqual(self.a.test_fns("class T {\n    @ .Test void a() {\n    }\n}\n"), [])

    def test_a_word_at_the_start_of_the_text_ends_the_markers(self):
        """the walk back stops at the text's start: a modifier there is read whole, once."""
        self.assertEqual([t.name for t in self.a.test_fns("public @Test void a() {\n}\n")], ["a"])
        self.assertEqual([t.name for t in self.a.test_fns("Test void a() {\n}\n")], [])

    def test_a_marker_group_with_a_group_inside_it(self):
        src = "class T {\n    @Test @ValueSource(ints = f(1)) void a() {\n    }\n}\n"
        self.assertEqual([t.name for t in self.a.test_fns(src)], ["T.a"])

    def test_a_block_that_never_closes_has_no_body(self):
        """close_of gives the text's last char for a block that never closes: no `}` there, no body."""
        src = "@Test void a() {\n    f(\n    1,\n    2,\n    3)"
        self.assertEqual([(t.name, t.body) for t in self.a.test_fns(src)], [("a", None)])

    def test_only_markers_and_the_default_separator(self):
        cfg = copy.deepcopy(adapter_file_dict())
        cfg["tests"] = {"style": "declared", "prefix": "@", "cases": ["Test"], "groups": ["class"], "only": ["Focus"]}
        a = parse(cfg)
        src = "class A {\n    @Focus @Test void x() {\n        assertEquals(1, 1);\n    }\n}\n"
        self.assertEqual([(t.name, t.markers) for t in a.test_fns(src)], [("A > x", ["only"])])


class RoundOne(unittest.TestCase):
    """review round 1 of #22: what the reference adapter missed."""

    def setUp(self):
        self.a = java()

    def test_a_generic_test_method_is_found_past_its_type_parameters(self):  # S9
        src = ("class T {\n    @Test\n    public <T extends Comparable<T>> void adds() {\n    }\n\n"
               "    int x = a > b;\n    @Test void c() {\n    }\n}\n")
        self.assertEqual([t.name for t in self.a.test_fns(src)], ["T.adds", "T.c"])
        self.assertEqual(self.a.test_fns("class T {\n    @Test x> void a() {\n    }\n}\n"), [])
        self.assertEqual([t.name for t in self.a.test_fns("class T {\n    @Test <TT> void a() {\n    }\n}\n")], ["T.a"])

    def test_junits_condition_annotations_skip(self):  # B4
        for ann in ("DisabledOnOs(OS.LINUX)", "EnabledOnOs(OS.WINDOWS)", "EnabledIfEnvironmentVariable(named = \"CI\")",
                    "DisabledForJreRange(min = JRE.JAVA_8)"):
            with self.subTest(ann):
                src = f"class T {{\n    @Test\n    @{ann}\n    void a() {{\n    }}\n}}\n"
                self.assertEqual([(t.name, t.markers) for t in self.a.test_fns(src)], [("T.a", ["ignore"])])

    def test_skip_annotations_are_mutation_skips_in_code_only(self):  # B3
        src = ('class A {\n    @DoNotMutate\n    int x() { return 1; }\n    @lombok.Generated("y") void g() {}\n'
               '    // @Generated in a comment\n    String s = "@CoverageIgnore";\n    @Generatedx void h() {}\n'
               '    @ CoverageIgnore void i() {}\n}\n')
        self.assertEqual(self.a.mutation_skips(src), [(2, 2, "@DoNotMutate"), (4, 4, "@Generated"),
                                                      (8, 8, "@CoverageIgnore")])
        self.assertEqual(self.a.mutation_skips("@"), [])
        self.assertEqual(self.a.mutation_skips("@DoNotMutate class A {}\n"), [(1, 1, "@DoNotMutate")])
        self.assertEqual(self.a.mutation_skips("int x;\n@Generated.;\n"), [(2, 2, "@Generated")])
        for path in ("pom.xml", "sub/pom.xml", ".mvn/maven.config", "sub/.mvn/jvm.config", ".mvn/extensions.xml"):
            with self.subTest(path):
                self.assertEqual(self.a.mutation_config(path, None), "PIT config (pom.xml or .mvn/)")
        for path in ("maven.config", "x.mvn/maven.config", "extensions.xml", "src/pom.xml.bak"):
            with self.subTest(path):
                self.assertIsNone(self.a.mutation_config(path, None))

    def test_a_skip_annotation_matches_by_suffix_as_pit_does(self):  # round 2, B2
        """PIT (ExcludedAnnotationInterceptor): an annotation whose name ends with a configured one is avoided."""
        src = ("class A {\n    @NoCoverageIgnore void a() {}\n    @MyGenerated void b() {}\n"
               "    @GeneratedX void c() {}\n    @x.y.MyDoNotMutate void d() {}\n}\n")
        self.assertEqual(self.a.mutation_skips(src), [(2, 2, "@NoCoverageIgnore"), (3, 3, "@MyGenerated"),
                                                      (5, 5, "@MyDoNotMutate")])

    def test_every_marker_spelling_javac_accepts(self):  # round 2, B1: whitespace, comments, line breaks, escapes
        variants = {
            "space after the prefix": "@ Disabled",
            "a block comment after the prefix": "@/**/Disabled",
            "a line break after the prefix": "@\n    Disabled",
            "a line comment after the prefix": "@ // why\n    Disabled",
            "a dotted name with spaces and comments": "@org . junit/* x */.jupiter . api\n.Disabled",
            "empty arguments": "@Disabled()",
            "arguments after a space": '@Disabled ("why")',
            "a unicode-escaped prefix": "\\u0040Disabled",
            "a unicode escape in the name": "@Dis\\u0061bled",
            "a multi-u escape": "\\uuu0040Disabled",
        }
        for why, ann in variants.items():
            for order in ("{a} @Test", "@Test {a}"):
                with self.subTest(why, order=order):
                    src = "class T {\n    " + order.format(a=ann) + " void a() {\n    }\n}\n"
                    self.assertEqual([(t.name, t.markers) for t in self.a.test_fns(src)], [("T.a", ["ignore"])])
            with self.subTest(why, on="class"):
                src = ann + "\nclass T {\n    @Test void a() {\n    }\n}\n"
                self.assertEqual([(t.name, t.markers) for t in self.a.test_fns(src)], [("T.a", ["ignore"])])
            with self.subTest(why, as_="skip annotation"):
                skip = ann.replace("Dis\\u0061bled", "DoNotM\\u0075tate").replace("Disabled", "DoNotMutate")
                got = self.a.mutation_skips("class T {\n    " + skip + " int a() { return 1; }\n}\n")
                self.assertEqual([m for _, _, m in got], ["@DoNotMutate"])

    def test_unicode_unescape(self):
        from scripts.mech_review.scan import unicode_unescape
        b = "\\"  # one backslash
        self.assertEqual(unicode_unescape(b + "u0040x"), "@x")
        self.assertEqual(unicode_unescape(b * 2 + "u0040x"), b * 2 + "u0040x")  # an escaped backslash: no escape
        self.assertEqual(unicode_unescape(b * 3 + "uu0040x"), b * 2 + "@x")
        self.assertEqual(unicode_unescape(b + "u004"), b + "u004")

    def test_without_unicode_escapes_nothing_is_decoded(self):
        d = adapter_file_dict()
        d["tests"]["skip"] = ["Disabled"]
        src = "class T {\n    " + "\\" + "u0040Disabled @Test void a() {\n    }\n}\n"
        self.assertEqual([(t.name, t.markers) for t in parse(d).test_fns(src)], [("a", [])])
        d["lexer"]["unicode_escapes"] = True
        self.assertEqual([(t.name, t.markers) for t in parse(d).test_fns(src)], [("a", ["ignore"])])
        d["lexer"]["unicode_escapes"] = "yes"
        with self.assertRaises(AdapterFileError) as cm:
            parse(d)
        self.assertEqual(str(cm.exception), "lexer.unicode_escapes: want true or false")
        d["lexer"]["unicode_escapes"] = False
        d["mutation"] = {"config_files": ["../pom.xml"], "config_name": "x"}
        with self.assertRaises(AdapterFileError) as cm:
            parse(d)
        self.assertTrue(str(cm.exception).startswith("mutation.config_files[0]: `../pom.xml`"), cm.exception)

    def test_an_escaped_backslash_is_no_unicode_escape(self):
        """JLS 3.3: a backslash is an escape only after an even run of backslashes: `\\u0040` stays."""
        src = "class T {\n    \\\\u0040Disabled @Test void a() {\n    }\n}\n"
        self.assertEqual([(t.name, t.markers) for t in self.a.test_fns(src)], [("T.a", [])])
        odd = "class T {\n    \\\\\\u0040Disabled @Test void a() {\n    }\n}\n"
        self.assertEqual([(t.name, t.markers) for t in self.a.test_fns(odd)], [("T.a", ["ignore"])])

    def test_a_test_that_prints_the_toolchains_message_is_judged_by_its_counts(self):  # B2
        fail = ("[INFO] Running com.example.CalcTest\nThe JAVA_HOME environment variable is not defined correctly\n"
                "JAVA_HOME not found\n[ERROR] No compiler is provided in this environment\n[ERROR] Tests run: 1, "
                "Failures: 1, Errors: 0, Skipped: 0\n")
        self.assertEqual(self.a.outcome(1, fail), "fail")
        self.assertEqual(self.a.outcome(1, "  The JAVA_HOME environment variable is not defined correctly\n"), "error")
        self.assertEqual(self.a.outcome(1, "JAVA_HOME not found\n"), "error")
        for out in ("The JAVA_HOME environment variable is not defined correctly,\nthis environment variable is needed\n",
                    "[ERROR] Failed to execute goal ...: Compilation failure\n[ERROR] No compiler is provided in this "
                    "environment. Perhaps you are running on a JRE rather than a JDK?\n"):
            with self.subTest(out):
                self.assertEqual(self.a.outcome(1, out), "env")

    def test_test_factory_is_no_case(self):  # S7: its method returns the tests, no void shape matches it
        self.assertEqual(self.a.tests["cases"], ["Test", "ParameterizedTest", "RepeatedTest", "TestTemplate"])


class SkipAnnotationsValidation(unittest.TestCase):
    def err(self, d):
        with self.assertRaises(AdapterFileError) as cm:
            parse(d)
        return str(cm.exception)

    def test_skip_annotations_need_style_declared_and_words(self):
        d = adapter_file_dict()
        d["mutation"] = {"skip_annotations": ["DoNotMutate"]}
        self.assertEqual(parse(d).mutation_skips("class A {\n    @DoNotMutate void a() {}\n}\n"), [(2, 2, "@DoNotMutate")])
        d["mutation"] = {"skip_annotations": ["DoNotMutate"], "skip_comments": ["mut off"]}
        self.assertEqual(parse(d).mutation_skips("// mut off\nclass A {\n    @DoNotMutate void a() {}\n}\n"),
                         [(1, 1, "mut off"), (3, 3, "@DoNotMutate")])
        d["mutation"] = {"skip_annotations": []}
        self.assertEqual(self.err(d), "mutation.skip_annotations: want at least one entry")
        d["mutation"] = {"skip_annotations": ["a b"]}
        self.assertEqual(self.err(d), "mutation.skip_annotations[0]: `a b` is not a word (letters, digits, _ and "
                                      "lexer.ident_chars)")
        d["tests"] = {"style": "calls", "cases": ["test"]}
        d["mutation"] = {"skip_annotations": ["DoNotMutate"]}
        self.assertEqual(self.err(d), "mutation.skip_annotations: needs tests.style declared: an annotation is a "
                                      "marker, its prefix the tests'")


class CallsBodies(unittest.TestCase):
    def test_a_skipped_call_keeps_its_body_only_with_a_callback(self):
        """beside the declared rule (a skipped declared test keeps its body), calls keep theirs (mini.toml)."""
        a = adapter_file.load(os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.toml"))
        src = 'test("bare")\nxtest("off", {\n  assertEquals(1, 1)\n})\nxtest("todo")\n'
        self.assertEqual(sorted(a.test_bodies(src)), ["bare", "off"])


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
