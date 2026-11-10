"""R3 for python end to end, with mutmut replaced by a scripted runner: which mutants it is asked to show."""
import contextlib
import io
import os
import subprocess
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants
from scripts.mech_review.gitio import Review, merge_base
from scripts.mech_review.stack import ADAPTERS

BASE = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
HEAD = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    c = a - b\n    return c\n"
SHOW = {
    "calc.x_sub__mutmut_1": "--- calc.py\n+++ calc.py\n@@ -1,3 +1,3 @@\n def sub(a, b):\n-    c = a - b\n+    c = a + b\n     return c\n",
}


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


class TestMutmutCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        for name, text in (("pyproject.toml", "[project]\nname = 'calc'\n"), ("calc.py", BASE)):
            with open(os.path.join(self.repo, name), "w") as f:
                f.write(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        with open(os.path.join(self.repo, "calc.py"), "w") as f:
            f.write(HEAD)
        git(self.repo, "commit", "-q", "-am", "head")
        self.shown = []

    def runner(self, results, run_result=(0, "done")):
        def run(argv, cwd, timeout):
            verb = argv[1]
            if verb == "--version":
                return 0, "mutmut, version 3.8.1"
            if verb == "run":
                return run_result
            if verb == "results":
                return 0, "".join(f"    {name}: {status}\n" for name, status in results)
            self.shown.append(argv[2])
            return 0, SHOW[argv[2]]
        return run

    def r3(self, results, **kw):
        base, head, mb = merge_base(self.repo, "HEAD~1", "HEAD")
        rv = Review(self.repo, mb, head, ADAPTERS["python"](), ["tests/**"], ".")
        return mutants.run(rv, None, 5, None, None, self.runner(results, **kw))

    def test_tests_that_fail_before_any_mutant_runs_are_named_in_the_job_log(self):
        output = ("\u280b Running stats\r\u2819 Running stats\n....F\n"
                  "FAILED tests/test_calc.py::test_sub - AssertionError: 3 != 2\n\n"
                  "failed to collect stats. runner returned 1\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            check, entries = self.r3([], run_result=(1, output))
        self.assertEqual((check["status"], check["note"]), ("fail", "baseline tests fail at head: mutants not run"))
        self.assertEqual([e["problem"] for e in entries], ["baseline tests fail at head: mutants not run"])
        self.assertEqual(err.getvalue(), "mech-review: R3 fail: last 3 lines of mutmut output\n....F\n"
                                         "FAILED tests/test_calc.py::test_sub - AssertionError: 3 != 2\n"
                                         "failed to collect stats. runner returned 1\n")
        self.assertEqual(self.shown, [])

    def test_a_missed_mutant_in_an_untouched_function_is_outside_and_never_shown(self):
        check, entries = self.r3([("calc.x_add__mutmut_1", "survived"), ("calc.x_add__mutmut_2", "no tests"),
                                  ("calc.x_sub__mutmut_1", "survived"), ("calc.x_sub__mutmut_2", "killed")])
        self.assertEqual(self.shown, ["calc.x_sub__mutmut_1"])
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["note"], "4/4 tested: 1 missed in the diff, 2 missed outside the diff, 0 unlocated, 1 caught")
        self.assertEqual([(e["file"], e["line"], e["severity"]) for e in entries], [("calc.py", 6, "fail")])
        self.assertEqual(entries[0]["problem"], "MISSED mutant calc.py:6: c = a - b -> c = a + b")

    def test_only_untouched_functions_missed_is_a_pass_with_no_lookup(self):
        check, entries = self.r3([("calc.x_add__mutmut_1", "survived"), ("calc.x_sub__mutmut_2", "killed")])
        self.assertEqual((check["status"], entries, self.shown), ("pass", [], []))
        self.assertEqual(check["note"], "2/2 tested: 0 missed in the diff, 1 missed outside the diff, 0 unlocated, 1 caught")


class TestDiagOutput(unittest.TestCase):
    def diag(self, text):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mutants.diag_output("mutmut", "fail", text)
        return err.getvalue().splitlines()

    def test_only_the_last_lines_are_printed(self):
        lines = self.diag("\n".join(f"line {i}" for i in range(mutants.DIAG_LINES + 5)))
        self.assertEqual(lines[0], f"mech-review: R3 fail: last {mutants.DIAG_LINES} lines of mutmut output")
        self.assertEqual((lines[1], lines[-1], len(lines)), ("line 5", f"line {mutants.DIAG_LINES + 4}", mutants.DIAG_LINES + 1))

    def test_no_output_is_a_header_with_zero_lines(self):
        self.assertEqual(self.diag(None), ["mech-review: R3 fail: last 0 lines of mutmut output"])
        self.assertEqual(self.diag("  \n\u2807 Generating mutants\n"), ["mech-review: R3 fail: last 0 lines of mutmut output"])

    def test_every_spinner_frame_from_first_to_last_is_dropped(self):
        self.assertEqual(self.diag("\u2800 first frame\n\u28ff last frame\nkept\n")[1:], ["kept"])
        self.assertEqual(self.diag("\u27ff below the frames\n\u2900 above the frames\n")[1:],
                         ["\u27ff below the frames", "\u2900 above the frames"])

    def test_text_after_a_carriage_return_is_a_line_of_its_own(self):
        self.assertEqual(self.diag("\u280b Running stats\rFAILED tests/test_calc.py::test_sub\n")[1:],
                         ["FAILED tests/test_calc.py::test_sub"])

    def test_a_line_that_merely_contains_a_spinner_frame_is_kept(self):
        self.assertEqual(self.diag("done \u280b\n")[1], "done \u280b")


if __name__ == "__main__":
    unittest.main()
