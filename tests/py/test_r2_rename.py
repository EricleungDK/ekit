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

    def test_an_unrelated_test_in_place_of_a_removed_one_stays_a_fail(self):
        rc, got = self.entries(UNRELATED)
        self.assertEqual(rc, 1)
        self.assertEqual(got, [("fail", "test fn `T::test_the_budget_gone_keeps_every_mutant_missed` removed")])


if __name__ == "__main__":
    unittest.main()
