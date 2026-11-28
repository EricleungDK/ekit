"""#107 review N5, N6, N7: one split of a start's errors for every runner (red.start_failed). The program's own errors
(no execute bit, a directory, a bad `#!` line) are env; any other (an argument past the OS's limit, a NUL byte in
one, the machine's limits) is the run's: R1/R4 fail naming it (`red`), R3 fail naming it (`mutants`), never n/a and
never a traceback. Through cli.main in this process, with the runners beside it."""
import errno
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants, red
from test_adapter_mutation_cli import ELEMENTS, Case, adapter_text
from test_adapter_run import TEST_FRESH, Fixture
from test_mutmut_run import SUB1, DiffOfSub

REAL_POPEN = subprocess.Popen


def popen_failing(err, stub):
    """subprocess.Popen that raises err for the tool's run (the stub, not its version probe), and starts any other."""
    def popen(argv, *a, **k):
        if stub in argv and "--version" not in argv:
            raise err
        return REAL_POPEN(argv, *a, **k)
    return popen


class RedNul(Fixture):
    def test_a_test_name_holding_a_nul_byte_fails_r1_and_r4_naming_it(self):
        base, head = self.ts_repo("x pass pass\n", files={"tests/calc.test.ts": TEST_FRESH.replace('"fresh"',
                                                                                                   '"nul\x00here"')})
        r = self.red(base, head, adapter=None)
        self.assertEqual((r.returncode, r.stderr), (1, ""))
        env = json.loads(r.stdout)
        self.assertEqual((env["checks"]["R1"]["status"], env["checks"]["R4"]["status"]), ("fail", "fail"))
        for e in env["entries"]:
            self.assertIn("could not start: embedded null byte", e["problem"])


class DeclaredToolStart(Case):
    def r3(self, err):
        self.pr()
        with mock.patch.object(mutants.subprocess, "Popen", popen_failing(err, self.stub)):
            r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)))
        self.assertEqual(r.stderr, "")
        return r.returncode, env["checks"]["R3"], [(e["check"], e["class"], e["problem"]) for e in env["entries"]]

    def test_an_argument_past_the_limit_is_an_r3_fail_naming_it(self):
        for err, why in ((OSError(errno.E2BIG, "Argument list too long", "mut"), "Argument list too long"),
                         (ValueError("embedded null byte"), "embedded null byte"),
                         (OSError(errno.EMFILE, "Too many open files", "mut"), "Too many open files")):
            with self.subTest(why=why):
                rc, check, ents = self.r3(err)
                self.assertEqual((rc, check["status"]), (1, "fail"))
                self.assertTrue(check["note"].startswith(f"R3 could not start its tool: `{sys.executable}` could "
                                                         f"not start: {why}"), check["note"])
                self.assertEqual(ents, [("R3", "agent-fixable", check["note"])])

    def test_the_programs_own_error_stays_not_installed(self):
        rc, check, ents = self.r3(OSError(errno.EACCES, "Permission denied", self.stub))
        self.assertEqual((rc, check["status"], ents), (0, "n/a", []))
        self.assertIn("not installed (env)", check["note"])


class BuiltInStart(DiffOfSub):
    def test_the_built_in_tools_run_error_is_an_r3_fail(self):
        def runner(argv, cwd, timeout):
            raise red.CannotStart("`mutmut` could not start: Argument list too long (its arguments: 200000 bytes)")
        check, entries, _ = self.r3(runner)
        self.assertEqual(check["status"], "fail")
        self.assertEqual([(e["check"], e["problem"]) for e in entries], [(
            "R3", "R3 could not start its tool: `mutmut` could not start: Argument list too long (its arguments: "
                  "200000 bytes): mutants not run")])


    def test_the_built_in_baseline_too(self):
        from scripts.mech_review.gitio import Review, merge_base
        from scripts.mech_review.stack import ADAPTERS

        def runner(argv, cwd, timeout):
            raise red.CannotStart("`mutmut` could not start: embedded null byte")
        _, head, mb = merge_base(self.repo, "HEAD~1", "HEAD")
        p = mutants.baseline(Review(self.repo, mb, head, ADAPTERS["python"](), ["tests/**"], "."), runner=runner)
        self.assertEqual((p["run"], p["check"]["status"], [e["problem"] for e in p["entries"]]), (
            False, "fail",
            ["R3 could not start its tool: `mutmut` could not start: embedded null byte: mutants not run"]))


class Runners(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("MECH_TEST_STUB", None)

    def test_both_runners_share_the_split(self):
        big = [sys.executable, "-c", "pass", "x" * 200000]
        for run in (lambda a: red.default_runner()(a, self.tmp), lambda a: mutants.default_runner()(a, self.tmp, 10)):
            with self.assertRaisesRegex(red.CannotStart, "could not start: Argument list too long"):
                run(big)
            with self.assertRaisesRegex(red.CannotStart, "could not start: embedded null byte"):
                run([sys.executable, "-c", "pass", "a\x00b"])
            self.assertEqual(run(["ekit-no-such-program-107"])[0], None)

    def test_a_relative_or_empty_path_entry_is_read_from_the_runs_dir(self):
        os.makedirs(os.path.join(self.tmp, "bin"))
        for d in ("bin", ""):
            prog = os.path.join(self.tmp, d, "myrunner")
            with open(prog, "w") as f:
                f.write("#!/no/such/interp\n")
            os.chmod(prog, 0o755)
            with self.subTest(entry=d or "(empty)"), mock.patch.dict(os.environ, {"PATH": d + os.pathsep + "/usr/bin"}):
                self.assertEqual(red.default_runner()(["myrunner"], self.tmp),
                                 (None, "myrunner: cannot run: bad interpreter `/no/such/interp`"))
            os.remove(prog)


if __name__ == "__main__":
    unittest.main()
