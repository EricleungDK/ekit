"""Adapter file validation (#16): adapter_file.parse(dict) builds the stack's adapter or raises AdapterFileError naming
the bad field. Pure: no git, no TOML reader (the dicts are what tomllib would read)."""
import copy
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review.adapter_file import AdapterFileError, parse

GOOD = {
    "format": 1,
    "name": "mini",
    "extensions": [".mini"],
    "lexer": {"block_style": "braces", "brackets": ["()", "{}"], "line_comments": ["#"],
              "strings": [{"quote": '"', "escape": "\\"}]},
    "tests": {"style": "calls", "groups": ["suite"], "cases": ["test", "xtest"], "skip": ["xtest"]},
    "asserts": {"call": [{"names": ["assertEquals"], "kind": "eq", "operands": [0, 1]}]},
}


def with_(path, value, base=GOOD):
    """GOOD with the dotted path set to value (value DEL: the key removed)."""
    d = copy.deepcopy(base)
    *parents, last = path.split(".")
    cur = d
    for p in parents:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    if value is DEL:
        del cur[last]
    elif isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value
    return d


DEL = object()


class Valid(unittest.TestCase):
    def test_a_minimal_file_builds_an_adapter_named_by_the_file(self):
        a = parse(GOOD)
        self.assertEqual((a.name, a.manifests, a.from_file), ("mini", (), True))

    def test_the_adapter_classifies_by_extension_and_test_paths(self):
        a = parse(GOOD)
        self.assertEqual([a.classify(p, ["tests/**"]) for p in ("tests/a.mini", "src/a.mini", "src/a.py")],
                         ["test", "prod", None])


