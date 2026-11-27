"""#122 deep R3 pass: the per-class counts of the python paths a 40-mutant CI pick never reaches, a listing the budget
cut and a shard with no share outside the cap, and the tie order of a function with ten or more mutants."""
import unittest

import test_r3_cap as cap

# cap.PY_MUTANTS by class: branch 1 and 5, return 4, arithmetic 2, string 3; the cap of 3 takes 1, 5 and 4
NONE_TESTED = {"branch": {"tested": 0, "total": 2}, "return": {"tested": 0, "total": 1},
               "arithmetic": {"tested": 0, "total": 1}, "string": {"tested": 0, "total": 1}}


class TestPythonListingCutByTheBudget(cap.PyRepo):
    def test_an_unsharded_run_whose_listing_the_budget_ends_counts_each_class_untested(self):
        # the budget ends step 1: the riskiest 3 are dealt from what mutmut listed, and none of them ran
        check, _ = self.r3(cap.CopyingMutmut(list_timeout=True), cap=3)
        self.assertEqual((check["status"], check["tested"], check["total"]), ("partial", 0, 5))
        self.assertEqual(check["by_risk"], NONE_TESTED)
        self.assertTrue(check["note"].endswith("; by risk class, tested/total: branch conditions 0/2, returns 0/1, "
                                               "arithmetic 0/1, strings and arguments 0/1"), check["note"])


class TestPythonEmptyShardWithinTheCap(cap.PyRepo):
    def test_a_shard_with_no_share_of_an_uncapped_run_has_no_counts(self):
        check, entries = self.r3(cap.CopyingMutmut(), shard="5/6")  # 5 mutants, under the cap of 40, over 6 shards
        self.assertEqual((check["status"], check["tested"], check["total"], entries), ("pass", 0, 0, []))
        self.assertEqual(check["note"], "0 mutants in this shard")
        self.assertNotIn("by_risk", check)


# eleven mutants of one class (a string each): their tie order is by mutant number, 2 before 10
MANY = {n: cap.PY_ORIG.replace('"x"', f'"x{n}"') for n in range(1, 12)}


class TestPythonTieOrderPastNine(cap.PyRepo):
    def test_mutants_of_one_class_and_function_go_by_their_number_not_its_text(self):
        fake = cap.CopyingMutmut(mutants=MANY)
        check, _ = self.r3(fake, cap=2)
        self.assertEqual(fake.ran, {cap.PY_NAME(1), cap.PY_NAME(2)})
        self.assertEqual(check["by_risk"], {"string": {"tested": 2, "total": 11}})


if __name__ == "__main__":
    unittest.main()
