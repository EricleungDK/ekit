"""scripts/mech-summary.py (#122): the merged R3 line says what its count stands for, tested/total per risk class,
when the cap cut the run; a result without the counts (an older engine's) prints as before."""
import os
import unittest

import test_mech_summary as summary

SHARD0 = {"branch": {"tested": 1, "total": 1}, "string": {"tested": 0, "total": 2}}
SHARD1 = {"branch": {"tested": 1, "total": 1}, "return": {"tested": 1, "total": 1}}


class TestRiskLine(summary.Run):
    def capped(self, risks):
        self.put("mech-review-json", "mech-review.json", summary.env("r2", {"R2": ("pass", "0 fail")}))
        self.put("mech-review-red-json", "mech-review-red.json",
                 summary.env("red", {"R1": ("pass", "ok"), "R4": ("pass", "ok")}))
        self.put("mech-review-baseline-json", "mech-review-baseline.json", summary.baseline(2))
        for k, (risk, tested, total) in enumerate(risks):
            s = summary.shard(k, f"{tested}/{total} tested", status="partial", tested=tested, total=total)
            if risk is not None:
                s["checks"]["R3"]["by_risk"] = risk
            self.put(f"mech-review-mutants-{k}", "mech-review-mutants.json", s)

    def test_the_r3_line_counts_tested_over_total_per_risk_class(self):
        self.capped([(SHARD0, 1, 3), (SHARD1, 2, 2)])
        r = self.main("555")
        self.assertIn("R3 partial (3/5 tested; by risk class: branch conditions 2/2, returns 1/1, "
                      "strings and arguments 0/2)", r.stdout.splitlines(), r.stdout)

    def test_a_shard_without_the_counts_prints_the_count_alone(self):
        self.capped([(SHARD0, 1, 3), (None, 2, 2)])
        r = self.main("555")
        self.assertIn("R3 partial (3/5 tested)", r.stdout.splitlines(), r.stdout)

    def test_a_shard_with_no_artifact_leaves_no_counts(self):
        # the summary merges only the shards it found: shard 1's artifact is missing, so its counts are too
        self.capped([(SHARD0, 1, 3), (SHARD1, 2, 2)])
        os.remove(os.path.join(self.art, "mech-review-mutants-1", "mech-review-mutants.json"))
        out = self.main("555").stdout.splitlines()
        r3 = [x for x in out if x.startswith("R3 ")]
        self.assertEqual(len(r3), 1, out)
        self.assertNotIn("by risk class", r3[0])

    def test_a_merged_result_whose_counts_do_not_add_up_prints_the_count_alone(self):
        self.capped([(SHARD0, 1, 3), (SHARD1, 2, 2)])
        merged = summary.env("mutants", {"R3": ("partial", "3/5 tested")}, tested=3, total=5,
                             by_risk={"branch": {"tested": 100, "total": 10 ** 12}})
        self.put("mech-review-mutants-merged-json", "mutants-merged.json", merged)
        r = self.main("555")
        self.assertIn("R3 partial (3/5 tested)", r.stdout.splitlines(), r.stdout)

    def test_a_merged_result_whose_counts_add_up_prints_them(self):
        self.capped([(SHARD0, 1, 3), (SHARD1, 2, 2)])
        merged = summary.env("mutants", {"R3": ("partial", "3/5 tested")}, tested=3, total=5,
                             by_risk={"rest": {"tested": 3, "total": 5}})
        self.put("mech-review-mutants-merged-json", "mutants-merged.json", merged)
        r = self.main("555")
        self.assertIn("R3 partial (3/5 tested; by risk class: rest 3/5)", r.stdout.splitlines(), r.stdout)


if __name__ == "__main__":
    unittest.main()
