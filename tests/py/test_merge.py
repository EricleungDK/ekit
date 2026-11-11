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
                         [("confirm", "R3 partial: 3/6 mutants untested at budget")])

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


if __name__ == "__main__":
    unittest.main()