class Invalid(unittest.TestCase):
    def err(self, data):
        with self.assertRaises(AdapterFileError) as e:
            parse(data)
        return str(e.exception)

    def test_each_required_top_level_field_is_named_when_missing(self):
        for k in ("format", "name", "extensions", "lexer", "tests", "asserts"):
            with self.subTest(k):
                self.assertEqual(self.err(with_(k, DEL)), f"{k}: missing")

    def test_an_unknown_key_is_named_not_ignored(self):
        self.assertEqual(self.err(with_("tests.skip_modifier", ["skip"])), "tests.skip_modifier: unknown key")
        self.assertEqual(self.err(with_("extra", 1)), "extra: unknown key")

    def test_wrong_types_name_the_field(self):
        cases = {
            "name": (3, "name: want a non-empty string"),
            "extensions": ("mini", "extensions: want a list of non-empty strings"),
            "lexer": ([], "lexer: want a table"),
            "lexer.strings.0.multiline": ("yes", "lexer.strings[0].multiline: want true or false"),
            "tests.min_args": (-1, "tests.min_args: want a whole number >= 0"),
            "tests.cases": ([], "tests.cases: want at least one entry"),
        }
        for path, (value, want) in cases.items():
            with self.subTest(path):
                self.assertEqual(self.err(with_(path, value)), want)

    def test_format_must_be_the_supported_version(self):
        self.assertEqual(self.err(with_("format", 2)), "format: `2`: want 1")
        self.assertEqual(self.err(with_("format", True)), "format: `True`: want 1")

    def test_an_unknown_block_style_is_named(self):
        self.assertEqual(self.err(with_("lexer.block_style", "tabs")),
                         "lexer.block_style: unknown block style `tabs`: want braces")

    def test_indent_and_keyword_block_styles_are_not_supported_yet(self):
        self.assertEqual(self.err(with_("lexer.block_style", "indent")),
                         "lexer.block_style: `indent` is not supported yet: want braces")

    def test_bad_values_name_the_field(self):
        cases = {
            "extensions.0": ("mini", "extensions[0]: `mini`: want a file extension such as \".ts\""),
            "name": ("my stack", "name: `my stack`: want letters, digits, _ or -"),
            "lexer.brackets.0": ("(", "lexer.brackets[0]: `(`: want an opener and a closer, e.g. \"()\""),
            "lexer.brackets": (["{}"], "lexer.brackets: want \"()\": calls are `name(...)`"),
            "lexer.strings.0.escape": ("\\\\", "lexer.strings[0].escape: want one character or \"\""),
            "tests.style": ("functions", "tests.style: unknown style `functions`: want calls"),
            "tests.skip": (["xit"], "tests.skip[0]: `xit` is not in tests.groups or tests.cases"),
            "tests.cases": (["it("], "tests.cases[0]: `it(` is not a word (letters, digits, _ and lexer.ident_chars)"),
            "tests.skipped_text": ("test {test} skipped", "tests.skipped_text: unknown placeholder `{test}`: want `{name}`"),
            "asserts.call.0.kind": ("equal", "asserts.call[0].kind: `equal`: want eq, ne or other"),
            "asserts.call.0.operands": ([0, 0], "asserts.call[0].operands: want [left, right]: two different argument indexes"),
        }
        for path, (value, want) in cases.items():
            with self.subTest(path):
                self.assertEqual(self.err(with_(path, value)), want)

    def test_an_eq_call_shape_needs_its_operands(self):
        self.assertEqual(self.err(with_("asserts.call.0.operands", DEL)),
                         "asserts.call[0].operands: missing: kind eq needs [left, right] argument indexes")

    def test_a_file_with_no_assert_shape_is_an_error(self):
        self.assertEqual(self.err(with_("asserts", {})), "asserts: no assert shape: want [[asserts.chain]] or [[asserts.call]]")

    def test_interpolation_needs_a_multiline_string(self):
        self.assertEqual(self.err(with_("lexer.strings.0.interpolation", ["${", "}"])),
                         "lexer.strings[0].interpolation: needs multiline = true")

    def test_a_bad_function_shape_names_the_shape_and_the_element(self):
        cases = {
            "fn NAME (...) %%": "functions.shapes[0]: `fn NAME (...) %%`: must end with a body: `{...}`, `...{...}` or BODY",
            "fn NAME <...> {...}": "functions.shapes[0]: `fn NAME <...> {...}`: unknown element `<...>`",
            "fn (...) {...}": "functions.shapes[0]: `fn (...) {...}`: want exactly one NAME",
            "NAME (...) {...}": "functions.shapes[0]: `NAME (...) {...}`: the first required element must be a word",
            "fn NAME :... (...) {...}": "functions.shapes[0]: `fn NAME :... (...) {...}`: `:...` must be followed by a literal",
        }
        for shape, want in cases.items():
            with self.subTest(shape):
                self.assertEqual(self.err(with_("functions", {"shapes": [shape]})), want)

    def test_every_suppression_directive_needs_a_cover(self):
        sup = {"directives": ["lint-off", "lint-off-line"], "covers": {"lint-off": "next-line"}}
        self.assertEqual(self.err(with_("suppressions", [sup])),
                         "suppressions[0].covers.lint-off-line: missing: want line, next-line or file")
        sup["covers"]["lint-off-line"] = "block"
        self.assertEqual(self.err(with_("suppressions", [sup])),
                         "suppressions[0].covers.lint-off-line: `block`: want line, next-line or file")

    def test_a_suppression_template_with_an_unknown_placeholder_is_an_error(self):
        sup = {"directives": ["lint-off"], "covers": {"lint-off": "line"}, "problem": "{rule} off"}
        self.assertEqual(self.err(with_("suppressions", [sup])),
                         "suppressions[0].problem: unknown placeholder `{rule}`: want `{lints}`")

    def test_mutation_config_files_need_a_name(self):
        self.assertEqual(self.err(with_("mutation", {"config_files": ["mut.toml"]})),
                         "mutation.config_name: missing: config_files needs a name for the entry")

    def test_a_regex_delimiter_is_one_character(self):
        self.assertEqual(self.err(with_("lexer.regex", {"delimiter": "//"})), "lexer.regex.delimiter: want one character")


if __name__ == "__main__":
    unittest.main()
