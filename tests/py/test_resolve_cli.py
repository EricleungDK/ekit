"""The `resolve` subcommand's arguments (#29): what a caller of `mech-review.py resolve` sees from its options, through
cli.main in this process (the workflow's `stack` job runs it; R3's mutmut credits in-process calls only)."""
import json
import os
import subprocess
import tempfile
import unittest

import _kit


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True)


class TestResolveArguments(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name
        git(self.repo, "init", "-q")
        os.makedirs(os.path.join(self.repo, "pkg"))
        with open(os.path.join(self.repo, "pkg", "pyproject.toml"), "w") as f:
            f.write("[project]\nname='x'\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")

    def test_leaving_out_base_is_a_usage_error(self):
        r = _kit.run_cli(["resolve", "--repo", self.repo, "--head", "HEAD"])
        self.assertEqual((r.returncode, r.stdout), (2, ""))

    def test_leaving_out_head_is_a_usage_error(self):
        r = _kit.run_cli(["resolve", "--repo", self.repo, "--base", "HEAD"])
        self.assertEqual((r.returncode, r.stdout), (2, ""))

    def test_repo_defaults_to_the_current_directory(self):
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.repo)
        r = _kit.run_cli(["resolve", "--base", "HEAD", "--head", "HEAD"])
        self.assertEqual((r.returncode, json.loads(r.stdout)),
                         (0, {"stack": "python", "project_dir": "pkg", "error": None, "target_os": "linux"}))

    def test_run_from_a_subdir_the_project_dir_is_still_relative_to_the_repo_root(self):
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(os.path.join(self.repo, "pkg"))
        r = _kit.run_cli(["resolve", "--base", "HEAD", "--head", "HEAD"])
        self.assertEqual((r.returncode, json.loads(r.stdout)),
                         (0, {"stack": "python", "project_dir": "pkg", "error": None, "target_os": "linux"}))

    def test_an_explicit_stack_passes_the_callers_project_dir_through(self):
        r = _kit.run_cli(["resolve", "--repo", self.repo, "--base", "HEAD", "--head", "HEAD", "--stack", "rust",
                          "--project-dir", "crates/x"])
        self.assertEqual((r.returncode, json.loads(r.stdout)),
                         (0, {"stack": "rust", "project_dir": "crates/x", "error": None, "target_os": "linux"}))


if __name__ == "__main__":
    unittest.main()
