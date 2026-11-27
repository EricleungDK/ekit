"""#122 review: R3's per-class counts are the check's own count split by risk class. Their tested counts add up to the
check's tested count and their totals to its total, per shard and after the merge, for any cap and shard count; counts
that do not add up are no counts (dropped when read: merge, comment). Engine calls are in-process (cli.main)."""
import json
import os
import tempfile
import unittest

import test_r3_cap as cap
import test_r3_risk_counts as counts
from scripts.mech_review import comment

N_MUTANTS = len(cap.PY_MUTANTS)  # 5


def sums(by):
    return sum(v["tested"] for v in by.values()), sum(v["total"] for v in by.values())


class Side:
    def side(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return d.name

    def save(self, d, name, env):
        path = os.path.join(d, name)
        with open(path, "w") as f:
            json.dump(env, f)
        return path


class TestPythonSums(Side, cap.PyCli):
    def run_shards(self, n, max_mutants):
        d, files, checks = self.side(), [], []
        for k in range(n):
            env = self.cli("mutants", "--shard", f"{k}/{n}", "--max-mutants", str(max_mutants))
            checks.append(env["checks"]["R3"])
            files += ["--envelope", f"{k}={self.save(d, f's{k}.json', env)}"]
        merged = self.cli("merge", "--shards", str(n), *files)["checks"]["R3"]
        return checks, merged

    def test_the_class_counts_add_up_to_the_checks_count_for_any_cap_and_shard_count(self):
        for n in (1, 2, 3):
            for max_mutants in range(1, N_MUTANTS + 2):
                capped = max_mutants < N_MUTANTS
                at = (n, max_mutants)
                checks, merged = self.run_shards(n, max_mutants)
                for k, c in enumerate(checks):
                    self.assertEqual("by_risk" in c, capped, (at, k, c))
                    if capped:
                        self.assertEqual(sums(c["by_risk"]), (c["tested"], c["total"]), (at, k))
                self.assertEqual("by_risk" in merged, capped, (at, merged))
                if capped:
                    self.assertEqual(sums(merged["by_risk"]), (merged["tested"], merged["total"]), at)
                    self.assertEqual(merged["total"], N_MUTANTS, at)
                    self.assertEqual("all shards, by risk class" in merged["note"], n > 1, (at, merged["note"]))
                else:
                    self.assertNotIn("by risk class", merged["note"], at)

    def test_a_run_of_exactly_max_mutants_has_no_counts(self):
        r3 = self.cli("mutants", "--max-mutants", str(N_MUTANTS))["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("pass", N_MUTANTS, N_MUTANTS))
        self.assertNotIn("by_risk", r3)
        self.assertNotIn("by risk class", r3["note"])

    def test_an_empty_shard_carries_empty_counts_so_the_merge_still_sums(self):
        checks, merged = self.run_shards(2, 1)
        self.assertEqual((checks[1]["tested"], checks[1]["total"], checks[1]["note"]), (0, 0, "0 mutants in this shard"))
        self.assertEqual(checks[1]["by_risk"], {})
        self.assertEqual(sums(merged["by_risk"]), (1, N_MUTANTS))

    def test_a_one_shard_merge_does_not_repeat_the_counts_in_its_note(self):
        _, merged = self.run_shards(1, 3)
        self.assertEqual(merged["note"].count("by risk class"), 1, merged["note"])

    def merged_with(self, change):
        d, files = self.side(), []
        for k in range(2):
            env = self.cli("mutants", "--shard", f"{k}/2", "--max-mutants", "3")
            if k == 1:
                change(env["checks"]["R3"])
            files += ["--envelope", f"{k}={self.save(d, f's{k}.json', env)}"]
        return self.cli("merge", "--shards", "2", *files)["checks"]["R3"]

    def test_a_shard_whose_counts_do_not_add_up_to_its_count_is_not_summed(self):
        for bad in ({"branch": {"tested": 100, "total": 10 ** 12}},  # more than the shard holds
                    {"branch": {"tested": 0, "total": 1}},            # tested short of the shard's
                    {"branch": {"tested": 1, "total": 2}}):           # total past the shard's
            r3 = self.merged_with(lambda c: c.update(by_risk=bad))
            self.assertEqual((r3["tested"], r3["total"]), (3, 5), bad)
            self.assertNotIn("by_risk", r3, bad)
            self.assertNotIn("all shards, by risk class", r3["note"], bad)

    def test_a_shard_whose_total_is_unknown_is_not_summed_whatever_its_counts(self):
        r3 = self.merged_with(lambda c: c.update(total=None))
        self.assertEqual((r3["tested"], r3["total"]), (3, None))
        self.assertNotIn("by_risk", r3)


class TestPythonGuards(Side, cap.PyCli):
    """review round 2: counts read anywhere are the check's own whole-number count, by known classes, from every
    shard of the run."""

    def shard_files(self, change=None, ks=(0, 1)):
        d, files = self.side(), []
        for k in ks:
            env = self.cli("mutants", "--shard", f"{k}/2", "--max-mutants", "3")
            if change and k == 1:
                change(env["checks"]["R3"])
            files += ["--envelope", f"{k}={self.save(d, f's{k}.json', env)}"]
        return files

    def test_a_shard_missing_from_the_merge_leaves_no_counts(self):
        r3 = self.cli("merge", "--shards", "2", *self.shard_files(ks=(0,)))["checks"]["R3"]
        self.assertEqual(r3["status"], "fail")  # the missing shard's CI entry
        self.assertNotIn("by_risk", r3)
        self.assertNotIn("all shards, by risk class", r3["note"])

    def test_a_shard_whose_counts_name_an_unknown_class_is_not_summed(self):
        # shard 1 holds one branch mutant, tested: its counts add up with the unknown class too
        def add(c):
            c["by_risk"] = {"branch": {"tested": 1, "total": 1}, "nope": {"tested": 0, "total": 0}}
        r3 = self.cli("merge", "--shards", "2", *self.shard_files(add))["checks"]["R3"]
        self.assertEqual((r3["tested"], r3["total"]), (3, 5))
        self.assertNotIn("by_risk", r3)


class TestReadersGuards(unittest.TestCase):
    R3 = {"status": "partial", "note": "3/5 tested", "timing": {"wall_s": 2.0}}

    def line(self, **r3):
        body = comment.render(counts.env_with(dict(self.R3, **r3))).split("### JSON")[0]
        return [x for x in body.splitlines() if "by risk class" in x]

    def test_control_whole_counts_that_add_up_get_the_line(self):
        self.assertEqual(self.line(tested=3, total=5, by_risk={"branch": {"tested": 3, "total": 5}}),
                         ["R3 by risk class, tested/total: branch conditions 3/5"])

    def test_a_count_that_is_not_a_whole_number_gets_no_line(self):
        for tested, total, by in ((3, 5.0, {"branch": {"tested": 3, "total": 5}}),
                                  (True, 5, {"branch": {"tested": 1, "total": 5}}),
                                  (3.0, 5, {"branch": {"tested": 3, "total": 5}}),
                                  (3, None, {"branch": {"tested": 3, "total": 5}})):
            self.assertEqual(self.line(tested=tested, total=total, by_risk=by), [], (tested, total))

    def test_an_unknown_class_gets_no_line(self):
        by = {"branch": {"tested": 3, "total": 4}, "nope": {"tested": 0, "total": 1}}
        self.assertEqual(self.line(tested=3, total=5, by_risk=by), [])


class TestRustSums(cap.RustCap):
    cli = counts.TestRustRiskCounts.cli  # in-process

    def test_a_capped_run_the_budget_stops_counts_only_what_ran(self):
        # the stub runs its first picked mutant (RET, a return) and hangs; the budget stops it
        r3 = self.cli("mutants", "--max-mutants", "4", "--mutation-budget", "0.02", STUB_HANG="1")["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 1, 7))
        self.assertEqual(r3["by_risk"], {"branch": {"tested": 0, "total": 3}, "return": {"tested": 1, "total": 2},
                                         "arithmetic": {"tested": 0, "total": 1}, "rest": {"tested": 0, "total": 1}})

    def test_a_run_of_exactly_max_mutants_has_no_counts(self):
        r3 = self.cli("mutants", "--max-mutants", str(len(cap.LISTED)))["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("pass", 7, 7))
        self.assertNotIn("by_risk", r3)


class TestCommentSums(unittest.TestCase):
    def test_counts_that_do_not_add_up_to_the_count_get_no_line(self):
        r3 = {"status": "partial", "note": "3/5 tested", "tested": 3, "total": 5, "timing": {"wall_s": 2.0}}
        for bad in ({"branch": {"tested": 100, "total": 10 ** 12}}, {"branch": {"tested": 3, "total": 4}},
                    {"branch": {"tested": 2, "total": 5}}):
            body = comment.render(counts.env_with(dict(r3, by_risk=bad))).split("### JSON")[0]
            self.assertIn("R3 timing: 3/5 mutants, 2s wall", body, bad)
            self.assertNotIn("by risk class", body, bad)
        body = comment.render(counts.env_with(dict(r3, total=None, by_risk={"branch": {"tested": 3, "total": 5}})))
        self.assertNotIn("by risk class", body.split("### JSON")[0])


if __name__ == "__main__":
    unittest.main()
