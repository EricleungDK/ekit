"""The mutants job reports one R3 for all its shards: fail > n/a > partial > skipped > pass. A shard that could not run
must never read as a pass because another shard passed."""
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import merge

BASE, HEAD = "b" * 40, "a" * 40


def shard(status, note="", **counts):
    """A shard's envelope with nothing but its R3 check."""
    return {"base": BASE, "head": HEAD, "summary": "", "entries": [],
            "checks": {"R3": dict({"status": status, "note": note}, **counts)}}


def merged(*shards):
    return merge.combine_shards(BASE, HEAD, len(shards), dict(enumerate(shards)), {})


class TestShardStatus(unittest.TestCase):
    def test_a_shard_that_could_not_run_beside_a_passing_one_is_na(self):
        env = merged(shard("pass"), shard("n/a"))
        self.assertEqual(env["checks"]["R3"]["status"], "n/a")
        self.assertEqual(env["summary"], f"pass {HEAD} (0 fail, 0 confirm; ran: none; skipped: R1 R2 R4; n/a: R3)")

    def test_a_failing_shard_outranks_one_that_could_not_run(self):
        self.assertEqual(merged(shard("n/a"), shard("fail"))["checks"]["R3"]["status"], "fail")

    def test_a_shard_that_could_not_run_outranks_a_partial_one_and_leaves_no_partial_entry(self):
        env = merged(shard("partial", tested=1, total=4), shard("n/a"))
        self.assertEqual(env["checks"]["R3"]["status"], "n/a")
        self.assertEqual(env["entries"], [])

    def test_a_partial_shard_beside_a_passing_one_is_partial_with_one_confirm_entry(self):
        env = merged(shard("pass", tested=2, total=2), shard("partial", tested=1, total=4))
        self.assertEqual(env["checks"]["R3"]["status"], "partial")
        self.assertEqual([(e["severity"], e["problem"]) for e in env["entries"]],
                         [("confirm", "R3 partial: 3/6 mutants untested: left unrun by the mutation tool")])

    def test_every_shard_skipped_is_skipped(self):
        self.assertEqual(merged(shard("skipped"), shard("skipped"))["checks"]["R3"]["status"], "skipped")

    def test_a_skipped_shard_beside_a_passing_one_is_pass(self):
        self.assertEqual(merged(shard("skipped"), shard("pass"))["checks"]["R3"]["status"], "pass")

    def test_the_note_names_each_shard(self):
        env = merged(shard("pass", "2/2 tested"), shard("n/a", "tool exit 1 (env)"))
        self.assertEqual(env["checks"]["R3"]["note"], "shard 0/2: 2/2 tested; shard 1/2: tool exit 1 (env)")


class TestShardCounts(unittest.TestCase):
    def test_tested_and_total_are_summed_over_the_shards(self):
        check = merged(shard("pass", tested=2, total=3), shard("pass", tested=4, total=5))["checks"]["R3"]
        self.assertEqual((check["tested"], check["total"]), (6, 8))

    def test_one_unknown_total_makes_the_sum_unknown(self):
        check = merged(shard("partial", tested=2, total=None), shard("pass", tested=4, total=5))["checks"]["R3"]
        self.assertEqual((check["tested"], check["total"]), (6, None))

    def test_no_shard_with_a_count_gives_no_count(self):
        self.assertEqual(merged(shard("n/a"), shard("n/a"))["checks"]["R3"], {
            "status": "n/a", "note": "shard 0/2: ; shard 1/2: "})


class TestMissingShard(unittest.TestCase):
    def test_a_shard_with_no_result_fails_r3_and_is_named(self):
        env = merge.combine_shards(BASE, HEAD, 2, {0: shard("pass"), 1: None}, {1: "no result file given"})
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertEqual([(e["check"], e["class"], e["severity"], e["problem"]) for e in env["entries"]],
                         [("CI", "env", "fail", "mutants shard 1/2 produced no result: no result file given")])


def job_env(checks, entries=()):
    full = {c: {"status": "skipped", "note": "not run"} for c in ("R1", "R2", "R3", "R4")}
    full.update(checks)
    return {"base": BASE, "head": HEAD, "summary": "", "entries": list(entries), "checks": full}


class TestDriftJob(unittest.TestCase):
    """The drift job owns check D (#56): merged in when its envelope holds it, absent when the repo has no plan."""

    R2 = {"R2": {"status": "pass", "note": "0 fail, 0 confirm"}}

    def test_no_plan_leaves_the_merged_result_as_it_was(self):
        alone = merge.merge({"r2": job_env(self.R2)}, {})
        both = merge.merge({"r2": job_env(self.R2), "drift": job_env({})}, {})
        self.assertNotIn("D", both["checks"])
        self.assertEqual((both["checks"], both["entries"], both["summary"]), (alone["checks"], alone["entries"],
                                                                              alone["summary"]))

    def test_the_drift_check_and_its_entry_are_kept(self):
        d = {"status": "fail", "note": "judged by the base branch's plan", "messages": ["planned stack `web` (web): x"]}
        e = {"id": "D-0a1b2c3d", "check": "D", "class": "adapter-fix", "severity": "fail", "file": ".ekit/stack-plan.toml",
             "line": 0, "problem": "p", "hint": "h", "forbidden": "f"}
        env = merge.merge({"r2": job_env(self.R2), "drift": job_env({"D": d}, [e])}, {})
        self.assertEqual(env["checks"]["D"], d)
        self.assertEqual(env["entries"], [e])
        self.assertEqual(env["summary"], f"fail {HEAD} (1 fail, 0 confirm; ran: R2 D; skipped: R1 R3 R4)")

    def test_a_drift_job_with_no_result_fails_d_with_a_ci_entry(self):
        env = merge.merge({"r2": job_env(self.R2), "drift": None}, {"drift": "no JSON from the job"})
        self.assertEqual(env["checks"]["D"]["status"], "fail")
        [ci] = env["entries"]
        self.assertEqual((ci["check"], ci["problem"]), ("CI", "drift job produced no result: no JSON from the job"))


if __name__ == "__main__":
    unittest.main()
