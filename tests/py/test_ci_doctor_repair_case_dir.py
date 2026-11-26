"""The eval tests find their case in the checkout the test file belongs to (#24 follow-up of #23). Two places hold a
second copy of evals/: R3's mutation run executes the tests from <checkout>/mutants/ (mutants.also_copy copies every
tracked top-level entry, evals/ too; its scripts mutated), and a git worktree may sit inside another checkout (Claude
Code's default: <repo>/.claude/worktrees/<name>). test_eval_scaffold.case_dir takes the evals/<case> at the top of the
git checkout that holds the tests: the worktree's own case, and from R3's copy (a plain dir inside the checkout) the
checkout's, never the copy's. The setup eval tests use the same lookup."""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import test_ci_doctor_setup_evals
from test_eval_scaffold import case_dir


def git(at, *args):
    subprocess.run(["git", "-C", at, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                   check=True, capture_output=True)


class CaseDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.join(os.path.realpath(tmp.name), "checkout")
        os.makedirs(os.path.join(self.root, "evals", "x"))
        with open(os.path.join(self.root, "evals", "x", "setup.sh"), "w") as f:
            f.write("exit 0\n")
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "c")

    def test_r3s_mutated_copy_reads_the_checkouts_case(self):
        os.makedirs(os.path.join(self.root, "mutants", "evals", "x"))
        os.makedirs(os.path.join(self.root, "mutants", "tests", "py"))
        self.assertEqual(case_dir("x", root=os.path.join(self.root, "mutants", "tests", "py")),
                         os.path.join(self.root, "evals", "x"))

    def test_a_worktree_inside_another_checkout_reads_its_own_case(self):
        tree = os.path.join(self.root, ".claude", "worktrees", "w")
        git(self.root, "worktree", "add", "-q", tree)
        with open(os.path.join(tree, "evals", "x", "setup.sh"), "w") as f:
            f.write("exit 7\n")  # the worktree's own edit: its tests must run it, not the outer checkout's
        self.assertEqual(case_dir("x", root=os.path.join(tree, "tests", "py")), os.path.join(tree, "evals", "x"))
        os.makedirs(os.path.join(tree, "mutants", "tests", "py"))  # R3 run from that worktree
        self.assertEqual(case_dir("x", root=os.path.join(tree, "mutants", "tests", "py")),
                         os.path.join(tree, "evals", "x"))

    def test_a_git_dir_in_the_environment_is_not_read(self):
        """review round 2 [case_dir GIT_DIR]: a git hook exports GIT_DIR, which makes --show-toplevel answer the cwd"""
        os.makedirs(os.path.join(self.root, "mutants", "evals", "x"))
        os.makedirs(os.path.join(self.root, "mutants", "tests", "py"))
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(self.root, ".git")}):
            self.assertEqual(case_dir("x", root=os.path.join(self.root, "mutants", "tests", "py")),
                             os.path.join(self.root, "evals", "x"))

    def test_the_checkout_finds_its_own_case(self):
        self.assertEqual(case_dir("x", root=os.path.join(self.root, "tests", "py")),
                         os.path.join(self.root, "evals", "x"))

    def test_outside_git_the_nearest_case_above(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bare = os.path.realpath(tmp.name)
        os.makedirs(os.path.join(bare, "evals", "y"))
        os.makedirs(os.path.join(bare, "tests", "py"))
        self.assertEqual(case_dir("y", root=os.path.join(bare, "tests", "py")), os.path.join(bare, "evals", "y"))

    def test_the_setup_eval_tests_use_the_same_lookup(self):
        self.assertIs(test_ci_doctor_setup_evals.case_dir, case_dir)


if __name__ == "__main__":
    unittest.main()
