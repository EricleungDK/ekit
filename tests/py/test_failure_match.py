import os
import sys
import time
import unittest
from unittest import mock

import _kit

fm = _kit.load("failure-match")

LSOF = ("COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
        "node    4242 eric   23u  IPv4 0xabc      0t0  TCP 127.0.0.1:4321 (LISTEN)\n")
SS = 'LISTEN 0 511 127.0.0.1:4321 0.0.0.0:* users:(("vite",pid=777,fd=20))\n'


def tools(**outputs):
    """A lookup runner: argv[0] -> its stdout; a tool that is not listed is not installed ("")."""
    calls = []

    def run(argv):
        calls.append(argv)
        return outputs.get(argv[0], "")

    run.calls = calls
    return run


class TestListeners(unittest.TestCase):
    def test_ss_names_the_owner_on_linux(self):
        run = tools(ss=SS)
        self.assertEqual(fm.listeners("4321", run), ("777", "vite"))
        self.assertEqual(run.calls, [["ss", "-ltnpH", "sport = :4321"]])

    def test_a_stubbed_ss_answer_is_used_without_running_ss(self):
        run = tools()
        with mock.patch.dict(os.environ, {"SS_STUB": SS}):
            self.assertEqual(fm.listeners("4321", run), ("777", "vite"))
        self.assertEqual(run.calls, [])

    def test_lsof_rows_need_a_command_and_a_numeric_pid(self):
        head = LSOF.splitlines()[0] + "\n"
        self.assertEqual(fm.listeners("4321", tools(lsof=head + "node 4242\n")), ("4242", "node"))
        self.assertIsNone(fm.listeners("4321", tools(lsof=head + "node\n\nnode notapid x\n")))

    def test_lsof_names_the_owner_where_there_is_no_ss(self):
        run = tools(lsof=LSOF)
        self.assertEqual(fm.listeners("4321", run), ("4242", "node"))
        self.assertEqual(run.calls[-1], ["lsof", "-nP", "-iTCP:4321", "-sTCP:LISTEN"])

    def test_no_tool_at_all_is_no_owner_not_a_crash(self):
        self.assertIsNone(fm.listeners("4321", tools()))

    def test_lsof_header_alone_is_no_owner(self):
        self.assertIsNone(fm.listeners("4321", tools(lsof=LSOF.splitlines()[0] + "\n")))

    def test_a_missing_executable_reads_as_empty_output(self):
        self.assertEqual(fm.run(["ekit-no-such-tool-xyz"]), "")

    def test_run_returns_the_tools_stdout_as_text_and_keeps_stderr_out(self):
        self.assertEqual(fm.run([sys.executable, "-c", "import sys; print('hi'); print('noise', file=sys.stderr)"]), "hi\n")

    def test_a_tool_that_does_not_answer_in_time_reads_as_empty_output(self):
        t0 = time.monotonic()
        with mock.patch.object(fm, "LOOKUP_TIMEOUT", 0.3):
            self.assertEqual(fm.run([sys.executable, "-c", "import time; time.sleep(5)"]), "")
        self.assertLess(time.monotonic() - t0, 3)


class TestClassify(unittest.TestCase):
    def test_env_signature_is_a_lead_with_the_check_that_settles_it(self):
        msg = fm.classify("npm test", "Error: getaddrinfo ENOTFOUND api.exmaple.com")
        self.assertEqual(msg, "[ekit] looks like sandbox/env (matched `ENOTFOUND`), not yet a code bug. Leave code as is "
                              "and rerun once unsandboxed/escalated. Passes there → record 'passed only unsandboxed'. "
                              "Fails the same way there → it is the code or the test: classify it with the "
                              "failure-triage skill. Can't rerun → verification debt.")

    def test_port_in_use_without_an_owner_still_answers(self):
        with mock.patch.object(fm, "listeners", lambda port: None):
            msg = fm.classify("npm run dev", "listen EADDRINUSE: address already in use 127.0.0.1:4321")
        self.assertIn("port 4321 in use", msg)

    def test_plain_test_failure_points_at_triage(self):
        self.assertIn("failure-triage", fm.classify("uv run pytest -q", "FAILED tests/test_x.py::test_a"))

    def test_unknown_failure_is_silent(self):
        self.assertIsNone(fm.classify("ls /nope", "No such file or directory"))

    def test_a_search_that_names_a_test_runner_is_silent(self):
        self.assertIsNone(fm.classify("grep -rn pytest docs/", "Exit code 1"))

    def port(self, err):
        with mock.patch.object(fm, "listeners", lambda port: None):
            return fm.classify("docker compose up", err)

    def test_a_log_lines_clock_time_is_not_the_port(self):
        self.assertIn("port 3000 in use", self.port("2026-11-10 12:34:56 web | listen EADDRINUSE: address already in use :::3000"))
        self.assertIn("port 5173 in use", self.port("2026-11-10T09:05:01Z bind [::1]:5173: address already in use"))

    def test_a_port_after_an_ip_address_is_still_read(self):
        self.assertIn("port 8080 in use", self.port("listen tcp 127.0.0.1:8080: bind: address already in use"))
        self.assertIn("port 80 in use", self.port("listen tcp 0.0.0.0:80: bind: address already in use"))

    def test_an_error_that_names_no_port_says_so(self):
        self.assertIn("port ? in use", self.port("12:34:56 OSError: [Errno 98] Address already in use"))


class TestRunsTests(unittest.TestCase):
    """The `test red` hint is for a command that ran tests, not for one that only mentions a runner."""

    def test_a_runner_is_a_test_run_alone_behind_a_wrapper_or_with_arguments(self):
        for cmd in ("pytest -q", "uv run pytest tests/test_x.py", "PYTHONPATH=. python3 -m pytest", "cargo test",
                    "npm run test -- --ci", "bash -c 'pytest -q'"):
            self.assertIs(fm.runs_tests(cmd), True, cmd)

    def test_a_tool_that_reads_or_prints_ran_no_test_whatever_it_names(self):
        for cmd in ("grep -rn pytest docs/", "/usr/bin/grep pytest f", "'grep' -rn pytest docs/", "git log --grep jest",
                    "cat vitest.config.ts", "grep x f > pytest.log", "grep -c X pytest.ini"):
            self.assertIs(fm.runs_tests(cmd), False, cmd)

    def test_each_command_of_a_line_is_judged_on_its_own(self):
        for cmd in ("cat pytest.ini; pytest -q", "grep -c x f && cargo test", "pytest -q | tee out.txt",
                    "(cd app && npm test)", "grep pytest a\npytest -q", "pytest -q;"):
            self.assertIs(fm.runs_tests(cmd), True, cmd)
        self.assertIs(fm.runs_tests("grep pytest a\ngrep jest b"), False)

    def test_a_separator_inside_quotes_does_not_start_a_command(self):
        self.assertIs(fm.runs_tests('grep -E "pytest|jest" notes.md'), False)

    def test_a_line_with_an_open_quote_is_judged_as_a_whole(self):
        self.assertIs(fm.runs_tests("pytest -q 'oops"), True)
        self.assertIs(fm.runs_tests("echo 'oops"), False)

    def test_a_command_that_names_no_runner_is_not_a_test_run(self):
        self.assertIs(fm.runs_tests("ls /nope"), False)
        self.assertIs(fm.runs_tests(""), False)


if __name__ == "__main__":
    unittest.main()
