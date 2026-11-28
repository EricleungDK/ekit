"""#107 B2: a test program that exists but cannot run (no execute bit, a directory, a bad `#!` interpreter, a file the
OS cannot execute) gives R1/R4 an `env` result naming the program and the error, never a traceback: `red` and `all`
through cli.main in this process, on the fixture repos of test_adapter_run (the built-in ts adapter and its file)."""
import json
import errno
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from scripts.mech_review import red
from test_adapter_run import TEST_FRESH, TS_FILE, Fixture

FIX = "give it the execute bit and a `#!` line whose interpreter exists, {fix}, or set setup-command ({what})"
NPM = "run the adapter's install command (`npm ci`)"
R1_WHAT, R4_WHAT = "tests on the base's production code", "new or changed tests"


def note(prog, err, what, fix=NPM):
    return f"test program cannot run (env): `{prog}`: {err}: " + FIX.format(fix=fix, what=what)


class CannotRun(Fixture):
    def runner_file(self, text, mode):
        """node_modules/.bin/vitest in the caller's checkout (linked into the worktree) holding text, with mode."""
        bin_dir = os.path.join(self.repo, "node_modules", ".bin")
        os.makedirs(bin_dir, exist_ok=True)
        path = os.path.join(bin_dir, "vitest")
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def checks(self, adapter=TS_FILE, check="red", stub=None, extra=()):
        base, head = self.ts_repo("fresh fail pass\n")
        with mock.patch.dict(os.environ):
            del os.environ["MECH_TEST_STUB"]
            if stub:
                os.environ["MECH_TEST_STUB"] = stub
            r = self.red(base, head, *extra, adapter=adapter, check=check)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return json.loads(r.stdout)["checks"]

    def assert_env(self, prog, err, **kw):
        for adapter, fix in ((TS_FILE, NPM), (None, "install it")):  # the built-in names no install command
            checks = self.checks(adapter=adapter, **kw)
            self.assertEqual(checks["R1"], {"status": "n/a", "note": note(prog, err, R1_WHAT, fix)}, adapter)
            self.assertEqual(checks["R4"], {"status": "n/a", "note": note(prog, err, R4_WHAT, fix)}, adapter)

    def test_a_program_without_the_execute_bit_is_env_naming_it_and_the_error(self):
        self.runner_file("#!/bin/sh\nexit 0\n", 0o644)
        self.assert_env("node_modules/.bin/vitest", "Permission denied")

    def test_the_same_through_all(self):
        self.runner_file("#!/bin/sh\nexit 0\n", 0o644)
        checks = self.checks(check="all")
        self.assertEqual(checks["R1"]["note"], note("node_modules/.bin/vitest", "Permission denied", R1_WHAT))

    def test_a_directory_in_the_programs_place_is_env(self):
        os.makedirs(os.path.join(self.repo, "node_modules", ".bin", "vitest"))
        self.assert_env("node_modules/.bin/vitest", "Is a directory")

    def test_a_bad_interpreter_line_is_env_naming_the_interpreter_not_a_missing_program(self):
        self.runner_file("#!/no/such/interp\nexit 0\n", 0o755)
        self.assert_env("node_modules/.bin/vitest", "bad interpreter `/no/such/interp`")

    def test_a_bad_interpreter_line_with_arguments_names_the_interpreter_only(self):
        self.runner_file("#! /no/such/interp -x -y\r\nexit 0\n", 0o755)
        self.assert_env("node_modules/.bin/vitest", "bad interpreter `/no/such/interp`")

    def test_an_executable_file_the_os_cannot_execute_is_env(self):
        self.runner_file("not a program\n", 0o755)  # sh would run it; the kernel refuses it: ENOEXEC
        self.assert_env("node_modules/.bin/vitest", "Exec format error")

    def test_a_binary_whose_loader_is_missing_is_env_not_a_missing_program(self):
        with open(shutil.which("true"), "rb") as f:
            elf = f.read()
        interp = re.search(rb"/[\w./-]*ld[\w.-]*\.so[\w.]*\x00", elf[:4096])  # PT_INTERP, early in a dynamic ELF
        self.assertIsNotNone(interp, "`true` is a dynamic ELF binary on the systems the suite runs on")
        gone = b"/" + b"x" * (interp.end() - interp.start() - 2) + b"\x00"  # same length: the ELF stays well formed
        self.runner_file("", 0o755)
        with open(os.path.join(self.repo, "node_modules", ".bin", "vitest"), "wb") as f:
            f.write(elf[:interp.start()] + gone + elf[interp.end():])
        self.assert_env("node_modules/.bin/vitest", "its interpreter or loader is missing")

    def test_an_absolute_program_path_is_named_as_given(self):
        stub = os.path.join(self.tmp, "runner")
        with open(stub, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(stub, 0o644)
        self.assert_env(stub, "Permission denied", stub=stub)

    def test_a_program_found_on_path_with_a_bad_interpreter_is_env(self):
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        prog = os.path.join(bin_dir, "myrunner")
        with open(prog, "w") as f:
            f.write("#!/no/such/interp\n")
        os.chmod(prog, 0o755)
        with mock.patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"]}):
            checks = self.checks(adapter=None, extra=("--test-cmd", "myrunner run"))
        self.assertEqual(checks["R1"]["note"], note("myrunner", "bad interpreter `/no/such/interp`", R1_WHAT,
                                                    "install it"))

    def test_a_dangling_link_in_the_programs_place_reads_not_found(self):
        bin_dir = os.path.join(self.repo, "node_modules", ".bin")
        os.makedirs(bin_dir)
        os.symlink(os.path.join(self.tmp, "gone"), os.path.join(bin_dir, "vitest"))
        checks = self.checks(adapter=None)
        self.assertEqual(checks["R1"]["note"], "toolchain absent: `node_modules/.bin/vitest` not found (env): "
                                               f"install it, or set setup-command ({R1_WHAT})")

    def test_a_missing_program_still_reads_not_found(self):
        checks = self.checks(adapter=None)  # no node_modules at all: the pre-#107 note stays
        self.assertEqual(checks["R1"]["note"], "toolchain absent: `node_modules/.bin/vitest` not found (env): "
                                               f"install it, or set setup-command ({R1_WHAT})")


class TheArgumentsCannotPass(Fixture):
    """#107 review F1: an OSError that the arguments, the environment or the dir cause (a test name past the OS's
    limit for one argument: E2BIG) is no `n/a`: the program is fine, the run is not. R1 and R4 fail naming it."""

    def test_a_test_name_too_long_to_pass_fails_r1_and_r4_never_na(self):
        long = "f" * 140000  # one argument past Linux's 128 KiB limit for a single argument
        test = TEST_FRESH.replace('"fresh"', f'"{long}"')
        base, head = self.ts_repo("x pass pass\n", files={"tests/calc.test.ts": test})
        r = self.red(base, head, adapter=None)
        self.assertEqual((r.returncode, r.stderr), (1, ""))
        env = json.loads(r.stdout)
        self.assertEqual((env["checks"]["R1"]["status"], env["checks"]["R4"]["status"]), ("fail", "fail"))
        got = [(e["check"], e["class"], e["problem"]) for e in env["entries"]]
        self.assertEqual([g[:2] for g in got], [("R1", "agent-fixable"), ("R4", "agent-fixable")])
        for _, _, problem in got:
            self.assertRegex(problem, r"`[^`]+` could not start: Argument list too long \(its arguments: 14\d{4} "
                                      r"bytes\)\)?$")


class RunnerSplit(unittest.TestCase):
    """which OSError of a start is the program's (env: (None, `<prog>: cannot run: …`)) and which is the run's
    (red.CannotStart, a named error: R1/R4 fail, a usage-level stop elsewhere)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("MECH_TEST_STUB", None)

    def run_with(self, err, argv=("prog",)):
        with mock.patch.object(red.subprocess, "run", side_effect=err):
            return red.default_runner()(list(argv), self.tmp)

    def test_the_programs_own_errors_are_env(self):
        prog = os.path.join(self.tmp, "prog")
        with open(prog, "w") as f:
            f.write("#!/bin/sh\n")
        for code in (errno.EACCES, errno.EPERM, errno.ENOEXEC, errno.ELOOP, errno.EISDIR, errno.ENOTDIR):
            with self.subTest(errno=errno.errorcode[code]):
                self.assertEqual(self.run_with(OSError(code, os.strerror(code), prog), [prog]),
                                 (None, f"{prog}: cannot run: {os.strerror(code)}"))

    def test_errors_of_the_arguments_or_the_machine_are_a_named_stop(self):
        for code in (errno.E2BIG, errno.ENOMEM, errno.EMFILE, errno.ENFILE, errno.EAGAIN, errno.ENAMETOOLONG,
                     errno.ETXTBSY):
            with self.subTest(errno=errno.errorcode[code]):
                with self.assertRaises(red.CannotStart) as cm:
                    self.run_with(OSError(code, os.strerror(code), "prog"))
                self.assertTrue(str(cm.exception).startswith(f"`prog` could not start: {os.strerror(code)}"),
                                str(cm.exception))

    def test_a_real_e2big_names_the_size_of_the_arguments(self):
        with self.assertRaises(red.CannotStart) as cm:
            red.default_runner()([sys.executable, "-c", "pass", "x" * 200000], self.tmp)
        self.assertEqual(str(cm.exception), f"`{sys.executable}` could not start: Argument list too long (its "
                                            f"arguments: {len(sys.executable) + 1 + 3 + 5 + 200001} bytes)")

    def test_a_dir_to_run_in_that_is_gone_is_a_named_stop_not_a_missing_program(self):
        gone = os.path.join(self.tmp, "gone")
        with self.assertRaises(red.CannotStart) as cm:
            red.default_runner()([sys.executable, "-c", "pass"], gone)
        self.assertEqual(str(cm.exception), f"`{sys.executable}` could not start in `{gone}`: No such file or "
                                            "directory")

    def test_a_directory_found_on_path_is_named_a_directory(self):
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(os.path.join(bin_dir, "myrunner"))
        with mock.patch.dict(os.environ, {"PATH": bin_dir}):
            self.assertEqual(red.default_runner()(["myrunner"], self.tmp),
                             (None, "myrunner: cannot run: Is a directory"))

    def test_a_file_on_path_without_the_execute_bit_is_named_with_its_error(self):
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "myrunner"), "w") as f:
            f.write("#!/bin/sh\n")
        with mock.patch.dict(os.environ, {"PATH": bin_dir}):
            self.assertEqual(red.default_runner()(["myrunner"], self.tmp),
                             (None, "myrunner: cannot run: Permission denied"))


if __name__ == "__main__":
    unittest.main()
