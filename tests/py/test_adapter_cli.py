"""R2 through an adapter file (#16): `mech-review.py r2 --stack <name> --adapter <file>` on a fixture git repo.

The stack is a made-up language described only by tests/fixtures/adapters/mini.toml: no built-in adapter knows it."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import _kit

MR = os.path.join(_kit.SCRIPTS, "mech-review.py")
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
    argv = [sys.executable, "-I", MR, check, "--repo", repo.path, "--base", base, "--head", head, "--stack", stack,
            "--test-paths", "tests/**"]
    if adapter:
        argv += ["--adapter", adapter]
    return subprocess.run(argv + list(extra), capture_output=True, text=True)


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

    def test_without_tomllib_an_adapter_file_is_a_stated_error_and_built_ins_still_run(self):
        code = ("import sys; sys.modules['tomllib'] = None; sys.path.insert(0, sys.argv[1]); "
                "from mech_review.cli import main; sys.exit(main(sys.argv[2:]))")
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
