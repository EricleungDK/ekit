"""The eval tests find their case under the checkout as written (#24 follow-up of #23): R3's mutation run executes the
tests from a copy under <checkout>/mutants/ that holds evals/ too (mutants.also_copy copies every tracked top-level
entry), its scripts mutated. test_eval_scaffold.case_dir takes the outermost evals/<case> above the tests, so a
scaffold run under R3 reads the checkout's case, never the copy's."""
import os
import tempfile
import unittest

from test_eval_scaffold import case_dir


class CaseDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)

    def mk(self, *parts):
        path = os.path.join(self.root, *parts)
        os.makedirs(path)
        return path

    def test_the_checkouts_case_wins_over_the_mutated_copys(self):
        checkout = self.mk("evals", "x")
        self.mk("mutants", "evals", "x")
        self.assertEqual(case_dir("x", root=os.path.join(self.root, "mutants")), checkout)

    def test_a_case_only_the_copy_holds_is_still_found(self):
        copy = self.mk("mutants", "evals", "y")
        self.assertEqual(case_dir("y", root=os.path.join(self.root, "mutants")), copy)

    def test_the_checkout_alone_finds_its_own_case(self):
        own = self.mk("evals", "z")
        self.assertEqual(case_dir("z", root=self.root), own)


if __name__ == "__main__":
    unittest.main()
