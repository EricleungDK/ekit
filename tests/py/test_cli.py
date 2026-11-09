import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import cli


class TestAgentPrefixFlag(unittest.TestCase):
    def parse(self, *extra):
        return cli.build_parser().parse_args(["red", "--base", "a", "--head", "b", "--stack", "python", *extra]).agent_prefix

    def test_unset_is_none_so_the_engine_uses_its_default_list(self):
        self.assertIsNone(self.parse())

    def test_the_flag_repeats(self):
        self.assertEqual(self.parse("--agent-prefix", "bot/", "--agent-prefix", "ai/"), ["bot/", "ai/"])

    def test_help_lists_the_default_prefixes(self):
        self.assertIn("agent/ claude/ codex/ copilot/ cursor/", " ".join(cli.build_parser().format_help().split()))


class TestMain(unittest.TestCase):
    """The flag reaches R1 through main(): a docs-only repo, so past the branch gate R1 says no production file changed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        for step in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "base"]):
            subprocess.run(["git", "-C", self.repo, "-c", "user.email=t@t", "-c", "user.name=t", *step], check=True)
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("docs\n")
        for step in (["add", "-A"], ["commit", "-q", "-m", "head"]):
            subprocess.run(["git", "-C", self.repo, "-c", "user.email=t@t", "-c", "user.name=t", *step], check=True)

    def r1_note(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["r2", "--repo", self.repo, "--base", "HEAD~1", "--head", "HEAD", "--stack", "python"])
        self.assertEqual(rc, 0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["red", "--repo", self.repo, "--base", "HEAD~1", "--head", "HEAD", "--stack", "python", *extra])
        return json.loads(out.getvalue())["checks"]["R1"]["note"]

    def test_a_copilot_branch_passes_the_default_gate(self):
        self.assertEqual(self.r1_note("--head-branch", "copilot/fix-1"), "no production file changed")

    def test_a_given_prefix_replaces_the_default(self):
        self.assertEqual(self.r1_note("--head-branch", "copilot/fix-1", "--agent-prefix", "bot/"),
                         "branch copilot/fix-1 does not match an agent prefix (bot/)")
        self.assertEqual(self.r1_note("--head-branch", "bot/fix-1", "--agent-prefix", "bot/,ai/"), "no production file changed")


if __name__ == "__main__":
    unittest.main()
