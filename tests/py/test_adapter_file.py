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

# every optional table and key in use (valid): the base for the field-by-field cases below
FULL = {
    "format": 1,
    "name": "full",
    "manifests": ["full.json"],
    "extensions": [".f"],
    "lexer": {"block_style": "braces", "brackets": ["()", "[]", "{}"], "ident_chars": "$", "member": ".",
              "line_comments": ["//"], "block_comments": [["/*", "*/"]],
              "strings": [{"quote": '"', "escape": "\\"},
                          {"quote": "`", "escape": "\\", "multiline": True, "interpolation": ["${", "}"],
                           "name": "template"}],
              "regex": {"delimiter": "/", "after": "(=", "after_words": ["return"]}},
    "tests": {"style": "calls", "groups": ["describe"], "cases": ["it", "xit"], "separator": " > ", "skip": ["xit"],
              "only": ["describe"], "skip_modifiers": ["skip"], "only_modifiers": ["only"], "table_modifiers": ["each"],
              "min_args": 2, "not_after": ["function"], "skipped_text": "`{name}` skipped"},
    "functions": {"shapes": ["function NAME (...) ...{...}"]},
    "asserts": {"chain": [{"start": "expect", "eq": ["toBe"], "negate": ["not"], "pass_through": ["resolves"]}],
                "call": [{"names": ["assertEquals"], "kind": "eq", "operands": [0, 1]},
                         {"names": ["assertTrue"], "kind": "other"}]},
    "suppressions": [{"directives": ["off"], "covers": {"off": "line"}, "lints": "rules", "reason_after": "--",
                      "problem": "`{lints}` bare", "hint": "why `{lints}`"},
                     {"directives": ["@ignore"], "covers": {"@ignore": "file"}, "reason_strip": [":"]}],
    "mutation": {"skip_comments": ["Mut off"], "config_files": ["mut.json"], "config_name": "Mut config"},
}

