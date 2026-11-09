"""R3 for python end to end, with mutmut replaced by a scripted runner: which mutants it is asked to show."""
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

    def runner(self, results):
        def run(argv, cwd, timeout):
            verb = argv[1]
            if verb == "--version":
                return 0, "mutmut, version 3.8.1"
            if verb == "run":
                return 0, "done"
            if verb == "results":
                return 0, "".join(f"    {name}: {status}\n" for name, status in results)
            self.shown.append(argv[2])
            return 0, SHOW[argv[2]]
        return run

    def r3(self, results):
        base, head, mb = merge_base(self.repo, "HEAD~1", "HEAD")
        rv = Review(self.repo, mb, head, ADAPTERS["python"](), ["tests/**"], ".")
        return mutants.run(rv, None, 5, None, None, self.runner(results))

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


if __name__ == "__main__":
    unittest.main()
