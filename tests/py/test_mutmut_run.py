"""R3 for python end to end, with mutmut replaced by a scripted runner: which mutants it is asked to show."""
import contextlib
import fnmatch
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants
from scripts.mech_review.gitio import Review, merge_base
from scripts.mech_review.stack import ADAPTERS

BASE = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
HEAD = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    c = a - b\n    return c\n"
SHOW = {
    "calc.x_sub__mutmut_1": "--- calc.py\n+++ calc.py\n@@ -1,3 +1,3 @@\n def sub(a, b):\n-    c = a - b\n+    c = a + b\n     return c\n",
    "calc.x_sub__mutmut_2": "--- calc.py\n+++ calc.py\n@@ -1,3 +1,3 @@\n def sub(a, b):\n     c = a - b\n-    return c\n+    return None\n",
}


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


class FakeMutmut:
    """mutmut as the engine drives it. `mutants` maps each mutant name to the status it ends with once it has run.
    A `run` whose filter matches nothing ends with mutmut's no-match error and runs none; a `run` with filters marks
    the matching mutants as run. `results` lists every mutant: its status, or `not checked`."""

    FAILED = "....F\nFAILED tests/test_calc.py::test_sub - AssertionError: 3 != 2\n"

    def __init__(self, mutants, fail_run=None, leave_unrun=(), timeout_run=None, fail_text="Failed to run clean test\n",
                 early_run=None, results_rc=None, show_rc=0):
        self.mutants, self.ran, self.runs, self.shown, self.budgets = dict(mutants), set(), [], [], []
        self.fail_run, self.leave_unrun, self.timeout_run = fail_run, set(leave_unrun), timeout_run
        self.fail_text, self.early_run, self.results_rc, self.show_rc = fail_text, early_run, results_rc, show_rc
        self.cwds, self.results_calls = set(), 0

    def __call__(self, argv, cwd, timeout):
        verb, args = argv[1], argv[2:]
        self.cwds.add(cwd)
        if verb == "--version":
            return 0, "mutmut, version 3.8.1"
        if verb in ("results", "show") and timeout != mutants.PROBE_TIMEOUT:
            return 2, f"unexpected timeout {timeout!r} for {verb}"
        if verb == "results":
            self.results_calls += 1
            if args != ["--all", "True"]:
                return 2, f"Error: unexpected arguments {args}"  # without --all True mutmut hides the caught mutants
            if self.results_rc and self.results_calls >= self.results_rc:
                return 1, "Traceback (most recent call last):\nOSError: mutants/ unreadable"
            return 0, "".join(f"    {n}: {st if n in self.ran else 'not checked'}\n" for n, st in self.mutants.items())
        if verb == "show":
            self.shown.append(args[0])
            return self.show_rc, SHOW[args[0]]  # a failing show may still print a diff: it is not to be trusted
        if verb != "run":
            return 2, f"Error: No such command {verb!r}"
        self.runs.append(args)
        self.budgets.append(timeout)
        if self.fail_run == len(self.runs):
            return 1, self.FAILED + self.fail_text
        hit = {n for n in self.mutants if any(fnmatch.fnmatchcase(n, pat) for pat in args)} - self.leave_unrun
        if self.timeout_run == len(self.runs):
            self.ran |= set(sorted(hit)[:1])
            return "timeout", ""
        if self.early_run == len(self.runs):
            return 1, "Stopping early, because tests recorded trampoline hits but none match any mutant key."
        if not hit:
            return 1, f"AssertionError: {mutants.NO_MATCH}\n\nFilter: {tuple(args)}"
        self.ran |= hit
        return 0, "done"


ADD1, ADD2, SUB1, SUB2 = (f"calc.x_{fn}__mutmut_{n}" for fn in ("add", "sub") for n in (1, 2))


