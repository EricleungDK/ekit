"""R0 (#20) in the job merge, the PR comment and the waivers: the guard's R0 result is its own job (`r0`), a failed R0
blocks the checks it names in every job's result, the comment shows R0, and a person can waive the R0 entry."""
import json
import unittest

import _kit
from scripts.mech_review import comment, merge, waiver

from test_r0 import broken_python_fixtures, tmp_repo


def envelopes(case, fixtures=None):
    """{job: envelope} of the guard's r0 and r2 steps on one PR that removes a test."""
    repo, _ = tmp_repo(case)
    base = repo.commit({"tests/test_a.py": "def test_a():\n    assert 1 == 1\n"})
    head = repo.commit({"tests/test_a.py": "def test_b():\n    assert 2 == 2\n"})
    common = ["--repo", repo.path, "--base", base, "--head", head, "--stack", "python", "--test-paths", "tests/**"]
    r0 = _kit.run_cli(["r0", *common] + (["--fixtures", fixtures] if fixtures else []))
    r2 = _kit.run_cli(["r2", *common])
    return {"r0": json.loads(r0.stdout), "r2": json.loads(r2.stdout)}, head


class Merge(unittest.TestCase):
    def test_a_failed_r0_blocks_r2_in_the_merged_result_and_keeps_its_one_entry(self):
        parts, head = envelopes(self, broken_python_fixtures(self))
        env = merge.merge(parts, {})
        self.assertEqual(sorted((e["check"], e["class"], e.get("blocked")) for e in env["entries"]),
                         [("R0", "adapter-fix", None), ("R2", "agent-fixable", "R0")])
        self.assertEqual(env["checks"]["R2"]["status"], "n/a")
        self.assertTrue(env["checks"]["R2"]["note"].startswith("blocked: R0 failed (R0 static half failed"))
        self.assertEqual(env["summary"], f"fail {head} (2 fail, 0 confirm; ran: R0; skipped: R1 R3 R4; n/a: R2)")

    def test_a_passed_r0_leaves_the_other_jobs_as_they_are(self):
        parts, head = envelopes(self)
        env = merge.merge(parts, {})
        self.assertEqual(env["checks"]["R0"]["status"], "pass")
        self.assertEqual([(e["check"], e["problem"]) for e in env["entries"]], [("R2", "test fn `test_a` removed")])
        self.assertEqual(env["summary"], f"fail {head} (1 fail, 0 confirm; ran: R0 R2; skipped: R1 R3 R4)")

    def test_a_named_r0_job_with_no_result_fails_r0_with_a_ci_entry(self):
        parts, _ = envelopes(self)
        env = merge.merge({"r2": parts["r2"], "r0": None}, {"r0": "no JSON"})
        self.assertEqual(env["checks"]["R0"]["status"], "fail")
        self.assertIn(("CI", "r0 job produced no result: no JSON"), [(e["check"], e["problem"]) for e in env["entries"]])

    def test_no_r0_job_means_no_r0(self):
        parts, _ = envelopes(self)
        self.assertNotIn("R0", merge.merge({"r2": parts["r2"]}, {})["checks"])


class Comment(unittest.TestCase):
    def test_the_comment_shows_r0_its_blocked_checks_and_a_ready_made_waiver_line(self):
        parts, _ = envelopes(self, broken_python_fixtures(self))
        env = merge.merge(parts, {})
        eid = next(e["id"] for e in env["entries"] if e["check"] == "R0")
        body = comment.render(env)
        self.assertIn("R0: `static half: 10 of 11 cases proved; failed: skip`", body)
        self.assertIn("Did not run: R2 (blocked: R0 failed (", body)
        self.assertIn(f"/mech-waive {eid} {waiver.PLACEHOLDER}", body)
        self.assertIn("| fail (R2 blocked by R0) |", body)
        self.assertEqual(comment.exit_code(env), 1)


class Waive(unittest.TestCase):
    """C8: a person can waive the R0 entry (the emergency exit while the adapter repair is pending)."""

    def test_a_person_waives_the_r0_entry(self):
        parts, head = envelopes(self, broken_python_fixtures(self))
        env = merge.merge(parts, {})
        eid = next(e["id"] for e in env["entries"] if e["check"] == "R0")
        comments = [{"user": {"login": "owner", "type": "User"}, "author_association": "OWNER",
                     "body": f"/mech-waive {eid} urgent fix; the adapter repair is pending", "html_url": "u",
                     "created_at": "t", "updated_at": "t"}]
        out = waiver.apply(env, waiver.collect(comments))
        self.assertEqual([(e["check"], e["severity"]) for e in out["entries"]], [("R0", "waived"), ("R2", "fail")]
                         if out["entries"][0]["check"] == "R0" else [("R2", "fail"), ("R0", "waived")])
        self.assertEqual(out["checks"]["R0"]["status"], "waived")
        # the blocked check's own fail entry still needs its own waiver (#20 review): waiving R0 never passes it
        self.assertEqual(out["summary"], f"fail {head} (1 fail, 0 confirm, 1 waived; ran: R0; skipped: R1 R3 R4; n/a: R2)")
        self.assertEqual(comment.exit_code(out), 1)


if __name__ == "__main__":
    unittest.main()
