import os
import subprocess
import tempfile
import time
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts import scenarios


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                       capture_output=True, text=True)
    return r.stdout.strip()


def write(repo, name, text):
    with open(os.path.join(repo, name), "w") as f:
        f.write(text)


class TestTreeHash(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        git(self.repo, "init", "-q")
        write(self.repo, "a.txt", "one\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")

    def tearDown(self):
        self.tmp.cleanup()

    def hash(self):
        return scenarios.tree_hash(self.repo)

    def test_a_clean_tree_hashes_to_heads_tree(self):
        self.assertEqual(self.hash(), git(self.repo, "rev-parse", "HEAD^{tree}"))

    def test_committing_the_same_files_keeps_the_hash(self):
        write(self.repo, "a.txt", "two\n")
        write(self.repo, "new.txt", "n\n")
        dirty = self.hash()
        git(self.repo, "add", "-A")
        self.assertEqual(self.hash(), dirty)
        git(self.repo, "commit", "-q", "-m", "work")
        self.assertEqual(self.hash(), dirty)
        self.assertEqual(dirty, git(self.repo, "rev-parse", "HEAD^{tree}"))

    def test_a_tracked_edit_and_an_untracked_file_each_change_the_hash(self):
        clean = self.hash()
        write(self.repo, "a.txt", "two\n")
        edited = self.hash()
        self.assertNotEqual(edited, clean)
        write(self.repo, "new.txt", "n\n")
        self.assertNotEqual(self.hash(), edited)

    def test_an_ignored_file_does_not_count(self):
        write(self.repo, ".gitignore", "*.log\n")
        before = self.hash()
        write(self.repo, "debug.log", "noise\n")
        self.assertEqual(self.hash(), before)

    def test_hashing_writes_nothing_into_the_repo(self):
        write(self.repo, "new.txt", "n\n")
        before = (git(self.repo, "count-objects", "-v"), git(self.repo, "status", "--porcelain"))
        self.hash()
        self.assertEqual((git(self.repo, "count-objects", "-v"), git(self.repo, "status", "--porcelain")), before)

    def test_a_file_that_is_not_utf8_is_hashed(self):
        with open(os.path.join(self.repo, "latin.txt"), "wb") as f:
            f.write(b"caf\xe9\n")
        one = self.hash()
        with open(os.path.join(self.repo, "latin.txt"), "wb") as f:
            f.write(b"caf\xe9 two\n")
        self.assertRegex(one, r"^[0-9a-f]{40}$")
        self.assertNotEqual(self.hash(), one)

    def test_a_fresh_repo_with_no_commit_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            write(d, "f", "x\n")
            self.assertRegex(scenarios.tree_hash(d), r"^[0-9a-f]{40}$")

    def test_outside_a_git_repo_the_hash_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(scenarios.tree_hash(d), "")

    def test_repo_state_is_head_and_the_tree_hash(self):
        self.assertEqual(scenarios.repo_state(self.repo), (git(self.repo, "rev-parse", "HEAD"), self.hash()))

    def test_an_empty_commit_changes_the_repo_state_but_not_the_hash(self):
        before = scenarios.repo_state(self.repo)
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "by a scenario")
        after = scenarios.repo_state(self.repo)
        self.assertEqual(after[1], before[1])
        self.assertNotEqual(after[0], before[0])


class TestPrune(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, age_days, is_dir=True):
        p = os.path.join(self.out, name)
        if is_dir:
            os.mkdir(p)
        else:
            open(p, "w").close()
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
        return p

    def test_old_transcript_dirs_of_other_trees_go(self):
        old, kept = self.make("aaa", scenarios.KEEP_DAYS + 1), self.make("bbb", scenarios.KEEP_DAYS - 1)
        scenarios.prune(self.out, "ccc")
        self.assertEqual((os.path.exists(old), os.path.exists(kept)), (False, True))

    def test_the_current_trees_dir_stays_however_old(self):
        cur = self.make("ccc", scenarios.KEEP_DAYS * 3)
        scenarios.prune(self.out, "ccc")
        self.assertTrue(os.path.isdir(cur))

    def test_files_are_never_removed(self):
        results = self.make("results.json", scenarios.KEEP_DAYS * 3, is_dir=False)
        scenarios.prune(self.out, "ccc")
        self.assertTrue(os.path.isfile(results))


if __name__ == "__main__":
    unittest.main()
