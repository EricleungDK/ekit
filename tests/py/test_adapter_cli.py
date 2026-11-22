"""R2 through an adapter file (#16): `mech-review.py r2 --stack <name> --adapter <file>` on a fixture git repo.

The stack is a made-up language described only by tests/fixtures/adapters/mini.toml: no built-in adapter knows it."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import _kit
from scripts.mech_review import cli

MINI = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.toml")

BASE = '''suite("Calc", {
  test("adds", {
    assertEquals(3, add(1, 2))
  })
  test("subtracts", {
    assertTrue(sub(3, 1) == 2)
  })
})
# test("ghost", { assertTrue(1) })
'''


class Repo:
    def __init__(self, tmp):
        self.path = tmp
        os.makedirs(tmp, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.path, "-c", "user.email=t@t", "-c", "user.name=t",
                               "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout

    def commit(self, files, msg):
        for rel, text in files.items():
            full = os.path.join(self.path, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", newline="\n") as f:
                f.write(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()




def r2(repo, base, head, *extra, adapter=MINI, stack="mini", check="r2"):
    """`mech-review.py <check> ...` through cli.main in this process (what the script runs), stdout and stderr captured.
    A usage error is argparse's SystemExit; its code is the exit code. Any other exception fails the test."""
    argv = [check, "--repo", repo.path, "--base", base, "--head", head, "--stack", stack, "--test-paths", "tests/**"]
    if adapter:
        argv += ["--adapter", adapter]
    return _kit.run_cli(argv + list(extra))


