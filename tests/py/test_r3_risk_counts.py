"""R3's tested versus untested counts per risk class (#122): what `40/599` stands for. A run the cap cut says, by risk
class, how many of its mutants were tested out of how many on the changed lines (checks.R3.by_risk, and its note);
the shards' counts add up in the merge; the sticky comment shows them in one line. Engine calls are in-process."""
import json
import os
import tempfile
import unittest
from unittest import mock

import _kit
import test_r3_cap as cap
import test_r3_unconfirmed as unconfirmed
from scripts.mech_review import comment
from scripts.mech_review.report import summarize

# cap.PY_MUTANTS by class: branch 1 and 5, return 4, arithmetic 2, string 3; the cap of 3 takes 1, 5 and 4
PY_CAP3 = {"branch": {"tested": 2, "total": 2}, "return": {"tested": 1, "total": 1},
           "arithmetic": {"tested": 0, "total": 1}, "string": {"tested": 0, "total": 1}}
PY_CAP3_TEXT = "branch conditions 2/2, returns 1/1, arithmetic 0/1, strings and arguments 0/1"


def save(dirname, name, env):
    path = os.path.join(dirname, name)
    with open(path, "w") as f:
        json.dump(env, f)
    return path


class TestPythonRiskCounts(cap.PyCli):
    def side(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return d.name

    def test_a_capped_run_counts_tested_over_total_per_risk_class(self):
        r3 = self.cli("mutants", "--max-mutants", "3")["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 3, 5))
        self.assertEqual(r3["by_risk"], PY_CAP3)
        self.assertTrue(r3["note"].endswith("2 past the cap (max-mutants 3): untested; by risk class, tested/total: "
                                            + PY_CAP3_TEXT), r3["note"])

    def test_a_run_within_the_cap_is_unchanged(self):
        r3 = self.cli("mutants")["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("pass", 5, 5))
        self.assertNotIn("by_risk", r3)
        self.assertNotIn("by risk class", r3["note"])

    def test_the_shards_counts_add_up_in_the_merge_and_are_not_multiplied(self):
        d, files = self.side(), []
        shards = []
        for k in range(2):
            env = self.cli("mutants", "--shard", f"{k}/2", "--max-mutants", "3")
            shards.append(env["checks"]["R3"]["by_risk"])
            files += ["--envelope", f"{k}={save(d, f's{k}.json', env)}"]
        # shard 0 runs mutants 1 and 4 and holds the 2 past the cap; shard 1 runs mutant 5
        self.assertEqual(shards, [{"branch": {"tested": 1, "total": 1}, "return": {"tested": 1, "total": 1},
                                   "arithmetic": {"tested": 0, "total": 1}, "string": {"tested": 0, "total": 1}},
                                  {"branch": {"tested": 1, "total": 1}}])
        r3 = self.cli("merge", "--shards", "2", *files)["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 3, 5))
        self.assertEqual(r3["by_risk"], PY_CAP3)
        self.assertTrue(r3["note"].endswith("; all shards, by risk class, tested/total: " + PY_CAP3_TEXT), r3["note"])

    def test_a_shard_from_an_older_engine_still_merges_without_the_counts(self):
        d, files = self.side(), []
        for k in range(2):
            env = self.cli("mutants", "--shard", f"{k}/2", "--max-mutants", "3")
            if k == 1:
                del env["checks"]["R3"]["by_risk"]
            files += ["--envelope", f"{k}={save(d, f's{k}.json', env)}"]
        r3 = self.cli("merge", "--shards", "2", *files)["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 3, 5))
        self.assertNotIn("by_risk", r3)  # a sum without one shard's counts would undercount
        self.assertNotIn("all shards, by risk class", r3["note"])

    def test_a_malformed_count_is_not_summed(self):
        d, files = self.side(), []
        for k in range(2):
            env = self.cli("mutants", "--shard", f"{k}/2", "--max-mutants", "3")
            if k == 1:
                env["checks"]["R3"]["by_risk"] = {"branch": {"tested": True, "total": "1"}}
            files += ["--envelope", f"{k}={save(d, f's{k}.json', env)}"]
        r3 = self.cli("merge", "--shards", "2", *files)["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 3, 5))
        self.assertNotIn("by_risk", r3)


class TestPythonRiskCountsOfAShortRun(cap.PyRepo):
    """the mutants run (cap.run, in-process) under a budget: the counts are the check's own."""

    def test_a_budget_hit_counts_what_ran(self):
        check, _ = self.r3(cap.CopyingMutmut(run_timeout=True), cap=3)
        self.assertEqual((check["status"], check["tested"], check["total"]), ("partial", 3, 5))
        self.assertEqual(check["by_risk"], PY_CAP3)
        self.assertTrue(check["note"].endswith("; by risk class, tested/total: " + PY_CAP3_TEXT), check["note"])

    def test_a_shard_whose_total_is_unknown_has_no_counts(self):
        check, _ = self.r3(cap.CopyingMutmut(list_timeout=True), cap=3, shard="1/2")
        self.assertEqual((check["tested"], check["total"]), (0, None))
        self.assertNotIn("by_risk", check)
        self.assertNotIn("by risk class", check["note"])


class TestPythonRiskCountsUnconfirmed(unconfirmed.Cli):
    def test_an_unconfirmed_survivor_is_not_counted_as_tested_in_its_class(self):
        # this fake writes no mutant copies, so neither edit can be read: both are the rest, and the cap of 1 takes
        # SUB1 (the lower number); its survivor gets no whole-suite retry
        fake = self.fake({unconfirmed.SUB1: "survived", unconfirmed.SUB2: "no tests"}, list_s=30, run_s=30)
        env, _ = self.mutants_cli(fake, 1, "--max-mutants", "1")
        r3 = env["checks"]["R3"]
        self.assertEqual([e["problem"] for e in self.unconfirmed(env)],
                         [f"R3 unconfirmed survivor calc.py:6: {unconfirmed.M1}"])
        self.assertEqual((r3["tested"], r3["total"]), (0, 2))
        self.assertEqual(r3["by_risk"], {"rest": {"tested": 0, "total": 2}})


class TestRustRiskCounts(cap.RustCap):
    """cap.LISTED by class: branch GT, GUARD, NOT; return RET, FALSE; arithmetic PLUS; rest ARM."""

    def cli(self, *args, **env):
        e = dict(MECH_TEST_STUB=self.stub, STUB_LOG=self.log, STUB_LIST=self.list_path, **env)
        open(self.log, "w").close()
        with mock.patch.dict(os.environ, e):
            r = _kit.run_cli([*args, "--repo", self.repo, "--base", "HEAD~1", "--head", "HEAD", "--stack", "rust",
                              "--test-paths", "tests/**"])
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return json.loads(r.stdout)

    def test_a_capped_run_counts_tested_over_total_per_risk_class(self):
        r3 = self.cli("mutants", "--max-mutants", "4")["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 4, 7))
        self.assertEqual(r3["by_risk"], {"branch": {"tested": 3, "total": 3}, "return": {"tested": 1, "total": 2},
                                         "arithmetic": {"tested": 0, "total": 1}, "rest": {"tested": 0, "total": 1}})
        self.assertTrue(r3["note"].endswith("; by risk class, tested/total: branch conditions 3/3, returns 1/2, "
                                            "arithmetic 0/1, rest 0/1"), r3["note"])

    def test_a_run_within_the_cap_is_unchanged(self):
        r3 = self.cli("mutants")["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("pass", 7, 7))
        self.assertNotIn("by_risk", r3)

    def test_a_capped_run_whose_baseline_fails_has_no_counts(self):
        r3 = self.cli("mutants", "--max-mutants", "4", STUB_BASELINE="Failure", STUB_RC="4")["checks"]["R3"]
        self.assertEqual(r3["status"], "fail")
        self.assertNotIn("by_risk", r3)

    def test_an_empty_shard_carries_empty_counts_so_the_merge_still_sums(self):
        self.listing([cap.GT, cap.PLUS])
        r3 = self.cli("mutants", "--max-mutants", "1", "--shard", "1/2")["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"], r3["note"]), ("pass", 0, 0, "0 mutants in this shard"))
        self.assertEqual(r3["by_risk"], {})

    def test_the_shards_counts_add_up_in_the_merge(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        files = []
        for k in range(2):
            env = self.cli("mutants", "--max-mutants", "4", "--shard", f"{k}/2")
            files += ["--envelope", f"{k}={save(d.name, f's{k}.json', env)}"]
        r3 = self.cli("merge", "--shards", "2", *files)["checks"]["R3"]
        self.assertEqual(r3["by_risk"], {"branch": {"tested": 3, "total": 3}, "return": {"tested": 1, "total": 2},
                                         "arithmetic": {"tested": 0, "total": 1}, "rest": {"tested": 0, "total": 1}})


def env_with(r3):
    checks = {c: {"status": "pass", "note": ""} for c in ("R1", "R2", "R4")}
    checks["R3"] = r3
    return {"ekit": "0", "base": "b" * 40, "head": "a" * 40, "checks": checks, "entries": [],
            "summary": summarize("a" * 40, checks, [])}


class TestCommentRiskLine(unittest.TestCase):
    R3 = {"status": "partial", "note": "3/5 tested", "tested": 3, "total": 5, "timing": {"wall_s": 2.0}}

    def test_the_comment_shows_tested_over_total_per_risk_class_under_the_count(self):
        body = comment.render(env_with(dict(self.R3, by_risk=PY_CAP3)))
        lines = body.splitlines()
        at = lines.index("R3 timing: 3/5 mutants, 2s wall")
        self.assertEqual(lines[at + 1], "R3 by risk class, tested/total: " + PY_CAP3_TEXT)

    def test_a_result_without_the_counts_renders_as_before(self):
        body = comment.render(env_with(dict(self.R3)))
        self.assertIn("R3 timing: 3/5 mutants, 2s wall", body)
        self.assertNotIn("by risk class", body)

    def test_malformed_counts_are_left_out_never_a_crash(self):
        for bad in ("x", [1], {"branch": 3}, {"branch": {"tested": -1, "total": 2}}, {"nope": {"tested": 0, "total": 1}},
                    {"branch": {"tested": 3, "total": 2}}, {"branch": {"tested": False, "total": 1}}):
            body = comment.render(env_with(dict(self.R3, by_risk=bad)))
            self.assertIn("R3 timing: 3/5 mutants, 2s wall", body, bad)
            self.assertNotIn("by risk class", body.split("### JSON")[0], bad)


if __name__ == "__main__":
    unittest.main()
