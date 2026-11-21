"""_kit.run_cli (#35): the engine CLI in this process, so mutmut sees the calls (R3 credits in-process calls only)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import _kit


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           *args], check=True, capture_output=True, text=True).stdout.strip()


class RunCli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name
        git(self.repo, "init", "-q", "-b", "main")
        os.makedirs(os.path.join(self.repo, "src"))
        with open(os.path.join(self.repo, "src", "calc.py"), "w", newline="\n") as f:
            f.write("def add(a, b):\n    return a + b\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def test_stdout_and_exit_code_of_a_run(self):
        r = _kit.run_cli(["plan", "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", "python"])
        self.assertEqual((r.returncode, json.loads(r.stdout), r.stderr), (0, {"run": False}, ""))

    def test_a_usage_error_is_exit_2_with_argparse_words_on_stderr(self):
        r = _kit.run_cli(["plan", "--repo", self.repo])
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("the following arguments are required: --base, --head, --stack", r.stderr)

    def test_a_git_error_is_exit_2_with_the_message(self):
        r = _kit.run_cli(["plan", "--repo", self.repo, "--base", "nope", "--head", self.base, "--stack", "python"])
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.startswith("mech-review: "), r.stderr)

    def test_another_main_runs_the_same_way(self):
        def main(argv):
            print("out", argv)
            print("err", file=sys.stderr)
            raise SystemExit(3)

        self.assertEqual(tuple(_kit.run_cli(["x"], main=main)), (3, "out ['x']\n", "err\n"))

    def test_a_main_that_returns_none_is_exit_0(self):
        self.assertEqual(_kit.run_cli([], main=lambda argv: None).returncode, 0)

    def test_sys_exit_with_a_message_is_exit_1_with_the_message_on_stderr(self):
        def main(argv):
            sys.exit("boom")

        self.assertEqual(tuple(_kit.run_cli([], main=main)), (1, "", "boom\n"))


if __name__ == "__main__":
    unittest.main()
