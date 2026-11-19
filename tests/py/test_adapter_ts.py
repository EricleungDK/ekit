"""TS through the shipped adapter file (#16): `mech-review.py r2 --stack ts --adapter scripts/mech_review/adapters/ts.toml`
on fixture repos, through cli.main in this process. Each case asserts the entries (severity, class, line, problem) and
that the built-in `ts` adapter gives the same entries: R2 through the file must match the built-in (the parity spec)."""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest

import _kit
from scripts.mech_review import cli

TS_FILE = os.path.join(_kit.ROOT, "scripts", "mech_review", "adapters", "ts.toml")

TEST = '''import { describe, it, expect } from "vitest";

describe("Calc", () => {
  it("adds", () => {
    expect(add(1, 2)).toBe(3);
  });
});
'''


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           *args], check=True, capture_output=True, text=True).stdout


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = cli.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


class TsThroughTheFile(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name
        git(self.repo, "init", "-q", "-b", "main")

    def commit(self, files):
        for rel, text in files.items():
            full = os.path.join(self.repo, rel)
            if text is None:
                os.remove(full)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", newline="\n") as f:
                f.write(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "c")
        return git(self.repo, "rev-parse", "HEAD").strip()

    def r2(self, base_files, head_files):
        """(rc, [(severity, class, file, line, problem)]) through the file; asserts the built-in gives the same."""
        base = self.commit(base_files)
        head = self.commit(head_files)
        argv = ["r2", "--repo", self.repo, "--base", base, "--head", head, "--stack", "ts", "--test-paths", "tests/**"]
        got = []
        for extra in (["--adapter", TS_FILE], []):
            rc, out, err = run(argv + extra)
            self.assertIn(rc, (0, 1), err)
            ents = [(e["severity"], e["class"], e["file"], e["line"], e["problem"]) for e in json.loads(out)["entries"]]
            got.append((rc, ents))
        file_rc, file_ents = got[0]
        if file_ents and any(e[1] == "needs-human" and "does not parse" in e[4] for e in file_ents):
            return got  # the parse class differs by design (A4): the caller compares both sides itself
        self.assertEqual(got[0], got[1], "adapter file and built-in ts differ")
        return file_rc, file_ents

    # ---- skips and focus ----
    def test_skip_forms_are_fails_naming_the_test(self):
        cases = {
            'it.skip("adds"': "test `Calc > adds` marked skipped (skip, todo or x-prefixed)",
            'xit("adds"': "test `Calc > adds` marked skipped (skip, todo or x-prefixed)",
            'it.only("adds"': "test `Calc > adds` marked only: the other tests do not run",
            'fit("adds"': "test `Calc > adds` marked only: the other tests do not run",
        }
        for new, problem in cases.items():
            with self.subTest(new):
                rc, ents = self.r2({"tests/a.test.ts": TEST}, {"tests/a.test.ts": TEST.replace('it("adds"', new)})
                self.assertEqual((rc, ents), (1, [("fail", "agent-fixable", "tests/a.test.ts", 4, problem)]))

    def test_a_skipped_group_skips_the_tests_in_it(self):
        rc, ents = self.r2({"tests/a.test.ts": TEST}, {"tests/a.test.ts": TEST.replace("describe(", "describe.skip(")})
        self.assertEqual(ents, [("fail", "agent-fixable", "tests/a.test.ts", 4,
                                 "test `Calc > adds` marked skipped (skip, todo or x-prefixed)")])

    def test_a_todo_without_a_function_is_a_skip(self):
        head = TEST.replace("  });\n});", '  });\n  it.todo("later");\n  it("bare");\n});')
        rc, ents = self.r2({"tests/a.test.ts": TEST}, {"tests/a.test.ts": head})
        self.assertEqual([(e[3], e[4]) for e in ents],
                         [(7, "test `Calc > later` marked skipped (skip, todo or x-prefixed)"),
                          (8, "test `Calc > bare` marked skipped (skip, todo or x-prefixed)")])

    def test_each_names_the_test_from_its_template(self):
        each = TEST.replace('it("adds", () => {', 'it.each([[1, 2, 3]])("adds %i", (a, b, c) => {')
        rc, ents = self.r2({"tests/a.test.ts": each}, {"tests/a.test.ts": each.replace("it.each(", "it.skip.each(")})
        self.assertEqual([e[4] for e in ents], ["test `Calc > adds %i` marked skipped (skip, todo or x-prefixed)"])

    def test_a_function_named_like_a_test_call_is_not_a_test(self):
        base = TEST + "function it(name, fn) { fn(); }\nfunction* test(x) { yield x; }\n"
        rc, ents = self.r2({"tests/a.test.ts": base}, {"tests/a.test.ts": TEST})
        self.assertEqual((rc, ents), (0, []))

    # ---- asserts ----
    def test_changed_expected_values_are_confirms(self):
        cases = {
            ".toBe(3)": (".toBe(4)", "expected value changed in `Calc > adds`: was 3, now 4"),
            "expect(add(1, 2)).toBe(3)": ("expect(add(1, 2)).not.toBe(3)",
                                          "assertion replaced in `Calc > adds`: `expect(add(1, 2)).toBe(3)` -> "
                                          "`expect(add(1, 2)).not.toBe(3)`"),
        }
        for old, (new, problem) in cases.items():
            with self.subTest(new):
                rc, ents = self.r2({"tests/a.test.ts": TEST}, {"tests/a.test.ts": TEST.replace(old, new)})
                self.assertEqual((rc, ents), (0, [("confirm", "agent-fixable", "tests/a.test.ts", 5, problem)]))

    def test_resolves_and_strict_equal_are_eq_asserts_and_others_compare_by_text(self):
        base = TEST.replace("expect(add(1, 2)).toBe(3);", "await expect(p).resolves.toStrictEqual(3);\n    expect(x).toBeTruthy();")
        head = base.replace("toStrictEqual(3)", "toStrictEqual(5)").replace("toBeTruthy()", "toBeDefined()")
        rc, ents = self.r2({"tests/a.test.ts": base}, {"tests/a.test.ts": head})
        self.assertEqual([(e[0], e[3], e[4]) for e in ents],
                         [("confirm", 5, "expected value changed in `Calc > adds`: was 3, now 5"),
                          ("confirm", 6, "assertion replaced in `Calc > adds`: `expect(x).toBeTruthy()` -> "
                                         "`expect(x).toBeDefined()`")])

    def test_a_dropped_assert_is_a_fail(self):
        two = TEST.replace("toBe(3);", "toBe(3);\n    expect(add(2, 2)).toBe(4);")
        rc, ents = self.r2({"tests/a.test.ts": two}, {"tests/a.test.ts": TEST})
        self.assertEqual((rc, ents), (1, [("fail", "agent-fixable", "tests/a.test.ts", 4,
                                           "assertions in test `Calc > adds` dropped from 2 to 1")]))

    def test_an_assert_moved_into_any_helper_form_the_test_calls_is_not_a_drop(self):
        helpers = {
            "function": "function check(a, b) {\n  expect(a).toBe(b);\n}\n",
            "generator": "function* check(a, b) {\n  expect(a).toBe(b);\n}\n",
            "arrow block": "export const check = async (a: number, b: number) => {\n  expect(a).toBe(b);\n};\n",
            "arrow expression": "const check = (a, b) => expect(a).toBe(b);\n",
            "function expression": "let check: Fn = function (a, b) {\n  expect(a).toBe(b);\n};\n",
            "one-param arrow": "var check = a => expect(a).toBe(3);\n",
        }
        for label, helper in helpers.items():
            with self.subTest(label):
                head = helper + TEST.replace("expect(add(1, 2)).toBe(3);", "check(add(1, 2), 3);")
                rc, ents = self.r2({"tests/a.test.ts": TEST}, {"tests/a.test.ts": head})
                self.assertEqual((rc, ents), (0, []))

    def test_a_helper_that_loses_its_assert_is_a_fail_for_the_file(self):
        helper = "function check(a, b) {\n  expect(a).toBe(b);\n}\n"
        rc, ents = self.r2({"tests/a.test.ts": helper + TEST}, {"tests/a.test.ts": "function check(a, b) {}\n" + TEST})
        self.assertEqual((rc, ents), (1, [("fail", "agent-fixable", "tests/a.test.ts", 0,
                                           "assertions outside test fns in `tests/a.test.ts` dropped from 1 to 0")]))

    # ---- masking: strings, templates, regex literals, comments ----
    def test_tests_in_strings_templates_regexes_and_comments_are_not_tests(self):
        noise = ('const s = "it(\'a\', () => {})";\nconst t = `it("b", () => {}) ${x} it("c", () => {})`;\n'
                 'const r = /it\\("d"/g; const q = a / b / c;\n// it("e", () => {});\n/* it("f", () => {}) */\n'
                 "const u = 'don\\'t';\n")
        rc, ents = self.r2({"tests/a.test.ts": noise + TEST}, {"tests/a.test.ts": TEST})
        self.assertEqual((rc, ents), (0, []))

    def test_unterminated_literals_and_comments_are_needs_human_through_the_file(self):
        cases = {
            "const t = `open\n": "file does not parse: unterminated template literal (line 1)",
            "/* open\n": "file does not parse: unterminated block comment (line 1)",
        }
        for prefix, problem in cases.items():
            with self.subTest(prefix):
                (rc, ents), (brc, bents) = self.r2({"tests/a.test.ts": TEST}, {"tests/a.test.ts": prefix + TEST})
                self.assertEqual((rc, [(e[0], e[1], e[3], e[4]) for e in ents]), (1, [("fail", "needs-human", 1, problem)]))
                self.assertEqual([(e[0], e[1], e[3], e[4]) for e in bents], [("fail", "agent-fixable", 1, problem)])

    def test_a_closer_that_does_not_match_is_needs_human_on_its_line(self):
        (rc, ents), (brc, bents) = self.r2({"tests/a.test.ts": TEST}, {"tests/a.test.ts": TEST + "const a = (1;\n}\n"})
        self.assertEqual([(e[1], e[3], e[4]) for e in ents], [("needs-human", 9, "file does not parse: unexpected `}` (line 9)")])
        self.assertEqual([(e[1], e[3], e[4]) for e in bents], [("agent-fixable", 9, "file does not parse: unexpected `}` (line 9)")])

    # ---- suppressions ----
    def test_suppressions_need_a_reason_on_an_added_line(self):
        src = "export function add(a: number, b: number): number {\n  return a + b;\n}\n"
        cases = {
            "// eslint-disable-next-line no-console\n": [
                ("fail", 1, "`eslint-disable-next-line no-console` added without a reason")],
            "// eslint-disable-next-line no-console -- logs on purpose\n": [],
            "const z = 1; // eslint-disable-line no-unused-vars\n": [
                ("fail", 1, "`eslint-disable-line no-unused-vars` added without a reason")],
            "/* eslint-disable */\n": [("fail", 1, "`eslint-disable` added without a reason")],
            "// @ts-ignore\n": [("fail", 1, "`@ts-ignore` added without a reason")],
            "// @ts-expect-error: the bad input under test\n": [],
            "// @ts-nocheck -- generated\n": [],
            "// @ts-nocheck: \n": [("fail", 1, "`@ts-nocheck` added without a reason")],
            "// eslint-disabled-thing\n": [],
        }
        for line, want in cases.items():
            with self.subTest(line):
                rc, ents = self.r2({"src/calc.ts": src}, {"src/calc.ts": line + src})
                self.assertEqual([(e[0], e[3], e[4]) for e in ents], want)

    # ---- scope, nesting, owners ----
    def test_outside_test_paths_only_asserts_inside_tests_count(self):
        prod = 'expect(0).toBe(0);\nit("x", () => {\n  expect(1).toBe(1);\n  expect(2).toBe(2);\n});\n'
        rc, ents = self.r2({"src/a.ts": prod}, {"src/a.ts": prod.replace("expect(0).toBe(0);\n", "").replace("  expect(2).toBe(2);\n", "")})
        self.assertEqual((rc, ents), (1, [("fail", "agent-fixable", "src/a.ts", 1, "assertions in test `x` dropped from 2 to 1")]))

    def test_a_name_joins_only_the_groups_around_it_outermost_first(self):
        src = ('describe("Z", () => {\n  describe("A", () => {\n    it("t", () => { expect(1).toBe(1); });\n  });\n});\n'
               'describe("B", () => {});\nit("u", () => { expect(2).toBe(2); });\n')
        rc, ents = self.r2({"tests/a.test.ts": src},
                           {"tests/a.test.ts": src.replace('it("t"', 'it.skip("t"').replace('it("u"', 'xit("u"')})
        self.assertEqual([(e[3], e[4]) for e in ents],
                         [(3, "test `Z > A > t` marked skipped (skip, todo or x-prefixed)"),
                          (7, "test `u` marked skipped (skip, todo or x-prefixed)")])

    def test_the_innermost_function_owns_an_assert(self):
        nested = "function outer() {\n  function inner(a) {\n    expect(a).toBe(3);\n  }\n}\n"
        head = nested + TEST.replace("expect(add(1, 2)).toBe(3);", "inner(add(1, 2));")
        rc, ents = self.r2({"tests/a.test.ts": "function outer() {\n  function inner(a) {}\n}\n" + TEST}, {"tests/a.test.ts": head})
        self.assertEqual((rc, ents), (0, []))

    def test_a_changed_actual_value_is_a_confirm_naming_it(self):
        rc, ents = self.r2({"tests/a.test.ts": TEST}, {"tests/a.test.ts": TEST.replace("expect(add(1, 2))", "expect(add(2, 1))")})
        self.assertEqual(ents, [("confirm", "agent-fixable", "tests/a.test.ts", 5,
                                 "expected value changed in `Calc > adds`: was add(1,2), now add(2,1)")])

    def test_a_changed_value_under_not_is_a_confirm(self):
        neg = TEST.replace(".toBe(3)", ".not.toBe(3)")
        rc, ents = self.r2({"tests/a.test.ts": neg}, {"tests/a.test.ts": neg.replace("toBe(3)", "toBe(4)")})
        self.assertEqual([e[4] for e in ents], ["expected value changed in `Calc > adds`: was 3, now 4"])

    def test_a_matcher_with_an_argument_that_is_not_eq_compares_by_text(self):
        gt = TEST.replace(".toBe(3)", ".toBeGreaterThan(2)")
        rc, ents = self.r2({"tests/a.test.ts": gt}, {"tests/a.test.ts": gt.replace("(2)", "(1)")})
        self.assertEqual([e[4] for e in ents], ["assertion replaced in `Calc > adds`: `expect(add(1, 2)).toBeGreaterThan(2)` -> "
                                                "`expect(add(1, 2)).toBeGreaterThan(1)`"])

    def test_a_bare_expect_is_an_assert(self):
        bare = TEST.replace("expect(add(1, 2)).toBe(3);", "expect(a);\n    expect(add(1, 2)).toBe(3);")
        rc, ents = self.r2({"tests/a.test.ts": bare}, {"tests/a.test.ts": bare.replace("expect(a);", "expect(b);")})
        self.assertEqual([e[4] for e in ents], ["assertion replaced in `Calc > adds`: `expect(a)` -> `expect(b)`"])
        rc, ents = self.r2({"tests/a.test.ts": bare}, {"tests/a.test.ts": TEST})
        self.assertEqual([e[4] for e in ents], ["assertions in test `Calc > adds` dropped from 2 to 1"])

    def test_a_curried_each_is_not_a_test_and_does_not_stop_the_scan(self):
        cur = "const run = it.each([[1]]);\n" + TEST
        rc, ents = self.r2({"tests/a.test.ts": cur}, {"tests/a.test.ts": cur.replace('it("adds"', 'it.skip("adds"')})
        self.assertEqual([e[4] for e in ents], ["test `Calc > adds` marked skipped (skip, todo or x-prefixed)"])

    def test_declarations_named_like_tests_at_any_spacing_and_position(self):
        decl = "function it(n, f) { f(); }\nfunction *test(x) { yield x; }\n"
        rc, ents = self.r2({"tests/a.test.ts": decl + TEST}, {"tests/a.test.ts": TEST})
        self.assertEqual((rc, ents), (0, []))
        odd = 'unction\nit("odd", () => { expect(1).toBe(1); });\n'
        rc, ents = self.r2({"tests/a.test.ts": odd}, {"tests/a.test.ts": odd.replace('it("odd"', 'it.skip("odd"')})
        self.assertEqual([e[4] for e in ents], ["test `odd` marked skipped (skip, todo or x-prefixed)"])

    def test_array_arguments_are_split_at_top_level_commas_only(self):
        arr = TEST.replace("expect(add(1, 2)).toBe(3);", "expect([1, 2]).toEqual([1, 2]);")
        rc, ents = self.r2({"tests/a.test.ts": arr}, {"tests/a.test.ts": arr.replace("toEqual([1, 2])", "toEqual([1, 3])")})
        self.assertEqual([e[4] for e in ents], ["expected value changed in `Calc > adds`: was [1,2], now [1,3]"])

    def test_every_literal_and_comment_edge_hides_the_calls_inside_it(self):
        noise = ('/it\\("r0"/.test(s);\n'
                 '/* a */ x(); /* it("c1", () => {}) */ const c2 = "it(\\"c2\\", () => {})";\n'
                 'const s1 = "a\\"b it(\\"x1\\", () => {})";\n'
                 'const s2 = "\\\\"; const s3 = \'it("x2", () => {})\';\n'
                 'const t1 = `plain`; const t0 = `it("x0", () => {})`;\n'
                 'const t2 = `a \\` it("x3", () => {})`;\n'
                 'const r1 = /[/]it\\("x4"/g, r2 = /a\\/it\\("x5"/i;\n'
                 'function f() { return /it\\("x6"/; }\n'
                 'const q = total / count / 2;\n'
                 "const j = <p>Don't</p>;\n")
        rc, ents = self.r2({"tests/a.test.ts": noise + TEST}, {"tests/a.test.ts": TEST + "foo"})
        self.assertEqual((rc, ents), (0, []))

    def test_a_test_name_keeps_its_escaped_quotes(self):
        q = TEST.replace('it("adds"', 'it("says \\"hi\\""')
        rc, ents = self.r2({"tests/a.test.ts": q}, {"tests/a.test.ts": q.replace("it(", "it.skip(")})
        self.assertEqual([e[4] for e in ents], ['test `Calc > says "hi"` marked skipped (skip, todo or x-prefixed)'])

    def test_a_declaration_word_must_stand_alone_and_unbroken(self):
        cases = ['xfunction it("t", () => { expect(1).toBe(1); });\n',
                 'func tion\nit("t", () => { expect(1).toBe(1); });\n']
        for src in cases:
            with self.subTest(src):
                rc, ents = self.r2({"tests/a.test.ts": src}, {"tests/a.test.ts": src.replace('it("t"', 'it.skip("t"')})
                self.assertEqual([e[4] for e in ents], ["test `t` marked skipped (skip, todo or x-prefixed)"])

    def test_a_dangling_member_access_does_not_end_the_scan(self):
        pre = "const a = it.\n  skip;\n"
        src = pre + 'it("b", () => { expect(1).toBe(1) });\n'
        rc, ents = self.r2({"tests/a.test.ts": src}, {"tests/a.test.ts": src.replace('it("b"', 'it.skip("b"')})
        self.assertEqual([e[4] for e in ents], ["test `b` marked skipped (skip, todo or x-prefixed)"])

    def test_an_arrow_body_ends_at_its_own_close_not_at_a_semicolon_inside_a_call(self):
        base = 'const h = (a) => X(a);\nit("t", () => { expect(1).toBe(1); h(1) });\n'
        head = 'const h = (a) => X(expect(a).toBe(1));\nit("t", () => { h(1) });\n'
        rc, ents = self.r2({"tests/a.test.ts": base}, {"tests/a.test.ts": head})
        self.assertEqual((rc, ents), (0, []))

    def test_an_escaped_backslash_ends_a_regex_literal(self):
        src = "const r = /\\\\/; const s = '/'; it(\"a\", () => { expect(1).toBe(1) });\n"
        rc, ents = self.r2({"tests/a.test.ts": src}, {"tests/a.test.ts": src.replace('it("a"', 'it.skip("a"')})
        self.assertEqual([e[4] for e in ents], ["test `a` marked skipped (skip, todo or x-prefixed)"])

    def test_a_test_named_by_a_variable_is_a_test(self):
        src = 'it(title, () => { expect(1).toBe(1); });\n'
        rc, ents = self.r2({"tests/a.test.ts": src}, {"tests/a.test.ts": src.replace("it(", "it.skip(")})
        self.assertEqual([e[4] for e in ents], ["test `title` marked skipped (skip, todo or x-prefixed)"])

    def test_an_expect_without_arguments_is_read(self):
        rc, ents = self.r2({"tests/a.test.ts": TEST + "expect();\n"}, {"tests/a.test.ts": TEST})
        self.assertEqual([e[4] for e in ents], ["assertions outside test fns in `tests/a.test.ts` dropped from 1 to 0"])

    def test_unparseable_hints_differ_by_where_the_stack_comes_from(self):
        base = self.commit({"tests/u.test.ts": TEST})
        head = self.commit({"tests/u.test.ts": TEST + "(\n"})
        got = []
        for extra in (["--adapter", TS_FILE], []):
            rc, out, err = run(["r2", "--repo", self.repo, "--base", base, "--head", head, "--stack", "ts",
                                "--test-paths", "tests/**", *extra])
            got.append([(e["check"], e["class"], e["hint"]) for e in json.loads(out)["entries"]])
        self.assertEqual(got, [
            [("R2", "needs-human", "fix the syntax error; if the file is valid, the adapter file's lexer table cannot "
                                   "read it: a person fixes the adapter file")],
            [("R2", "agent-fixable", "fix the syntax error: this file cannot be checked against base")]])

    # ---- suppression regions and texts ----
    def test_a_next_line_directive_does_not_reach_two_lines_down(self):
        base = "// eslint-disable-next-line no-x\nfoo();\nbar();\n"
        rc, ents = self.r2({"src/n.ts": base}, {"src/n.ts": base.replace("bar();", "bar(1);")})
        self.assertEqual(ents, [])

    def test_a_block_directive_covers_the_line_after_its_end(self):
        base = "/* eslint-disable-next-line no-x\n*/\nfoo();\nbar();\n"
        rc, ents = self.r2({"src/b.ts": base}, {"src/b.ts": base.replace("foo();", "foo(1);")})
        self.assertEqual([(e[3], e[4]) for e in ents], [(1, "`eslint-disable-next-line no-x` added without a reason")])
        rc, ents = self.r2({"src/b.ts": base}, {"src/b.ts": base.replace("bar();", "bar(1);")})
        self.assertEqual(ents, [])

    def test_a_suppression_counts_only_where_its_region_meets_an_added_line(self):
        cases = {  # base text, added line at the end, want problems
            "// eslint-disable-next-line no-x\nfoo();\nbar();\n": ("baz();\n", []),
            "const z = 1; // eslint-disable-line no-x\nbar();\n": ("baz();\n", []),
            "/* eslint-disable */\nbar();\n": ("baz();\n", ["`eslint-disable` added without a reason"]),
            "// @ts-nocheck\nbar();\n": ("baz();\n", ["`@ts-nocheck` added without a reason"]),
        }
        for base, (added, want) in cases.items():
            with self.subTest(base):
                rc, ents = self.r2({"src/s.ts": base}, {"src/s.ts": base + added})
                self.assertEqual([e[4] for e in ents], want)

    def test_suppression_hints_come_from_the_file(self):
        hints = {}
        for line in ("// eslint-disable-next-line no-console\n", "// @ts-ignore\n"):
            base = self.commit({"src/h.ts": "x();\n"})
            head = self.commit({"src/h.ts": line + "x();\n"})
            for extra in (["--adapter", TS_FILE], []):
                rc, out, err = run(["r2", "--repo", self.repo, "--base", base, "--head", head, "--stack", "ts",
                                    "--test-paths", "tests/**", *extra])
                hints.setdefault(line, []).append([e["hint"] for e in json.loads(out)["entries"]])
        self.assertEqual(hints, {
            "// eslint-disable-next-line no-console\n": [
                ["fix the lint, or give the suppression a reason after the rules: `// eslint-disable-next-line no-console -- why`"]] * 2,
            "// @ts-ignore\n": [["fix the type error, or give the directive a reason after it: `// @ts-ignore: why`"]] * 2})

    def test_a_ts_directive_reason_is_what_is_left_after_its_marks(self):
        rc, ents = self.r2({"src/r.ts": "x();\n"}, {"src/r.ts": "// @ts-ignore -:\nx();\n"})
        self.assertEqual((rc, ents), (0, []))

    def test_a_stryker_marker_already_on_base_is_not_reported_for_a_later_line(self):
        src = "// Stryker disable next-line all\nexport const f = (a: number) => a + 1;\n"
        rc, ents = self.r2({"src/a.ts": src}, {"src/a.ts": src + "export const g = 2;\n"})
        self.assertEqual((rc, ents), (0, []))

    # ---- mutation markers and config ----
    def test_stryker_markers_and_config_are_needs_human(self):
        src = "export const f = (a: number) => a + 1;\n"
        rc, ents = self.r2({"src/a.ts": src}, {"src/a.ts": "// Stryker disable next-line all\n" + src})
        self.assertEqual((rc, ents), (1, [("fail", "needs-human", "src/a.ts", 1,
                                           "mutation skip added: `Stryker disable next-line all` hides this code from R3")]))
        rc, ents = self.r2({"src/a.ts": src}, {"src/a.ts": "// Stryker disabled here\n" + src})
        self.assertEqual((rc, ents), (0, []))
        rc, ents = self.r2({"src/a.ts": src}, {".stryker.config.mjs": "export default {};\n"})
        self.assertEqual((rc, ents), (1, [("fail", "needs-human", ".stryker.config.mjs", 0,
                                           "mutation config changed: Stryker config in .stryker.config.mjs")]))
        rc, ents = self.r2({"src/a.ts": src}, {"stryker.config.yaml": "x: 1\n"})
        self.assertEqual((rc, ents), (0, []))


if __name__ == "__main__":
    unittest.main()