FIELD_CASES = [  # (dotted path in FULL, bad value or DEL, the error)
    ("name", "", "name: want a non-empty string"),
    ("manifests", "full.json", "manifests: want a list of non-empty strings"),
    ("extensions", [], "extensions: want at least one entry"),
    ("extensions.0", ".", "extensions[0]: `.`: want a file extension such as \".ts\""),
    ("lexer.x", 1, "lexer.x: unknown key"),
    ("lexer.block_style", DEL, "lexer.block_style: missing"),
    ("lexer.brackets", DEL, "lexer.brackets: missing"),
    ("lexer.brackets", [], "lexer.brackets: want at least one entry"),
    ("lexer.ident_chars", 3, "lexer.ident_chars: want a string"),
    ("lexer.member", 3, "lexer.member: want a string"),
    ("lexer.member", "::", "lexer.member: want one character or \"\""),
    ("lexer.line_comments", "//", "lexer.line_comments: want a list of non-empty strings"),
    ("lexer.block_comments", "/*", "lexer.block_comments: want a list of [open, close] pairs"),
    ("lexer.block_comments", [["/*"]], "lexer.block_comments[0]: want [open, close], two non-empty strings"),
    ("lexer.block_comments", [["/*", ""]], "lexer.block_comments[0]: want [open, close], two non-empty strings"),
    ("lexer.strings", {}, "lexer.strings: want an array of tables ([[lexer.strings]])"),
    ("lexer.strings.0", "\"", "lexer.strings[0]: want a table"),
    ("lexer.strings.0.x", 1, "lexer.strings[0].x: unknown key"),
    ("lexer.strings.0.quote", DEL, "lexer.strings[0].quote: missing"),
    ("lexer.strings.0.quote", "", "lexer.strings[0].quote: want a non-empty string"),
    ("lexer.strings.0.escape", 1, "lexer.strings[0].escape: want a string"),
    ("lexer.strings.1.interpolation", ["${"], "lexer.strings[1].interpolation: want [open, close], two non-empty strings"),
    ("lexer.strings.1.interpolation", "${", "lexer.strings[1].interpolation: want [open, close], two non-empty strings"),
    ("lexer.strings.1.name", "", "lexer.strings[1].name: want a non-empty string"),
    ("lexer.regex", [], "lexer.regex: want a table"),
    ("lexer.regex.x", 1, "lexer.regex.x: unknown key"),
    ("lexer.regex.delimiter", DEL, "lexer.regex.delimiter: missing"),
    ("lexer.regex.delimiter", 1, "lexer.regex.delimiter: want one character"),
    ("lexer.regex.after", 1, "lexer.regex.after: want a string"),
    ("lexer.regex.after_words", "return", "lexer.regex.after_words: want a list of non-empty strings"),
    ("tests", [], "tests: want a table"),
    ("tests.x", 1, "tests.x: unknown key"),
    ("tests.style", DEL, "tests.style: missing"),
    ("tests.cases", DEL, "tests.cases: missing"),
    ("tests.groups", ["a b"], "tests.groups[0]: `a b` is not a word (letters, digits, _ and lexer.ident_chars)"),
    ("tests.only", ["zz"], "tests.only[0]: `zz` is not in tests.groups or tests.cases"),
    ("tests.only", "it", "tests.only: want a list of non-empty strings"),
    ("tests.skip_modifiers", ["a.b"], "tests.skip_modifiers[0]: `a.b` is not a word (letters, digits, _ and lexer.ident_chars)"),
    ("tests.only_modifiers", [1], "tests.only_modifiers: want a list of non-empty strings"),
    ("tests.table_modifiers", ["e ach"], "tests.table_modifiers[0]: `e ach` is not a word (letters, digits, _ and lexer.ident_chars)"),
    ("tests.separator", "", "tests.separator: want a non-empty string"),
    ("tests.min_args", True, "tests.min_args: want a whole number >= 0"),
    ("tests.min_args", "2", "tests.min_args: want a whole number >= 0"),
    ("tests.not_after", "function", "tests.not_after: want a list of non-empty strings"),
    ("tests.skipped_text", 3, "tests.skipped_text: want a non-empty string"),
    ("tests.skipped_text", "{}", "tests.skipped_text: unknown placeholder `{}`: want `{name}`"),
    ("functions", [], "functions: want a table"),
    ("functions.x", 1, "functions.x: unknown key"),
    ("functions.shapes", DEL, "functions.shapes: missing"),
    ("functions.shapes", "function NAME {...}", "functions.shapes: want a list of non-empty strings"),
    ("asserts", [], "asserts: want a table"),
    ("asserts.x", 1, "asserts.x: unknown key"),
    ("asserts.chain", {}, "asserts.chain: want an array of tables ([[asserts.chain]])"),
    ("asserts.call", {}, "asserts.call: want an array of tables ([[asserts.call]])"),
    ("asserts.chain.0.x", 1, "asserts.chain[0].x: unknown key"),
    ("asserts.chain.0.start", DEL, "asserts.chain[0].start: missing"),
    ("asserts.chain.0.eq", DEL, "asserts.chain[0].eq: missing"),
    ("asserts.chain.0.start", "", "asserts.chain[0].start: want a non-empty string"),
    ("asserts.chain.0.start", "ex pect", "asserts.chain[0].start: `ex pect` is not a word (letters, digits, _ and lexer.ident_chars)"),
    ("asserts.chain.0.eq", ["to Be"], "asserts.chain[0].eq[0]: `to Be` is not a word (letters, digits, _ and lexer.ident_chars)"),
    ("asserts.chain.0.negate", ["n ot"], "asserts.chain[0].negate[0]: `n ot` is not a word (letters, digits, _ and lexer.ident_chars)"),
    ("asserts.chain.0.pass_through", "resolves", "asserts.chain[0].pass_through: want a list of non-empty strings"),
    ("asserts.call.0.x", 1, "asserts.call[0].x: unknown key"),
    ("asserts.call.0.names", DEL, "asserts.call[0].names: missing"),
    ("asserts.call.0.names", [], "asserts.call[0].names: want at least one entry"),
    ("asserts.call.0.names", ["expect"], "asserts.call[0].names[0]: `expect` is already an assert shape"),
    ("asserts.call.0.kind", DEL, "asserts.call[0].kind: missing"),
    ("asserts.call.0.kind", 3, "asserts.call[0].kind: want a non-empty string"),
    ("asserts.call.0.kind", "ne", None),  # valid: ne takes operands too
    ("asserts.call.0.operands", "01", "asserts.call[0].operands: want [left, right]: two different argument indexes"),
    ("asserts.call.0.operands", [0], "asserts.call[0].operands: want [left, right]: two different argument indexes"),
    ("asserts.call.0.operands", [0, -1], "asserts.call[0].operands[1]: want a whole number >= 0"),
    ("asserts.call.1.operands", [0, 1], "asserts.call[1].operands: kind other has no operands"),
    ("suppressions", {}, "suppressions: want an array of tables ([[suppressions]])"),
    ("suppressions.0.x", 1, "suppressions[0].x: unknown key"),
    ("suppressions.0.directives", DEL, "suppressions[0].directives: missing"),
    ("suppressions.0.covers", DEL, "suppressions[0].covers: missing"),
    ("suppressions.0.directives", [], "suppressions[0].directives: want at least one entry"),
    ("suppressions.0.covers", "line", "suppressions[0].covers: want a table"),
    ("suppressions.0.covers.extra", "line", "suppressions[0].covers.extra: unknown key"),
    ("suppressions.0.lints", "all", "suppressions[0].lints: `all`: want rules or directive"),
    ("suppressions.0.reason_after", "", "suppressions[0].reason_after: want a non-empty string"),
    ("suppressions.0.reason_strip", [":"], "suppressions[0].reason_strip: not with reason_after: the reason is the text after the mark"),
    ("suppressions.1.reason_strip", ":", "suppressions[1].reason_strip: want a list of non-empty strings"),
    ("suppressions.0.hint", "{x}", "suppressions[0].hint: unknown placeholder `{x}`: want `{lints}`"),
    ("mutation", [], "mutation: want a table"),
    ("mutation.x", 1, "mutation.x: unknown key"),
    ("mutation.skip_comments", "Mut off", "mutation.skip_comments: want a list of non-empty strings"),
    ("mutation.config_files", "mut.json", "mutation.config_files: want a list of non-empty strings"),
    ("mutation.config_name", "", "mutation.config_name: want a non-empty string"),
    ("mutation.config_files", [], None),  # valid: a name with no config files is harmless
    ("lexer.block_style", 3, "lexer.block_style: want a non-empty string"),
    ("tests.style", 3, "tests.style: want a non-empty string"),
    ("lexer.strings.1.interpolation", ["${", ""], "lexer.strings[1].interpolation: want [open, close], two non-empty strings"),
    ("lexer.strings", DEL, None),  # valid: a stack with no string literals
    ("lexer.regex.after_words", DEL, None),  # valid: a regex literal after the `after` characters only
    ("lexer.regex.after", DEL, None),
    ("tests.min_args", DEL, None),
]