class AdapterFileR2(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(tmp.name)
        self.base = self.repo.commit({"tests/calc.mini": BASE, "src/calc.mini": "fn add(a, b) { a + b }\n"}, "base")

    def head(self, text, path="tests/calc.mini"):
        return self.repo.commit({path: text}, "head")

    def entries(self, head):
        r = r2(self.repo, self.base, head)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return r.returncode, json.loads(r.stdout)["entries"]

    def test_a_removed_test_is_a_fail_named_by_its_qualified_name(self):
        rc, ents = self.entries(self.head(BASE.replace('  test("subtracts", {\n    assertTrue(sub(3, 1) == 2)\n  })\n', "")))
        self.assertEqual(rc, 1)
        self.assertEqual([(e["check"], e["severity"], e["class"], e["file"], e["line"], e["problem"]) for e in ents],
                         [("R2", "fail", "agent-fixable", "tests/calc.mini", 5, "test fn `Calc / subtracts` removed")])

    def test_a_test_in_a_comment_is_not_a_test(self):
        rc, ents = self.entries(self.head(BASE.replace('# test("ghost", { assertTrue(1) })\n', "")))
        self.assertEqual((rc, ents), (0, []))

    def test_a_skip_marker_from_the_file_is_a_fail_with_the_files_wording(self):
        rc, ents = self.entries(self.head(BASE.replace('test("adds"', 'xtest("adds"')))
        self.assertEqual(rc, 1)
        self.assertEqual([(e["severity"], e["line"], e["problem"]) for e in ents],
                         [("fail", 2, "test `Calc / adds` marked xtest")])

    def test_a_changed_expected_value_in_a_call_shape_is_a_confirm(self):
        rc, ents = self.entries(self.head(BASE.replace("assertEquals(3,", "assertEquals(4,")))
        self.assertEqual(rc, 0)
        self.assertEqual([(e["severity"], e["line"], e["problem"]) for e in ents],
                         [("confirm", 3, "expected value changed in `Calc / adds`: was 3, now 4")])

    def test_a_dropped_assert_is_a_fail(self):
        rc, ents = self.entries(self.head(BASE.replace("    assertTrue(sub(3, 1) == 2)\n", "")))
        self.assertEqual(rc, 1)
        self.assertEqual([e["problem"] for e in ents], ["assertions in test `Calc / subtracts` dropped from 1 to 0"])

    def test_a_suppression_without_a_reason_is_a_fail_and_one_with_a_reason_is_not(self):
        rc, ents = self.entries(self.head("# lint-off unused\nfn add(a, b) { a + b }\n", "src/calc.mini"))
        self.assertEqual(rc, 1)
        self.assertEqual([(e["severity"], e["file"], e["line"], e["problem"]) for e in ents],
                         [("fail", "src/calc.mini", 1, "`lint-off unused` added without a reason")])
        rc, ents = self.entries(self.head("# lint-off unused -- kept for the plugin API\nfn add(a, b) { a + b }\n",
                                          "src/calc.mini"))
        self.assertEqual((rc, ents), (0, []))

    def test_a_file_that_does_not_balance_is_a_needs_human_fail(self):
        rc, ents = self.entries(self.head(BASE.replace("add(1, 2))", "add(1, 2)")))
        self.assertEqual(rc, 1)
        self.assertEqual([(e["severity"], e["class"], e["line"], e["problem"]) for e in ents],
                         [("fail", "needs-human", 4, "file does not parse: unexpected `}` (line 4)")])

    def test_files_of_other_stacks_are_not_read(self):
        rc, ents = self.entries(self.head("def broken(:\n", "tests/test_x.py"))
        self.assertEqual((rc, ents), (0, []))

    def test_a_replaced_other_assert_is_a_confirm_quoting_both_calls(self):
        rc, ents = self.entries(self.head(BASE.replace("assertTrue(sub(3, 1) == 2)", "assertTrue(sub(3, 1) > 0)")))
        self.assertEqual((rc, [(e["severity"], e["line"], e["problem"]) for e in ents]),
                         (0, [("confirm", 6, "assertion replaced in `Calc / subtracts`: `assertTrue(sub(3, 1) == 2)` -> "
                                             "`assertTrue(sub(3, 1) > 0)`")]))

    def test_a_changed_actual_operand_is_a_confirm_naming_it(self):
        rc, ents = self.entries(self.head(BASE.replace("add(1, 2))", "add(2, 1))")))
        self.assertEqual([(e["severity"], e["line"], e["problem"]) for e in ents],
                         [("confirm", 3, "expected value changed in `Calc / adds`: was add(1,2), now add(2,1)")])

    def test_an_unparseable_file_from_an_adapter_file_says_a_person_fixes_the_adapter(self):
        r = r2(self.repo, self.base, self.head(BASE.replace("add(1, 2))", "add(1, 2)")))
        self.assertEqual([(e["check"], e["id"].startswith("R2-"), e["hint"]) for e in json.loads(r.stdout)["entries"]],
                         [("R2", True, "fix the syntax error; if the file is valid, the adapter file's lexer table cannot "
                                       "read it: a person fixes the adapter file")])

    def test_a_modifier_the_file_does_not_list_is_neither_skip_nor_only(self):
        rc, ents = self.entries(self.head(BASE.replace("})\n# test", '  test.only("new", { assertTrue(1) })\n})\n# test')))
        self.assertEqual((rc, ents), (0, []))

    def test_a_replaced_call_is_quoted_up_to_its_closing_paren(self):
        semi = BASE.replace("assertTrue(sub(3, 1) == 2)", "assertTrue(a);")
        self.base = self.repo.commit({"tests/calc.mini": semi}, "semicolon")
        rc, ents = self.entries(self.head(semi.replace("assertTrue(a);", "assertTrue(b);")))
        self.assertEqual([e["problem"] for e in ents], ["assertion replaced in `Calc / subtracts`: `assertTrue(a)` -> `assertTrue(b)`"])

    def test_a_file_without_suppressions_reads_comments_as_comments_only(self):
        with open(MINI) as f:
            text = f.read().split("[[suppressions]]")[0]
        path = os.path.join(self.repo.path, "nosup.toml")  # committed with head: not a file of the stack
        with open(path, "w") as f:
            f.write(text)
        head = self.head("# lint-off unused\nfn add(a, b) { a + b }\n", "src/calc.mini")
        r = r2(self.repo, self.base, head, adapter=path)
        self.assertEqual((r.returncode, json.loads(r.stdout)["entries"]), (0, []), r.stderr)

    def test_an_eq_call_missing_an_operand_compares_by_text(self):
        one = BASE.replace("assertEquals(3, add(1, 2))", "assertEquals(3)")
        self.base = self.repo.commit({"tests/calc.mini": one}, "one operand")
        rc, ents = self.entries(self.head(one.replace("assertEquals(3)", "assertEquals(4)")))
        self.assertEqual([e["problem"] for e in ents],
                         ["assertion replaced in `Calc / adds`: `assertEquals(3)` -> `assertEquals(4)`"])


MINIMAL = '''format = 1
name = "tiny"
extensions = [".tiny"]

[lexer]
block_style = "braces"
brackets = ["()", "{}"]

[[lexer.strings]]
quote = '"'

[lexer.regex]
delimiter = "/"

[tests]
style = "calls"
cases = ["test"]

[[asserts.call]]
names = ["check"]
kind = "other"

[[asserts.chain]]
start = "expect"
eq = ["is"]
'''

# optional keys left out where their default is what a file means: groups without a separator, a skip without
# skipped_text, suppressions without lints/reason/problem keys beyond one, an ne call shape
DEFAULTS = '''format = 1
name = "dflt"
extensions = [".dflt"]

[lexer]
block_style = "braces"
brackets = ["()", "{}"]
line_comments = ["#"]

[[lexer.strings]]
quote = '"'

[[lexer.strings]]
quote = "'"
multiline = true

[tests]
style = "calls"
groups = ["suite"]
cases = ["test", "xtest"]
skip = ["xtest"]

[[asserts.call]]
names = ["assertNot"]
kind = "ne"
operands = [0, 1]

[[suppressions]]
directives = ["off", "off all"]
covers = { "off" = "next-line", "off all" = "file" }
problem = "bare {lints}"
'''


class OptionalKeysLeftOut(unittest.TestCase):
    """Each table with only its required keys (MINIMAL), or optional keys left at their default (DEFAULTS): the
    defaults (no comments, no groups, no escape, a regex literal only at the start of the file, `.` as member,
    ` > ` between names, the default skip and hint texts, no min_args) give a working R2."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = Repo(os.path.join(tmp.name, "repo"))

    def run_file(self, text, name, base_files, head_files):
        path = os.path.join(self.tmp, name + ".toml")
        with open(path, "w") as f:
            f.write(text)
        base = self.repo.commit(base_files, "base")
        head = self.repo.commit(head_files, "head")
        r = r2(self.repo, base, head, adapter=path, stack=name)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return r.returncode, json.loads(r.stdout)["entries"]

    def test_a_file_with_only_required_keys_reads_tests_strings_and_regexes(self):
        rc, ents = self.run_file(MINIMAL, "tiny",
                                 {"tests/a.tiny": '/test("r", {})/\ntest("a", { check(1) })\ns = "test(\\"q\\", {})"\n'
                                                  'x.test("m", { check(2) })\n'},
                                 {"tests/a.tiny": 's = "test(\\"q\\", {})"\n'})
        self.assertEqual(rc, 1)
        self.assertEqual([(e["severity"], e["line"], e["problem"]) for e in ents],
                         [("fail", 2, "test fn `a` removed"),
                          ("fail", 0, "assertions outside test fns in `tests/a.tiny` dropped from 1 to 0")])

    def test_a_chain_with_only_its_required_keys_and_a_test_with_no_arguments(self):
        rc, ents = self.run_file(MINIMAL, "tiny", {"tests/b.tiny": 'test("t", { expect(v).is(1) })\n'},
                                 {"tests/b.tiny": 'test("t", { expect(v).is(2) })\ntest()\n'})
        self.assertEqual([(e["severity"], e["line"], e["problem"]) for e in ents],
                         [("confirm", 1, "expected value changed in `t`: was 1, now 2")])

    def test_an_unterminated_multiline_string_without_a_name_is_named_string(self):
        rc, ents = self.run_file(DEFAULTS, "dflt", {"src/d.dflt": "f()\n"}, {"src/d.dflt": "f('open\n"})
        self.assertEqual([(e["class"], e["line"], e["problem"]) for e in ents],
                         [("needs-human", 1, "file does not parse: unterminated string (line 1)")])

    def test_a_test_with_no_arguments_has_an_empty_name(self):
        rc, ents = self.run_file(MINIMAL, "tiny", {"tests/e.tiny": 'test()\ntest("k", { check(1) })\n'},
                                 {"tests/e.tiny": 'test("k", { check(1) })\n'})
        self.assertEqual([(e["line"], e["problem"]) for e in ents], [(1, "test fn `` removed")])

    def test_default_separator_skip_text_hint_and_an_ne_call(self):
        base = 'suite("S", {\n  test("t", { assertNot(1, f()) })\n})\n'
        rc, ents = self.run_file(DEFAULTS, "dflt", {"tests/c.dflt": base, "src/c.dflt": "f()\n"},
                                 {"tests/c.dflt": base.replace('test("t"', 'xtest("t"').replace("assertNot(1,", "assertNot(2,"),
                                  "src/c.dflt": "# off all\nf()\n# off\ng()\n"})
        self.assertEqual([(e["severity"], e["file"], e["line"], e["problem"], e["hint"]) for e in ents], [
            ("fail", "src/c.dflt", 1, "bare off all", "fix the lint, or give the suppression a reason"),
            ("fail", "src/c.dflt", 3, "bare off", "fix the lint, or give the suppression a reason"),
            ("confirm", "tests/c.dflt", 2, "expected value changed in `S > t`: was 1, now 2",
             "confirm the new value is the spec'd behaviour, not the buggy output"),
            ("fail", "tests/c.dflt", 2, "test `S > t` marked skipped",
             "make it pass or fix the code it covers; do not mark it ignored")])


class AdapterFileUsage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = Repo(os.path.join(tmp.name, "repo"))
        self.base = self.repo.commit({"tests/a.mini": BASE}, "base")

    def write(self, text):
        path = os.path.join(self.tmp, "bad.toml")
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_a_file_missing_a_field_is_a_usage_error_naming_the_field(self):
        with open(MINI) as f:
            text = f.read().replace('name = "mini"\n', "")
        r = r2(self.repo, self.base, self.base, adapter=self.write(text))
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("name: missing", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_template_with_a_format_spec_is_a_usage_error_at_load(self):
        with open(MINI) as f:
            text = f.read().replace('reason_after = "--"\n', 'reason_after = "--"\nproblem = "{lints:{lints}<5}"\n')
        r = r2(self.repo, self.base, self.base, adapter=self.write(text))
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("suppressions[0].problem: `{lints:{lints}<5}`: want plain `{lints}`", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_bad_target_os_is_a_usage_error_naming_the_field(self):
        with open(MINI) as f:
            text = f.read().replace('name = "mini"\n', 'name = "mini"\ntarget-os = "beos"\n')
        r = r2(self.repo, self.base, self.base, adapter=self.write(text))
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("bad.toml: target-os: `beos`: want linux, macos or windows\n", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_file_named_auto_is_a_usage_error_naming_the_field(self):
        with open(MINI) as f:
            text = f.read().replace('name = "mini"\n', 'name = "auto"\n')
        r = r2(self.repo, self.base, self.base, adapter=self.write(text), stack="auto")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("bad.toml: name: `auto` is reserved", r.stderr)

    def test_a_file_that_is_not_toml_is_a_usage_error(self):
        r = r2(self.repo, self.base, self.base, adapter=self.write("name = [\n"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("not valid TOML", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_file_that_is_not_utf8_is_a_usage_error_not_a_traceback(self):
        path = os.path.join(self.tmp, "latin1.toml")
        with open(path, "wb") as f:
            f.write(b'name = "caf\xe9"\n')
        r = r2(self.repo, self.base, self.base, adapter=path)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("not valid TOML", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_deeply_nested_file_is_a_usage_error_not_a_traceback(self):
        r = r2(self.repo, self.base, self.base, adapter=self.write("x = " + "[" * 3000 + "]" * 3000 + "\n"))
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("not valid TOML", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_missing_file_is_a_usage_error(self):
        r = r2(self.repo, self.base, self.base, adapter=os.path.join(self.tmp, "none.toml"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot read", r.stderr)
        self.assertIn("none.toml: cannot read: No such file or directory\n", r.stderr)

    def test_the_stack_name_must_match_the_files_name(self):
        r = r2(self.repo, self.base, self.base, stack="ts")
        self.assertEqual(r.returncode, 2)
        self.assertIn("describes stack `mini`, not `ts`", r.stderr)

    def test_an_unknown_stack_without_an_adapter_file_is_still_a_usage_error(self):
        r = r2(self.repo, self.base, self.base, adapter=None)
        self.assertEqual(r.returncode, 2)
        self.assertIn("invalid choice: 'mini'", r.stderr)

    def test_the_adapter_file_drives_r2_only(self):
        r = r2(self.repo, self.base, self.base, check="red")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--adapter applies to r2 only", r.stderr)

    def test_usage_errors_name_the_choices_and_what_is_not_built(self):
        r = r2(self.repo, self.base, self.base, adapter=None)
        self.assertIn("error: argument --stack: invalid choice: 'mini' (choose from 'python', 'rust', 'ts')\n", r.stderr)
        r = r2(self.repo, self.base, self.base, check="mutants")
        self.assertIn("error: --adapter applies to r2 only (the run side of an adapter file: R1, R3, R4 is not built yet)\n",
                      r.stderr)

    def test_stack_is_still_required(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as e:
                cli.main(["r2", "--repo", self.repo.path, "--base", self.base, "--head", self.base, "--adapter", MINI])
        self.assertEqual(e.exception.code, 2)
        self.assertIn("the following arguments are required: --stack", err.getvalue())

    def test_without_tomllib_an_adapter_file_is_a_stated_error_and_built_ins_still_run(self):
        # a python without tomllib, as the engine sees it: only imports made by mech_review fail. Hiding it from the
        # whole process would also break other importers (mutmut's trampoline reads its config with tomllib).
        code = ("import builtins, sys\n"
                "real = builtins.__import__\n"
                "def imp(name, globals=None, *a, **k):\n"
                "    if name == 'tomllib' and (globals or {}).get('__name__', '').startswith('mech_review'):\n"
                "        raise ImportError('No module named tomllib')\n"
                "    return real(name, globals, *a, **k)\n"
                "builtins.__import__ = imp\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "from mech_review.cli import main\n"
                "sys.exit(main(sys.argv[2:]))\n")
        common = ["r2", "--repo", self.repo.path, "--base", self.base, "--head", self.base, "--test-paths", "tests/**"]
        r = subprocess.run([sys.executable, "-I", "-c", code, _kit.SCRIPTS, *common, "--stack", "mini", "--adapter", MINI],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs python 3.11 or newer (tomllib)", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        r = subprocess.run([sys.executable, "-I", "-c", code, _kit.SCRIPTS, *common, "--stack", "ts"],
                           capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stderr), (0, ""))


if __name__ == "__main__":
    unittest.main()