class TestMutmutCheck(unittest.TestCase):
    """The diff changes `sub` only (BASE -> HEAD). mutmut mutates the whole file, so it also has mutants of `add`."""

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

    def r3(self, fake, budget_min=5):
        base, head, mb = merge_base(self.repo, "HEAD~1", "HEAD")
        rv = Review(self.repo, mb, head, ADAPTERS["python"](), ["tests/**"], ".")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            check, entries = mutants.run(rv, None, budget_min, None, None, fake)
        return check, entries, err.getvalue()

    def test_only_the_mutants_of_touched_functions_run(self):
        fake = FakeMutmut({ADD1: "survived", ADD2: "no tests", SUB1: "survived", SUB2: "killed"})
        check, entries, _ = self.r3(fake)
        self.assertEqual(fake.runs, [[mutants.LIST_ONLY], ["calc.x_sub__mutmut_*"]])
        self.assertEqual(fake.ran, {SUB1, SUB2})
        self.assertEqual(fake.shown, [SUB1])
        self.assertEqual((check["status"], check["tested"], check["total"]), ("fail", 2, 2))
        self.assertEqual(check["note"], "2/2 tested: 1 missed in the diff, 0 missed outside the diff, 0 unlocated, 1 caught; "
                                        "2 in functions the diff does not touch: not run")
        self.assertEqual([(e["file"], e["line"], e["severity"]) for e in entries], [("calc.py", 6, "fail")])
        self.assertEqual(entries[0]["problem"], "MISSED mutant calc.py:6: c = a - b -> c = a + b")

    def test_all_caught_in_the_touched_function_is_a_pass(self):
        check, entries, _ = self.r3(FakeMutmut({ADD1: "survived", SUB1: "killed", SUB2: "killed"}))
        self.assertEqual((check["status"], entries), ("pass", []))
        self.assertEqual(check["note"], "2/2 tested: 0 missed in the diff, 0 missed outside the diff, 0 unlocated, 2 caught; "
                                        "1 in functions the diff does not touch: not run")

    def test_mutants_only_in_untouched_functions_means_no_second_run(self):
        fake = FakeMutmut({ADD1: "survived", ADD2: "survived"})
        check, entries, _ = self.r3(fake)
        self.assertEqual(fake.runs, [[mutants.LIST_ONLY]])
        self.assertEqual((check["status"], check["tested"], check["total"], entries), ("pass", 0, 0, []))
        self.assertEqual(check["note"], "0 mutants in the diff (2 in functions the diff does not touch: not run)")

    def test_no_mutants_at_all_is_a_pass(self):
        fake = FakeMutmut({})
        check, entries, _ = self.r3(fake)
        self.assertEqual((check, entries, len(fake.runs)),
                         ({"status": "pass", "note": "0 mutants in the diff", "tested": 0, "total": 0}, [], 1))

    def test_mutmut_runs_in_one_directory_the_worktrees(self):
        fake = FakeMutmut({SUB1: "survived"})
        self.r3(fake)
        (cwd,) = fake.cwds
        self.assertTrue(os.path.isabs(cwd) and cwd != self.repo, cwd)

    def test_tests_that_fail_while_statistics_are_collected_stop_the_check(self):
        fake = FakeMutmut({SUB1: "killed"}, fail_run=1, fail_text="failed to collect stats. runner returned 1\n")
        check, entries, err = self.r3(fake)
        self.assertEqual(check, {"status": "fail", "note": "baseline tests fail at head: mutants not run"})
        self.assertEqual(entries, [{
            "id": entries[0]["id"], "check": "R3", "class": "agent-fixable", "severity": "fail", "file": "", "line": 0,
            "problem": "baseline tests fail at head: mutants not run",
            "hint": "fix the failing tests first: mutation needs an unmutated tree that passes",
            "forbidden": "a mutation check that did not run"}])
        # the id is the contract's: check + file + key, the same on every run, so fix rounds can be counted
        self.assertEqual(entries[0]["id"], "R3-" + hashlib.sha1(b"R3baseline").hexdigest()[:8])
        self.assertIn("failed to collect stats. runner returned 1", err)

    def test_mutmut_stopping_early_means_no_test_reaches_the_touched_functions(self):
        fake = FakeMutmut({ADD1: "killed", SUB1: "killed", SUB2: "killed"}, early_run=2)
        check, entries, _ = self.r3(fake)
        self.assertEqual(fake.shown, [SUB1, SUB2])
        self.assertEqual((check["status"], check["tested"], check["total"]), ("fail", 2, 2))
        self.assertEqual({e["hint"] for e in entries}, {"no test reaches this line: add a test that calls it and asserts the result"})

    def test_a_filter_that_matches_nothing_on_the_real_run_is_not_a_result(self):
        fake = FakeMutmut({SUB1: "killed"}, leave_unrun=[SUB1])
        check, entries, _ = self.r3(fake)
        self.assertEqual((check["status"], entries, len(fake.runs)), ("n/a", [], 2))
        self.assertTrue(check["note"].startswith("mutmut exit 1 (env): AssertionError: " + mutants.NO_MATCH), check["note"])

    def test_results_that_cannot_be_read_are_not_run_not_a_pass(self):
        for when in (1, 2):
            check, entries, _ = self.r3(FakeMutmut({SUB1: "killed"}, results_rc=when))
            self.assertEqual((check, entries), ({"status": "n/a", "note": "mutmut results failed (env): Traceback (most "
                                                 "recent call last):"}, []), when)

    def test_mutants_mutmut_cannot_show_are_counted_as_unlocated_and_do_not_end_the_loop(self):
        fake = FakeMutmut({SUB1: "survived", SUB2: "survived"}, show_rc=1)
        check, entries, _ = self.r3(fake)
        self.assertEqual(fake.shown, [SUB1, SUB2])
        self.assertEqual([(e["severity"], e["problem"]) for e in entries],
                         [("confirm", "R3 unlocated: 2 missed mutant(s) could not be mapped to a line: not blocking")])
        self.assertEqual(check["note"], "2/2 tested: 0 missed in the diff, 0 missed outside the diff, 2 unlocated, 0 caught")

    def test_a_shown_diff_that_names_no_file_is_unlocated(self):
        fake = FakeMutmut({SUB1: "survived"})
        with mock.patch.dict(SHOW, {SUB1: "@@ -1 +1 @@\n-    c = a - b\n+    c = a + b\n"}):
            check, entries, _ = self.r3(fake)
        self.assertEqual([e["severity"] for e in entries], ["confirm"])

    def test_every_changed_line_of_the_touched_function_is_judged(self):
        show = dict(SHOW)
        show[SUB2] = "--- calc.py\n+++ calc.py\n@@ -1,3 +1,3 @@\n def sub(a, b):\n     c = a - b\n-    return c\n+    return None\n"
        fake = FakeMutmut({SUB1: "killed", SUB2: "survived"})
        with mock.patch.dict(SHOW, show):
            check, entries, _ = self.r3(fake)
        # line 7 `return c` is new in this diff as well (the base returned `a - b` directly)
        self.assertEqual([(e["line"], e["problem"]) for e in entries], [(7, "MISSED mutant calc.py:7: return c -> return None")])
        self.assertEqual(check["status"], "fail")

    def clock(self, *times):
        """time.monotonic as the engine sees it: these readings in order, then the last one again"""
        left = list(times)
        return mock.patch.object(mutants.time, "monotonic", lambda: left.pop(0) if len(left) > 1 else left[0])

    def test_the_second_run_gets_what_is_left_of_the_budget(self):
        fake = FakeMutmut({SUB1: "killed"})
        with self.clock(100, 130, 140):
            self.r3(fake, budget_min=2)
        self.assertEqual(fake.budgets, [120, 90])

    def test_a_budget_already_spent_leaves_the_second_run_one_second(self):
        fake = FakeMutmut({SUB1: "killed"})
        with self.clock(100, 700, 710):
            self.r3(fake, budget_min=2)
        self.assertEqual(fake.budgets, [120, 1.0])

    def test_no_budget_means_no_limit_on_either_run(self):
        fake = FakeMutmut({SUB1: "killed"})
        self.r3(fake, budget_min=None)
        self.assertEqual(fake.budgets, [None, None])

    def test_tests_that_fail_while_listing_stop_the_check_and_are_named_in_the_job_log(self):
        fake = FakeMutmut({SUB1: "killed"}, fail_run=1)
        check, entries, err = self.r3(fake)
        self.assertEqual((check["status"], check["note"]), ("fail", "baseline tests fail at head: mutants not run"))
        self.assertEqual([e["problem"] for e in entries], ["baseline tests fail at head: mutants not run"])
        self.assertEqual(err, "mech-review: R3 fail: last 3 lines of mutmut output\n....F\n"
                              "FAILED tests/test_calc.py::test_sub - AssertionError: 3 != 2\nFailed to run clean test\n")
        self.assertEqual(len(fake.runs), 1)

    def test_tests_that_fail_before_the_mutants_run_stop_the_check_too(self):
        fake = FakeMutmut({SUB1: "killed"}, fail_run=2)
        check, entries, err = self.r3(fake)
        self.assertEqual((check["status"], len(entries), len(fake.runs)), ("fail", 1, 2))
        self.assertIn("FAILED tests/test_calc.py::test_sub", err)

    def test_a_touched_mutant_that_mutmut_left_unrun_is_partial_not_a_pass(self):
        check, entries, _ = self.r3(FakeMutmut({SUB1: "killed", SUB2: "killed"}, leave_unrun=[SUB2]))
        self.assertEqual((check["status"], check["tested"], check["total"]), ("partial", 1, 2))

    def test_the_budget_ending_while_listing_is_partial_with_nothing_tested(self):
        fake = FakeMutmut({ADD1: "killed", SUB1: "killed", SUB2: "killed"}, timeout_run=1)
        check, entries, _ = self.r3(fake)
        self.assertEqual(len(fake.runs), 1)
        self.assertEqual((check["status"], check["note"]), ("partial", "0/2 tested: budget hit, no MISSED so far"))

    def test_the_budget_ending_mid_run_keeps_what_was_tested(self):
        fake = FakeMutmut({SUB1: "survived", SUB2: "killed"}, timeout_run=2)
        check, entries, _ = self.r3(fake)
        self.assertEqual((check["status"], check["note"]), ("fail", "1/2 tested: budget hit, 1 missed"))

    def test_any_other_mutmut_error_is_not_run_not_a_pass(self):
        def broken(argv, cwd, timeout):
            return (0, "mutmut, version 3.8.1") if argv[1] == "--version" else (1, "ModuleNotFoundError: No module named 'x'")
        check, entries, _ = self.r3(broken)
        self.assertEqual((check["status"], entries), ("n/a", []))
        self.assertEqual(check["note"], "mutmut exit 1 (env): ModuleNotFoundError: No module named 'x'; check the test deps "
                                        "(requirements, setup-command)")


