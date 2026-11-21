"""R2: a test renamed with its body mostly kept but its assertions changed (#41) is one `confirm` entry for the reviewer,
not a `fail` for a removed test; through `cli.main(["r2", ...])` on a fixture repo (python stack)."""
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from test_adapter_cli import Repo, r2

BASE = '''import unittest

import calc


class T(unittest.TestCase):
    def test_the_budget_gone_keeps_every_mutant_missed(self):
        fake = calc.fake({"a": "survived", "b": "survived"})
        with calc.clock(100, 130, 140):
            check = calc.run(fake, budget=2)
        self.assertEqual(check["status"], "fail")
        self.assertIn("2 missed", check["note"])

    def test_adds(self):
        self.assertEqual(calc.add(1, 2), 3)
'''

RENAMED = BASE.replace("def test_the_budget_gone_keeps_every_mutant_missed", "def test_the_budget_gone_leaves_every_mutant_untested") \
              .replace('self.assertEqual(check["status"], "fail")', 'self.assertEqual(check["status"], "partial")') \
              .replace('self.assertIn("2 missed", check["note"])', 'self.assertIn("2 untested", check["note"])')

UNRELATED = BASE.replace('''    def test_the_budget_gone_keeps_every_mutant_missed(self):
        fake = calc.fake({"a": "survived", "b": "survived"})
        with calc.clock(100, 130, 140):
            check = calc.run(fake, budget=2)
        self.assertEqual(check["status"], "fail")
        self.assertIn("2 missed", check["note"])
''', '''    def test_subtracts(self):
        self.assertEqual(calc.sub(3, 1), 2)
''')


DROPPED = RENAMED.replace('        self.assertIn("2 untested", check["note"])\n', "")


BLACK_BASE = """import refunds


def test_refund_is_never_negative(
    tmp_path,
):
    assert refunds.refund(tmp_path, -5) == 0
    assert refunds.refund(tmp_path, 0) == 0
    assert refunds.refund(tmp_path, 3) == 3
"""

BLACK_HEAD = """import refunds


def test_something_else(
    tmp_path,
):
    assert True
    assert 1
    assert 2
"""

NO_ASSERT_BASE = """import calc


def test_runs_without_error():
    fake = calc.fake({"a": "survived"})
    with calc.clock(100, 130):
        calc.run(fake, budget=2)
"""

NO_ASSERT_HEAD = NO_ASSERT_BASE.replace("test_runs_without_error", "test_runs_quietly")


class R2Rename(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(os.path.join(self.tmp.name, "r"))
        self.base = self.repo.commit({"pyproject.toml": "[project]\nname = 'x'\n", "calc.py": "def add(a, b):\n    return a + b\n",
                                      "tests/test_calc.py": BASE}, "base")

    def tearDown(self):
        self.tmp.cleanup()

    def entries(self, text):
        head = self.repo.commit({"tests/test_calc.py": text}, "head")
        res = r2(self.repo, self.base, head, adapter=None, stack="python")
        return res.returncode, [(e["severity"], e["problem"]) for e in json.loads(res.stdout)["entries"]]

    def test_a_rename_whose_assertions_changed_is_one_confirm_entry(self):
        self.assertEqual(self.entries(RENAMED), (0, [
            ("confirm", "test `T::test_the_budget_gone_keeps_every_mutant_missed` renamed to "
                        "`T::test_the_budget_gone_leaves_every_mutant_untested`, assertions changed")]))

    def test_a_rename_that_drops_an_assertion_stays_a_fail(self):
        rc, got = self.entries(DROPPED)
        self.assertEqual(rc, 1)
        self.assertEqual(got, [("fail", "test fn `T::test_the_budget_gone_keeps_every_mutant_missed` removed")])

    def test_two_tests_sharing_only_a_multi_line_signature_are_no_rename(self):
        self.repo.commit({"tests/test_refunds.py": BLACK_BASE}, "black base")
        self.base = self.repo.git("rev-parse", "HEAD").strip()
        head = self.repo.commit({"tests/test_refunds.py": BLACK_HEAD}, "head")
        res = r2(self.repo, self.base, head, adapter=None, stack="python")
        self.assertEqual(res.returncode, 1)
        self.assertEqual([(e["severity"], e["problem"]) for e in json.loads(res.stdout)["entries"]],
                         [("fail", "test fn `test_refund_is_never_negative` removed")])

    def test_a_removed_test_with_no_assertion_is_no_rename_whose_assertions_changed(self):
        self.repo.commit({"tests/test_quiet.py": NO_ASSERT_BASE}, "quiet base")
        self.base = self.repo.git("rev-parse", "HEAD").strip()
        head = self.repo.commit({"tests/test_quiet.py": NO_ASSERT_HEAD}, "head")
        res = r2(self.repo, self.base, head, adapter=None, stack="python")
        self.assertEqual(res.returncode, 1)
        self.assertEqual([(e["severity"], e["problem"]) for e in json.loads(res.stdout)["entries"]],
                         [("fail", "test fn `test_runs_without_error` removed")])

    def test_an_unrelated_test_in_place_of_a_removed_one_stays_a_fail(self):
        rc, got = self.entries(UNRELATED)
        self.assertEqual(rc, 1)
        self.assertEqual(got, [("fail", "test fn `T::test_the_budget_gone_keeps_every_mutant_missed` removed")])


if __name__ == "__main__":
    unittest.main()
