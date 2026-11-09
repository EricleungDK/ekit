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
        self.assertEqual(fm.listeners("4321", tools(ss=SS)), ("777", "vite"))

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


class TestClassify(unittest.TestCase):
    def test_env_signature_is_a_lead_with_the_check_that_settles_it(self):
        msg = fm.classify("npm test", "Error: getaddrinfo ENOTFOUND api.exmaple.com")
        self.assertIn("looks like sandbox/env (matched `ENOTFOUND`)", msg)
        self.assertIn("Fails the same way there → it is the code or the test", msg)
        self.assertNotIn("failure, not a code bug", msg)

    def test_port_in_use_without_an_owner_still_answers(self):
        with mock.patch.object(fm, "listeners", lambda port: None):
            msg = fm.classify("npm run dev", "listen EADDRINUSE: address already in use 127.0.0.1:4321")
        self.assertIn("port 4321 in use", msg)

    def test_plain_test_failure_points_at_triage(self):
        self.assertIn("failure-triage", fm.classify("uv run pytest -q", "FAILED tests/test_x.py::test_a"))

    def test_unknown_failure_is_silent(self):
        self.assertIsNone(fm.classify("ls /nope", "No such file or directory"))


if __name__ == "__main__":
    unittest.main()