KEPT = "def sub(a, b):\n    c = a - b\n    return c\n"          # base
EDITED = "def sub(a, b):\n    c = a - b\n    return c + 0\n"    # head: only the return line changes
COPIES = """\
def sub(a, b):
    c = a - b
    return c + 0


def x_sub__mutmut_orig(a, b):
    c = a - b
    return c + 0


def x_sub__mutmut_1(a, b):
    c = a + b
    return c + 0


def x_sub__mutmut_2(a, b):
    c = a - b
    return c - 0
"""


class WritingMutmut(FakeMutmut):
    """A fake that also leaves what mutmut leaves in `mutants/`: the mutated file and its .meta."""

    def __call__(self, argv, cwd, timeout):
        if argv[1] == "run" and not self.runs:
            os.makedirs(os.path.join(cwd, "mutants"))
            with open(os.path.join(cwd, "mutants", "calc.py"), "w") as f:
                f.write(COPIES)
            with open(os.path.join(cwd, "mutants", "calc.py.meta"), "w") as f:
                json.dump({"exit_code_by_key": dict.fromkeys(self.mutants)}, f)
        return super().__call__(argv, cwd, timeout)


class TestMutmutFiles(unittest.TestCase):
    """The diff changes the return line of `sub`; its other line is unchanged."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        for name, text in (("pyproject.toml", "[project]\nname = 'calc'\n"), ("calc.py", KEPT)):
            with open(os.path.join(self.repo, name), "w") as f:
                f.write(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        with open(os.path.join(self.repo, "calc.py"), "w") as f:
            f.write(EDITED)
        git(self.repo, "commit", "-q", "-am", "head")

    def r3(self, fake):
        base, head, mb = merge_base(self.repo, "HEAD~1", "HEAD")
        rv = Review(self.repo, mb, head, ADAPTERS["python"](), ["tests/**"], ".")
        return mutants.run(rv, None, 5, None, None, fake)

    def test_missed_mutants_are_located_from_mutmuts_files_without_asking_it(self):
        fake = WritingMutmut({SUB1: "survived", SUB2: "survived"})
        check, entries = self.r3(fake)
        self.assertEqual(fake.shown, [])
        self.assertEqual([(e["file"], e["line"], e["problem"]) for e in entries],
                         [("calc.py", 3, "MISSED mutant calc.py:3: return c + 0 -> return c - 0")])
        self.assertEqual(check["note"], "2/2 tested: 1 missed in the diff, 1 missed outside the diff, 0 unlocated, 0 caught")

    def test_a_miss_on_an_unchanged_line_of_the_touched_function_does_not_block(self):
        check, entries = self.r3(WritingMutmut({SUB1: "survived", SUB2: "killed"}))
        self.assertEqual((check["status"], entries), ("pass", []))
        self.assertEqual(check["note"], "2/2 tested: 0 missed in the diff, 1 missed outside the diff, 0 unlocated, 1 caught")

    def test_a_copy_that_disagrees_with_the_source_is_not_trusted(self):
        fake = WritingMutmut({SUB2: "survived"})
        stale = COPIES.replace("def x_sub__mutmut_orig(a, b):\n", "def x_sub__mutmut_orig(a, b):\n    pass\n") \
                      .replace("def x_sub__mutmut_2(a, b):\n", "def x_sub__mutmut_2(a, b):\n    pass\n")
        with mock.patch.dict(globals(), {"COPIES": stale}), \
                mock.patch.dict(SHOW, {SUB2: "--- calc.py\n+++ calc.py\n@@ -1 +1 @@\n-    return c + 0\n+    return c - 0\n"}):
            check, entries = self.r3(fake)
        self.assertEqual(fake.shown, [SUB2])  # the offset points past the function: mutmut is asked instead
        self.assertEqual([e["line"] for e in entries], [3])

    def test_a_copy_whose_line_is_not_the_sources_line_is_not_trusted(self):
        fake = WritingMutmut({SUB2: "survived"})
        stale = COPIES.replace("return c + 0", "return c * 1").replace("return c - 0", "return c / 1")
        with mock.patch.dict(globals(), {"COPIES": stale}), \
                mock.patch.dict(SHOW, {SUB2: "--- calc.py\n+++ calc.py\n@@ -1 +1 @@\n-    return c + 0\n+    return c - 0\n"}):
            check, entries = self.r3(fake)
        self.assertEqual(fake.shown, [SUB2])  # same offset, other text: the copy is of another version of the file
        self.assertEqual([e["problem"] for e in entries], ["MISSED mutant calc.py:3: return c + 0 -> return c - 0"])

    def test_a_mutant_the_files_do_not_explain_is_asked_of_mutmut(self):
        fake = WritingMutmut({SUB1: "survived"})
        with mock.patch.object(mutants, "mutant_change", return_value=None), \
                mock.patch.dict(SHOW, {SUB1: "--- calc.py\n+++ calc.py\n@@ -1 +1 @@\n-    return c + 0\n+    return c - 0\n"}):
            check, entries = self.r3(fake)
        self.assertEqual(fake.shown, [SUB1])
        self.assertEqual([e["line"] for e in entries], [3])


class TestFunctionGlob(unittest.TestCase):
    def test_every_mutant_of_the_function_and_no_other(self):
        glob = mutants.function_glob("calc.core.x_add__mutmut_3")
        self.assertEqual(glob, "calc.core.x_add__mutmut_*")
        self.assertTrue(fnmatch.fnmatchcase("calc.core.x_add__mutmut_12", glob))
        self.assertFalse(fnmatch.fnmatchcase("calc.core.x_add_all__mutmut_1", glob))

    def test_a_function_whose_own_name_holds_mutmuts_marker_keeps_its_whole_name(self):
        self.assertEqual(mutants.function_glob("pkg.x__mutmut_stop__mutmut_5"), "pkg.x__mutmut_stop__mutmut_*")

    def test_a_method_keeps_its_class(self):
        self.assertEqual(mutants.function_glob("calc.core.x\u01c1Calc\u01c1add__mutmut_1"), "calc.core.x\u01c1Calc\u01c1add__mutmut_*")

    def test_glob_characters_in_a_name_are_literal(self):
        glob = mutants.function_glob("pkg.x_a[b]__mutmut_1")
        self.assertTrue(fnmatch.fnmatchcase("pkg.x_a[b]__mutmut_2", glob))
        self.assertFalse(fnmatch.fnmatchcase("pkg.x_ab__mutmut_2", glob))

    def test_the_list_only_filter_cannot_match_a_mutant(self):
        self.assertFalse(fnmatch.fnmatchcase(SUB1, mutants.LIST_ONLY))
        self.assertNotIn("__mutmut_", mutants.LIST_ONLY)


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
