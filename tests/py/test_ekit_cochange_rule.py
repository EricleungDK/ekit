"""ekit's own co-change rule (#86): `.ekit/co-change.toml` in this repo says a behaviour change (a change under
`scripts/`) updates the changelog, the testing standard's status line or the CI doc. The rule file is this checkout's,
put on the base of a PR-shaped fixture repo (R2 reads the rules at the base) and run through `cli.main` in-process."""
import json
import os
import tempfile
import unittest

import _kit
from test_adapter_cli import Repo

RULE_FILE = os.path.join(_kit.ROOT, ".ekit", "co-change.toml")
DOCS = ("CHANGELOG.md", "docs/testing-standard.md", "docs/mech-review-ci.md")
REASON = ("a behaviour change updates CHANGELOG.md (## Unreleased), the status line of docs/testing-standard.md and "
          "docs/mech-review-ci.md, as AGENTS.md asks")


def ekit_rules():
    with open(RULE_FILE, encoding="utf-8") as f:
        return f.read()


class EkitRule(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(tmp.name)

    def run_check(self, head_files, check="r2", base_rules=True):
        files = {"scripts/mech_review/r2.py": "X = 1\n", "scripts/ci-local.py": "Y = 1\n", "README.md": "hi\n",
                 "tests/py/test_a.py": "def test_a():\n    assert 1\n", **{d: "# doc\n" for d in DOCS}}
        if base_rules:
            files[".ekit/co-change.toml"] = ekit_rules()
        base = self.repo.commit(files, "base")
        head = self.repo.commit(head_files, "head")
        r = _kit.run_cli([check, "--repo", self.repo.path, "--base", base, "--head", head, "--stack", "python",
                          "--test-paths", "tests/**", "--test-paths", ".ekit/scenarios/**"])
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_a_pr_that_changes_scripts_and_none_of_the_three_docs_shows_the_rules_confirm_entry(self):
        for changed, named in ((["scripts/mech_review/r2.py"], "`scripts/mech_review/r2.py` changed"),
                               (["scripts/ci-local.py"], "`scripts/ci-local.py` changed"),
                               (["scripts/ci-local.py", "scripts/mech_review/r2.py", "README.md"],
                                "`scripts/ci-local.py` and 1 more changed")):
            with self.subTest(changed=changed):
                self.setUp()
                env = self.run_check({p: "Z = 2\n" for p in changed})
                got = [e for e in env["entries"] if e["check"] == "R2"]
                self.assertEqual([(e["severity"], e["class"], e["file"], e["problem"]) for e in got],
                                 [("confirm", "agent-fixable", ".ekit/co-change.toml",
                                   f"co-change rule `behaviour-docs`: {named}, and none of `CHANGELOG.md`, "
                                   f"`docs/testing-standard.md`, `docs/mech-review-ci.md` did: {REASON}")])
                self.assertIn("(it came from b57480eb189e)", got[0]["hint"])
                self.assertTrue(env["summary"].startswith("pass "), env["summary"])  # confirm: listed, never blocking

    def test_a_pr_that_changes_scripts_and_updates_the_docs_shows_none(self):
        env = self.run_check({"scripts/mech_review/r2.py": "X = 2\n", **{d: "# doc\n- the change\n" for d in DOCS}})
        self.assertEqual(env["entries"], [])

    def test_a_pr_that_changes_no_script_shows_none(self):
        env = self.run_check({"README.md": "hello\n", "tests/py/test_b.py": "def test_b():\n    assert 2\n"})
        self.assertEqual(env["entries"], [])

    def test_the_pr_that_adds_the_rule_proves_its_two_cases_in_r0(self):
        env = self.run_check({".ekit/co-change.toml": ekit_rules()}, check="r0", base_rules=False)
        c = env["checks"]["R0"]
        self.assertEqual([(x["case"], x["status"]) for x in c["co-change"]],
                         [("behaviour-docs:flagged", "pass"), ("behaviour-docs:control", "pass")])
        self.assertTrue(c["note"].endswith("; co-change rules: 1 of 1 proved"), c["note"])
        self.assertEqual(env["entries"], [])


if __name__ == "__main__":
    unittest.main()