class Valid(unittest.TestCase):
    def test_a_file_with_every_table_builds_its_adapter(self):
        a = parse(FULL)
        self.assertEqual((a.name, a.manifests, a.from_file), ("full", ("full.json",), True))

    def test_a_top_level_value_that_is_not_a_table_is_an_error(self):
        with self.assertRaises(AdapterFileError) as e:
            parse(["format", 1])
        self.assertEqual(str(e.exception), "want a table")
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

    def test_every_field_names_itself_in_its_error(self):
        for path, value, want in FIELD_CASES:
            with self.subTest(path, value=value):
                data = with_(path, value, FULL)
                if want is None:
                    self.assertEqual(parse(data).name, "full")
                else:
                    self.assertEqual(self.err(data), want)

    def test_a_block_comment_opener_cannot_be_a_word_char(self):
        data = with_("lexer.line_comments", [], FULL)
        data["lexer"]["ident_chars"] = "/"
        self.assertEqual(self.err(data), "lexer.ident_chars: `/` cannot be part of a word (a comment opener)")

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

    def test_brackets_must_be_real_pairs_each_char_once_with_calls_and_blocks(self):
        cases = {
            ("(]", "[]", "{}"): "lexer.brackets[1]: `]` is already in lexer.brackets[0]",
            ("()", "{}", "(>"): "lexer.brackets[2]: `(` is already in lexer.brackets[0]",
            ("(}", "{)"): "lexer.brackets: want \"()\": calls are `name(...)`",
            ("()", "[]"): "lexer.brackets: want \"{}\": block_style braces opens blocks with `{`",
        }
        for value, want in cases.items():
            with self.subTest(value):
                self.assertEqual(self.err(with_("lexer.brackets", list(value))), want)

    def test_a_utf8_bom_is_not_part_of_the_file(self):
        import os
        import tempfile
        from scripts.mech_review.adapter_file import load
        with open(os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.toml"), "rb") as f:
            text = f.read()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bom.toml")
            with open(path, "wb") as f:
                f.write(b"\xef\xbb\xbf" + text)
            self.assertEqual(load(path).name, "mini")

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

    def test_ident_chars_that_would_change_what_a_word_is_are_rejected(self):
        cases = {
            " ": "lexer.ident_chars: ` ` cannot be part of a word (whitespace)",
            "$(": "lexer.ident_chars: `(` cannot be part of a word (a bracket)",
            '"': "lexer.ident_chars: `\"` cannot be part of a word (a string quote)",
            "#": "lexer.ident_chars: `#` cannot be part of a word (a comment opener)",
            ".": "lexer.ident_chars: `.` cannot be part of a word (the member character)",
        }
        for value, want in cases.items():
            with self.subTest(value):
                self.assertEqual(self.err(with_("lexer.ident_chars", value)), want)

    def test_a_member_char_that_is_a_word_char_bracket_or_space_is_rejected(self):
        cases = {
            "a": "lexer.member: `a` is a word character: want punctuation such as \".\"",
            "_": "lexer.member: `_` is a word character: want punctuation such as \".\"",
            " ": "lexer.member: ` ` is whitespace: want punctuation such as \".\"",
            "(": "lexer.member: `(` is a bracket: want punctuation such as \".\"",
        }
        for value, want in cases.items():
            with self.subTest(value):
                self.assertEqual(self.err(with_("lexer.member", value)), want)

    def test_a_chain_needs_eq_matchers_and_a_start_of_its_own(self):
        chain = {"start": "expect", "eq": []}
        self.assertEqual(self.err(with_("asserts", {"chain": [chain]})), "asserts.chain[0].eq: want at least one entry")
        two = [{"start": "expect", "eq": ["toBe"]}, {"start": "expect", "eq": ["toEqual"]}]
        self.assertEqual(self.err(with_("asserts", {"chain": two})),
                         "asserts.chain[1].start: `expect` is already asserts.chain[0].start")

    def test_a_call_name_in_two_call_shapes_is_rejected(self):
        calls = [{"names": ["check"], "kind": "other"}, {"names": ["check"], "kind": "eq", "operands": [0, 1]}]
        self.assertEqual(self.err(with_("asserts", {"call": calls})),
                         "asserts.call[1].names[0]: `check` is already an assert shape")

    def test_a_template_takes_plain_fields_only(self):
        sup = {"directives": ["lint-off"], "covers": {"lint-off": "line"}, "problem": "{lints:{lints}<5}"}
        self.assertEqual(self.err(with_("suppressions", [sup])),
                         "suppressions[0].problem: `{lints:{lints}<5}`: want plain `{lints}` (no `!` conversion or `:` spec)")
        self.assertEqual(self.err(with_("tests.skipped_text", "{name:{name}<5}")),
                         "tests.skipped_text: `{name:{name}<5}`: want plain `{name}` (no `!` conversion or `:` spec)")
        self.assertEqual(self.err(with_("tests.skipped_text", "{name!r}")),
                         "tests.skipped_text: `{name!r}`: want plain `{name}` (no `!` conversion or `:` spec)")

    def test_a_template_with_plain_fields_and_escaped_braces_loads(self):
        self.assertEqual(parse(with_("tests.skipped_text", "test {{x}} `{name}` off")).ignored_text("a"), "test {x} `a` off")

    def test_a_template_that_would_fail_to_format_is_rejected_at_load(self):
        # the reason after `bad template:` is python's own wording, which changes between versions
        for value in ("{lints!z}", "{lints:>>>}", "{"):
            with self.subTest(value):
                sup = {"directives": ["lint-off"], "covers": {"lint-off": "line"}, "problem": value}
                got = self.err(with_("suppressions", [sup]))
                self.assertTrue(got.startswith("suppressions[0].problem: bad template: "), got)

    def test_format_must_be_a_whole_number(self):
        self.assertEqual(self.err(with_("format", 1.0)), "format: `1.0`: want 1")

    def test_a_function_shape_name_cannot_be_optional(self):
        self.assertEqual(self.err(with_("functions", {"shapes": ["fn NAME? (...) {...}"]})),
                         "functions.shapes[0]: `fn NAME? (...) {...}`: NAME cannot be optional")

    def test_an_extension_listed_twice_is_rejected(self):
        self.assertEqual(self.err(with_("extensions", [".mini", ".mini"])), "extensions[1]: `.mini` is listed twice")

    def test_a_regex_delimiter_is_one_character(self):
        self.assertEqual(self.err(with_("lexer.regex", {"delimiter": "//"})), "lexer.regex.delimiter: want one character")


class ReservedName(unittest.TestCase):
    def test_auto_is_not_a_stack_name(self):
        # `auto` is the stack job's "find it" input: a file named so would read as a settled stack of that name
        with self.assertRaises(AdapterFileError) as e:
            parse(with_("name", "auto"))
        self.assertEqual(str(e.exception), "name: `auto` is reserved (stack: auto finds the stack): want another name")


class TargetOs(unittest.TestCase):
    """`target-os` (#58): the OS a stack's tests run on. linux, macos or windows; missing reads linux."""

    def test_each_of_the_three_values_parses(self):
        for os_name in ("linux", "macos", "windows"):
            with self.subTest(os_name):
                self.assertEqual(parse(with_("target-os", os_name)).target_os, os_name)

    def test_a_missing_target_os_reads_linux(self):
        self.assertEqual(parse(GOOD).target_os, "linux")

    def test_any_other_value_names_the_field(self):
        cases = [
            ("solaris", "target-os: `solaris`: want linux, macos or windows"),
            ("Linux", "target-os: `Linux`: want linux, macos or windows"),
            ("ubuntu-latest", "target-os: `ubuntu-latest`: want linux, macos or windows"),
            ("", "target-os: want a non-empty string"),
            (3, "target-os: want a non-empty string"),
            (["linux"], "target-os: want a non-empty string"),
        ]
        for value, want in cases:
            with self.subTest(value=value):
                with self.assertRaises(AdapterFileError) as e:
                    parse(with_("target-os", value))
                self.assertEqual(str(e.exception), want)


if __name__ == "__main__":
    unittest.main()
