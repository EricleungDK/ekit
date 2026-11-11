"""Python has no marker for a test: a function is one by its name and by the file it is in. Outside the test paths
only a file named like a test file holds tests, so `test_connection()` in src/app.py is production code."""
import os
import subprocess
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import engine
from scripts.mech_review.r2 import r2_file
from scripts.mech_review.stack import ADAPTERS

PY = ADAPTERS["python"]()
GLOBS = ["tests/**"]

PROD_BEFORE = """def testimonials():
    return ["great"]


def test_connection(host):
    assert host
    return host == "localhost"


def add(a, b):
    return a + b
"""
PROD_AFTER = """def add(a, b):
    return a + b
"""
TESTS_BEFORE = """def check(n):
    assert n > 0


def test_a():
    assert add(1, 2) == 3
    assert add(0, 0) == 0


def test_b():
    check(1)
"""


def problems(old, new, before, after):
    return [(e["severity"], e["problem"]) for e in r2_file(PY, GLOBS, old, new, before, after)]


class TestHoldsTests(unittest.TestCase):
    def test_a_test_paths_file_holds_tests_whatever_its_name(self):
        self.assertIs(PY.holds_tests("tests/helpers.py", GLOBS), True)

    def test_outside_the_test_paths_a_file_named_like_a_test_file_holds_tests(self):
        for path in ("src/pkg/test_utils.py", "src/pkg/utils_test.py", "app/tests.py", "test_x.py"):
            self.assertIs(PY.holds_tests(path, GLOBS), True, path)

    def test_any_other_file_does_not(self):
        for path in ("src/app.py", "src/testimonials.py", "src/latest.py", "src/test_dir/app.py", "src/tests.pyi.py"):
            self.assertIs(PY.holds_tests(path, GLOBS), False, path)

    def test_rust_and_ts_files_hold_tests_anywhere(self):
        self.assertIs(ADAPTERS["rust"]().holds_tests("src/lib.rs", GLOBS), True)
        self.assertIs(ADAPTERS["ts"]().holds_tests("src/app.ts", GLOBS), True)


class TestR2(unittest.TestCase):
    def test_a_production_function_named_test_is_not_a_removed_test(self):
        self.assertEqual(problems("src/app.py", "src/app.py", PROD_BEFORE, PROD_AFTER), [])

    def test_nor_is_one_added_in_a_new_production_file_a_skipped_test(self):
        added = "import pytest\n\n\n@pytest.mark.skip\ndef test_connection(host):\n    return host\n"
        self.assertEqual(problems(None, "src/app.py", None, added), [])

    def test_a_removed_test_in_a_test_paths_file_is_a_fail(self):
        after = TESTS_BEFORE.split("\n\ndef test_b")[0] + "\n"
        self.assertEqual(problems("tests/test_app.py", "tests/test_app.py", TESTS_BEFORE, after),
                         [("fail", "test fn `test_b` removed")])

    def test_an_untouched_test_paths_file_has_no_entry(self):
        self.assertEqual(problems("tests/test_app.py", "tests/test_app.py", TESTS_BEFORE, TESTS_BEFORE + "\nX = 1\n"), [])

    def test_a_helpers_assert_dropped_in_a_test_paths_file_is_a_fail(self):
        after = TESTS_BEFORE.replace("    assert n > 0\n", "    return n\n")
        self.assertEqual(problems("tests/test_app.py", "tests/test_app.py", TESTS_BEFORE, after),
                         [("fail", "assertions outside test fns in `tests/test_app.py` dropped from 1 to 0")])

    def test_a_changed_expected_value_is_a_confirm(self):
        after = TESTS_BEFORE.replace("add(1, 2) == 3", "add(1, 2) == 4")
        self.assertEqual(problems("tests/test_app.py", "tests/test_app.py", TESTS_BEFORE, after),
                         [("confirm", "expected value changed in `test_a`: was 3, now 4")])

    def test_a_test_named_file_outside_the_test_paths_is_still_guarded(self):
        after = TESTS_BEFORE.replace("    assert add(0, 0) == 0\n", "").split("\n\ndef test_b")[0] + "\n"
        self.assertEqual(problems("src/pkg/test_app.py", "src/pkg/test_app.py", TESTS_BEFORE, after),
                         [("fail", "test fn `test_b` removed"), ("fail", "assertions in test `test_a` dropped from 2 to 1")])

    def test_a_new_test_paths_file_with_a_skipped_test_is_a_fail(self):
        added = "import pytest\n\n\n@pytest.mark.skip\ndef test_later():\n    assert False\n"
        self.assertEqual(problems(None, "tests/test_new.py", None, added),
                         [("fail", "test `test_later` marked skipped (skip or xfail)")])

    def test_a_deleted_test_paths_file_loses_its_tests(self):
        self.assertEqual(problems("tests/test_app.py", None, TESTS_BEFORE, None),
                         [("fail", "test fn `test_a` removed"), ("fail", "test fn `test_b` removed"),
                          ("fail", "assertions outside test fns in `tests/test_app.py` dropped from 1 to 0")])

    def test_a_test_file_renamed_to_a_name_no_runner_collects_loses_its_tests(self):
        self.assertEqual(problems("src/pkg/test_app.py", "src/pkg/app_checks.py", TESTS_BEFORE, TESTS_BEFORE),
                         [("fail", "test fn `test_a` removed"), ("fail", "test fn `test_b` removed")])


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


class TestRedFirst(unittest.TestCase):
    """R1 and R4 on a PR that changes a production function named test_*, next to one real new test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        self.write("src/app.py", "def test_connection(host):\n    return host == 'localhost'\n\n\ndef add(a, b):\n    return a - b\n")
        self.write("tests/test_app.py", "from src.app import add\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n")
        self.write("docs/old.txt", "gone at head\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.write("src/app.py", "def test_connection(host):\n    return host in ('localhost', '::1')\n\n\n"
                                 "def add(a, b):\n    return a + b  # fixed\n")
        self.write("tests/test_app.py", "from src.app import add\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n\n\n"
                                        "def test_adds():\n    assert add(1, 2) == 3\n")
        self.write("tests/snippet.txt", "def test_in_a_text_file():\n    assert True\n")
        os.remove(os.path.join(self.repo, "docs", "old.txt"))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "fix")
        self.ran = []

    def write(self, path, text):
        os.makedirs(os.path.dirname(os.path.join(self.repo, path)), exist_ok=True)
        with open(os.path.join(self.repo, path), "w") as f:
            f.write(text)

    def pytest(self, argv, cwd):
        """What pytest prints for one named test: on the base's code add() is still wrong."""
        with open(os.path.join(cwd, "src", "app.py")) as f:
            fixed = "# fixed" in f.read()
        self.ran.append(argv[-1])
        return (0, "1 passed in 0.01s\n") if fixed else (1, "1 failed in 0.01s\n")

    def test_only_the_real_test_is_run_on_the_base_and_at_head(self):
        env = engine.run(self.repo, "HEAD~1", "HEAD", "python", GLOBS, which="red", head_branch="claude/fix",
                         runner=self.pytest)
        self.assertEqual(set(self.ran), {"tests/test_app.py::test_adds"})
        self.assertEqual(env["checks"]["R1"], {
            "status": "pass", "note": "1 of 1 new or changed test(s) fail on the base's production code"})
        self.assertEqual(env["checks"]["R4"], {"status": "pass", "note": "1 new or changed test(s) run 5x at head"})
        self.assertEqual(env["entries"], [])


if __name__ == "__main__":
    unittest.main()
