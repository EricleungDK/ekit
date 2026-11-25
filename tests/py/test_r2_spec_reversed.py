"""R2: a test removed because the spec reverses it (#53). A commit body line `spec: #N reverses <test name>` in
merge-base..head, with N among the PR's `--linked-issue`s, turns the removed test's `fail` into one `confirm` for the
reviewer; any other removal stays the `fail`. Through `cli.main(["r2", ...])` on a fixture repo (python stack)."""
import json
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from test_adapter_cli import BASE as MINI_BASE, MINI, Repo, r2

BASE = '''import unittest

import calc


class T(unittest.TestCase):
    def test_refund_never_negative(self):
        self.assertEqual(calc.refund(-5), 0)

    def test_adds(self):
        self.assertEqual(calc.add(1, 2), 3)
'''
HEAD = BASE.replace('''    def test_refund_never_negative(self):
        self.assertEqual(calc.refund(-5), 0)

''', "")
NAME = "T::test_refund_never_negative"


class SpecReversed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(tmp.name)
        self.base = self.repo.commit({"tests/test_calc.py": BASE, "calc.py": "def add(a, b):\n    return a + b\n"},
                                     "base")

    def entries(self, msg, *extra, check="r2", text=HEAD):
        head = self.repo.commit({"tests/test_calc.py": text}, msg)
        r = r2(self.repo, self.base, head, *extra, adapter=None, stack="python", check=check)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        got = json.loads(r.stdout)
        return r.returncode, [e for e in got["entries"] if e["check"] == "R2"], got

    def assertConfirm(self, rc, ents, n="53"):
        self.assertEqual(rc, 0)
        self.assertEqual([(e["severity"], e["class"], e["file"], e["line"], e["problem"]) for e in ents],
                         [("confirm", "agent-fixable", "tests/test_calc.py", 7,
                           f"test `{NAME}` removed, spec #{n} reverses it")])
        self.assertIn(f"quoted sentence of #{n}", ents[0]["hint"])
        self.assertIn("restore the test", ents[0]["hint"])

    def assertFail(self, rc, ents):
        self.assertEqual(rc, 1)
        self.assertEqual([(e["severity"], e["class"], e["line"], e["problem"]) for e in ents],
                         [("fail", "agent-fixable", 7, f"test fn `{NAME}` removed")])

    def test_a_one_line_test_the_linked_spec_reverses_is_one_confirm(self):
        rc, ents, _ = self.entries(f"drop it\n\nspec: #53 reverses {NAME}\n", "--linked-issue", "53")
        self.assertConfirm(rc, ents)

    def test_all_reads_the_spec_line_as_r2_does(self):
        rc, ents, got = self.entries(f"drop it\n\nspec: #53 reverses {NAME}\n", "--linked-issue", "#53", check="all")
        self.assertEqual([(e["severity"], e["problem"]) for e in ents],
                         [("confirm", f"test `{NAME}` removed, spec #53 reverses it")])

    def test_the_spec_line_may_be_in_any_commit_of_the_range(self):
        self.repo.commit({"calc.py": "def add(a, b):\n    return a + b\n# x\n"}, f"why\n\nspec: #9 reverses {NAME}\n")
        rc, ents, _ = self.entries("drop it", "--linked-issue", "53", "--linked-issue", "9")
        self.assertConfirm(rc, ents, n="9")

    def test_no_spec_line_stays_the_fail(self):
        self.assertFail(*self.entries("drop it", "--linked-issue", "53")[:2])

    def test_a_spec_line_naming_an_unlinked_issue_stays_the_fail(self):
        self.assertFail(*self.entries(f"drop it\n\nspec: #54 reverses {NAME}\n", "--linked-issue", "53")[:2])

    def test_a_spec_line_naming_another_test_stays_the_fail(self):
        self.assertFail(*self.entries("drop it\n\nspec: #53 reverses T::test_adds\n", "--linked-issue", "53")[:2])

    def test_a_spec_line_naming_a_longer_name_stays_the_fail(self):
        self.assertFail(*self.entries(f"drop it\n\nspec: #53 reverses {NAME}_x\n", "--linked-issue", "53")[:2])

    def test_a_spec_line_without_linked_issues_stays_the_fail(self):
        self.assertFail(*self.entries(f"drop it\n\nspec: #53 reverses {NAME}\n")[:2])

    def test_linked_issue_is_a_usage_error_on_a_subcommand_without_r2(self):
        head = self.repo.commit({"tests/test_calc.py": HEAD}, "drop it")
        r = r2(self.repo, self.base, head, "--linked-issue", "53", adapter=None, stack="python", check="red")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--linked-issue applies to r2 and all", r.stderr)

    def test_linked_issue_wants_a_number(self):
        r = r2(self.repo, self.base, self.base, "--linked-issue", "abc", adapter=None, stack="python")
        self.assertEqual(r.returncode, 2)
        self.assertIn("want an issue number", r.stderr)


class SpecReversedRepoAdapter(unittest.TestCase):
    """`all` on a stack the repo's own adapter file describes (R2 through the file, R1 and R4 n/a), and a test name with
    spaces in it (the mini stack's `Calc / subtracts`)."""

    def test_all_through_the_repos_adapter_file_reads_the_spec_line(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Repo(tmp.name)
        with open(MINI) as f:
            toml = f.read()
        base = repo.commit({".ekit/adapters/mini.toml": toml, "tests/calc.mini": MINI_BASE}, "base")
        head = repo.commit({"tests/calc.mini": MINI_BASE.replace(
            '  test("subtracts", {\n    assertTrue(sub(3, 1) == 2)\n  })\n', "")},
            "drop it\n\nspec: #53 reverses Calc / subtracts\n")
        r = r2(repo, base, head, "--linked-issue", "53", adapter=None, check="all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([(e["check"], e["severity"], e["line"], e["problem"]) for e in json.loads(r.stdout)["entries"]],
                         [("R2", "confirm", 5, "test `Calc / subtracts` removed, spec #53 reverses it")])
