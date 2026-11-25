"""ekit's own co-change rules (#86): `.ekit/co-change.toml` in this repo says a behaviour change (a change under
`scripts/`) updates each of the changelog, the testing standard's status line and the CI doc: three rules, one per doc.
The rule file is this checkout's, put on the base of a PR-shaped fixture repo (R2 reads the rules at the base) and run
through `cli.main` in-process."""
import json
import os
import tempfile
import unittest

import _kit
from test_adapter_cli import Repo

RULE_FILE = os.path.join(_kit.ROOT, ".ekit", "co-change.toml")
DOCS = ("CHANGELOG.md", "docs/testing-standard.md", "docs/mech-review-ci.md")
CHANGELOG_REASON = ("a behaviour change (a change under scripts/) adds its line to the ## Unreleased section of "
                    "CHANGELOG.md")
STATUS_REASON = "a behaviour change (a change under scripts/) updates the status line of docs/testing-standard.md"
CI_DOC_REASON = ("a behaviour change (a change under scripts/) updates docs/mech-review-ci.md, which describes the "
                 "engine's CI inputs and per-stack behaviour")


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

    def r2_entries(self, env):
        return [(e["severity"], e["class"], e["file"], e["problem"]) for e in env["entries"] if e["check"] == "R2"]

    def test_a_pr_that_changes_scripts_and_none_of_the_docs_shows_one_confirm_entry_per_doc(self):
        env = self.run_check({"scripts/mech_review/r2.py": "X = 2\n"})
        self.assertEqual(self.r2_entries(env), [  # in id order
            ("confirm", "agent-fixable", ".ekit/co-change.toml",
             "co-change rule `behaviour-status-line`: `scripts/mech_review/r2.py` changed, and none of "
             f"`docs/testing-standard.md` did: {STATUS_REASON}"),
            ("confirm", "agent-fixable", ".ekit/co-change.toml",
             "co-change rule `behaviour-changelog`: `scripts/mech_review/r2.py` changed, and none of `CHANGELOG.md` "
             f"did: {CHANGELOG_REASON}"),
            ("confirm", "agent-fixable", ".ekit/co-change.toml",
             "co-change rule `behaviour-ci-doc`: `scripts/mech_review/r2.py` changed, and none of "
             f"`docs/mech-review-ci.md` did: {CI_DOC_REASON}")])
        self.assertEqual([e["hint"] for e in env["entries"]], [
            "change one of `docs/testing-standard.md` in this range as the rule asks (it came from b57480eb189e); a "
            "rule that misfires is changed in a PR of its own",
            "change one of `CHANGELOG.md` in this range as the rule asks (it came from b57480eb189e); a rule that "
            "misfires is changed in a PR of its own",
            "change one of `docs/mech-review-ci.md` in this range as the rule asks (it came from b57480eb189e); a rule "
            "that misfires is changed in a PR of its own"])
        self.assertEqual(env["summary"].split()[0], "pass")  # confirm: listed, never blocking

    def test_a_pr_that_changes_scripts_and_two_of_the_docs_shows_the_entry_of_the_third(self):
        env = self.run_check({"scripts/ci-local.py": "Y = 2\n", "CHANGELOG.md": "# doc\n- the change\n",
                              "docs/testing-standard.md": "# doc\n- the change\n"})
        self.assertEqual(self.r2_entries(env), [
            ("confirm", "agent-fixable", ".ekit/co-change.toml",
             "co-change rule `behaviour-ci-doc`: `scripts/ci-local.py` changed, and none of `docs/mech-review-ci.md` "
             f"did: {CI_DOC_REASON}")])

    def test_a_pr_that_changes_scripts_and_updates_the_three_docs_shows_none(self):
        env = self.run_check({"scripts/mech_review/r2.py": "X = 2\n", "CHANGELOG.md": "# doc\n- the change\n",
                              "docs/testing-standard.md": "# doc\n- the change\n",
                              "docs/mech-review-ci.md": "# doc\n- the change\n"})
        self.assertEqual(env["entries"], [])

    def test_a_pr_that_changes_no_script_shows_none(self):
        env = self.run_check({"README.md": "hello\n", "tests/py/test_b.py": "def test_b():\n    assert 2\n"})
        self.assertEqual(env["entries"], [])

    def test_the_pr_that_adds_the_rules_proves_their_six_cases_in_r0(self):
        env = self.run_check({".ekit/co-change.toml": ekit_rules()}, check="r0", base_rules=False)
        c = env["checks"]["R0"]
        self.assertEqual([(x["case"], x["status"]) for x in c["co-change"]],
                         [("behaviour-changelog:flagged", "pass"), ("behaviour-changelog:control", "pass"),
                          ("behaviour-status-line:flagged", "pass"), ("behaviour-status-line:control", "pass"),
                          ("behaviour-ci-doc:flagged", "pass"), ("behaviour-ci-doc:control", "pass")])
        self.assertEqual(c["note"].rsplit("; ", 1)[1], "co-change rules: 3 of 3 proved")
        self.assertEqual(env["entries"], [])


if __name__ == "__main__":
    unittest.main()
