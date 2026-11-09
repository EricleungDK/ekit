import os
import subprocess
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts scripts/ on sys.path
from mech_review import engine, red


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


class TestPrefixList(unittest.TestCase):
    def test_default_covers_the_harness_branch_prefixes(self):
        self.assertEqual(red.agent_prefixes(None), ["agent/", "claude/", "codex/", "copilot/", "cursor/"])

    def test_one_value_is_split_on_commas_and_whitespace(self):
        self.assertEqual(red.agent_prefixes("bot/, ai/\nx/"), ["bot/", "ai/", "x/"])

    def test_repeated_values_are_joined_in_order(self):
        self.assertEqual(red.agent_prefixes(["bot/", "ai/,x/"]), ["bot/", "ai/", "x/"])

    def test_an_empty_value_falls_back_to_the_default(self):
        self.assertEqual(red.agent_prefixes(" , "), list(red.AGENT_PREFIXES))


class TestR1Branch(unittest.TestCase):
    """R1's branch gate, on a docs-only change: past the gate the note is `no production file changed`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("one\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("two\n")
        git(self.repo, "commit", "-q", "-am", "head")

    def tearDown(self):
        self.tmp.cleanup()

    def r1(self, branch, **kw):
        env = engine.run(self.repo, "HEAD~1", "HEAD", "python", ["tests/**"], which="red", head_branch=branch,
                         runner=lambda argv, cwd: (0, ""), **kw)
        return env["checks"]["R1"]

    def test_a_claude_branch_is_an_agent_branch_by_default(self):
        self.assertEqual(self.r1("claude/fix-login"), {"status": "skipped", "note": "no production file changed"})

    def test_codex_copilot_cursor_and_agent_branches_too(self):
        for branch in ("codex/x", "copilot/x", "cursor/x", "agent/x"):
            self.assertEqual(self.r1(branch)["note"], "no production file changed", branch)

    def test_a_human_branch_skips_r1_and_names_the_prefixes(self):
        self.assertEqual(self.r1("feature/login"), {
            "status": "skipped",
            "note": "branch feature/login does not match an agent prefix (agent/ claude/ codex/ copilot/ cursor/)"})

    def test_a_set_prefix_replaces_the_default(self):
        self.assertEqual(self.r1("claude/x", agent_prefix=["bot/"])["note"],
                         "branch claude/x does not match an agent prefix (bot/)")
        self.assertEqual(self.r1("bot/x", agent_prefix=["bot/"])["note"], "no production file changed")

    def test_star_matches_every_branch(self):
        self.assertEqual(self.r1("feature/login", agent_prefix="*")["note"], "no production file changed")

    def test_a_prefix_matches_the_start_only(self):
        self.assertEqual(self.r1("my/claude/x")["status"], "skipped")
        self.assertIn("does not match", self.r1("my/claude/x")["note"])


if __name__ == "__main__":
    unittest.main()
