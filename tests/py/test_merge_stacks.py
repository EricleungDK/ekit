"""Several stacks from the stack plan (#17): each stack's merged result stays apart, and the report reads them as ONE
result. The same rule broken in two stacks keeps two entries with two ids (a waiver names one); any stack failing, or
a stack with no result at all, fails the whole."""
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import merge, waiver
from scripts.mech_review.report import CHECKS, envelope

BASE, HEAD = "b" * 40, "a" * 40
API = {"name": "api", "stack": "python", "project_dir": "api"}
WEB = {"name": "web", "stack": "ts", "project_dir": "web"}
PROTECTED = {"id": "R2-0badc0de", "check": "R2", "class": "needs-human", "severity": "fail", "file": ".github/ci.yml",
             "line": 0, "problem": "protected path changed", "hint": "the owner edits it", "forbidden": "editing it"}


def stack_env(r2="pass", entries=(), **more):
    checks = {c: {"status": "skipped", "note": "not run"} for c in CHECKS}
    checks["R2"] = {"status": r2, "note": ""}
    checks.update(more)
    return envelope(BASE, HEAD, list(entries), checks)


class TestStackIds(unittest.TestCase):
    def test_one_rule_broken_in_two_stacks_keeps_two_entries_with_two_ids_each_labelled(self):
        env = merge.combine_stacks([(API, stack_env("fail", [PROTECTED])), (WEB, stack_env("fail", [PROTECTED]))])
        ids = [e["id"] for e in env["entries"]]
        self.assertEqual(len(set(ids)), 2, ids)
        self.assertNotIn(PROTECTED["id"], ids)
        self.assertEqual(sorted(e["stack"] for e in env["entries"]), ["api", "web"])
        self.assertTrue(all(waiver.WAIVE.match(f"/mech-waive {i} ok") for i in ids), ids)

    def test_a_stack_entry_id_holds_across_runs_and_differs_by_stack_and_project_dir(self):
        one = merge.combine_stacks([(API, stack_env("fail", [PROTECTED]))])["entries"][0]["id"]
        again = merge.combine_stacks([(WEB, stack_env()), (API, stack_env("fail", [PROTECTED]))])["entries"][0]["id"]
        moved = merge.combine_stacks([(dict(API, project_dir="svc"), stack_env("fail", [PROTECTED]))])["entries"][0]["id"]
        self.assertEqual(one, again)
        self.assertNotEqual(one, moved)


class TestVerdict(unittest.TestCase):
    def test_one_failing_stack_fails_the_whole_and_each_stack_keeps_its_own_result(self):
        env = merge.combine_stacks([(API, stack_env()), (WEB, stack_env("fail", [PROTECTED]))])
        self.assertEqual(env["checks"]["R2"]["status"], "fail")
        self.assertTrue(env["summary"].startswith(f"fail {HEAD} (1 fail, 0 confirm;"), env["summary"])
        self.assertEqual([(s["name"], s["stack"], s["project_dir"], s["checks"]["R2"]["status"]) for s in env["stacks"]],
                         [("api", "python", "api", "pass"), ("web", "ts", "web", "fail")])
        self.assertEqual(env["stacks"][0]["summary"], f"pass {HEAD} (0 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)")

    def test_every_stack_passing_passes_and_the_note_names_each_stack(self):
        env = merge.combine_stacks([(API, stack_env()), (WEB, stack_env())])
        self.assertEqual(env["checks"]["R2"], {"status": "pass", "note": "api: pass; web: pass"})
        self.assertEqual(env["checks"]["R3"]["status"], "skipped")
        self.assertEqual(env["summary"], f"pass {HEAD} (0 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)")

    def test_a_stack_with_no_result_is_a_ci_entry_that_fails_every_check_never_a_silent_pass(self):
        env = merge.combine_stacks([(API, stack_env()), (WEB, None)])
        self.assertEqual({c: env["checks"][c]["status"] for c in CHECKS}, dict.fromkeys(CHECKS, "fail"))
        [ci] = env["entries"]
        self.assertEqual((ci["check"], ci["severity"], ci["stack"]), ("CI", "fail", "web"))
        self.assertEqual(ci["problem"], "stack web (ts in web) produced no result")
        self.assertEqual(env["stacks"][1]["checks"]["R2"]["status"], "fail")

    def test_a_check_takes_the_worst_status_of_the_stacks(self):
        r3 = lambda status: {"R3": {"status": status, "note": status}}
        for a, b, want in (("pass", "n/a", "n/a"), ("n/a", "fail", "fail"), ("partial", "pass", "partial"),
                           ("skipped", "pass", "pass"), ("waived", "pass", "waived"), ("skipped", "skipped", "skipped")):
            env = merge.combine_stacks([(API, stack_env(**r3(a))), (WEB, stack_env(**r3(b)))])
            self.assertEqual(env["checks"]["R3"]["status"], want, (a, b))

    def test_r0_and_drift_reach_the_whole_only_from_where_they_ran(self):
        r0 = {"R0": {"status": "pass", "note": "3 proved"}}
        drift = envelope(BASE, HEAD, [], dict({c: {"status": "skipped", "note": ""} for c in CHECKS},
                                              D={"status": "pass", "note": "clean", "messages": ["api: current"]}))
        env = merge.combine_stacks([(API, stack_env(**r0)), (WEB, stack_env())], drift=drift)
        self.assertEqual(env["checks"]["R0"], {"status": "pass", "note": "api: pass (3 proved)"})
        self.assertEqual(env["checks"]["D"], drift["checks"]["D"])
        self.assertNotIn("D", env["stacks"][0]["checks"])

    def test_could_not_run_ranks_above_unproven(self):
        r0 = lambda status: {"R0": {"status": status, "note": ""}}
        for a, b in (("unproven", "n/a"), ("n/a", "unproven")):
            env = merge.combine_stacks([(API, stack_env(**r0(a))), (WEB, stack_env(**r0(b)))])
            self.assertEqual(env["checks"]["R0"]["status"], "n/a", (a, b))

    def test_an_unknown_status_fails_the_check_never_passes(self):
        env = merge.combine_stacks([(API, stack_env(**{"R3": {"status": "bogus", "note": ""}})), (WEB, stack_env())])
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertIn("api: unknown status `bogus`", env["checks"]["R3"]["note"])
        self.assertTrue(env["summary"].startswith(f"fail {HEAD} "), env["summary"])

    def test_the_drift_results_ci_entry_is_kept(self):
        ci = {"id": "CI-12345678", "check": "CI", "class": "env", "severity": "fail", "file": "", "line": 0,
              "problem": "the stack plan does not read", "hint": "", "forbidden": ""}
        drift = envelope(BASE, HEAD, [ci], dict({c: {"status": "skipped", "note": ""} for c in CHECKS},
                                                D={"status": "fail", "note": "bad plan"}))
        env = merge.combine_stacks([(API, stack_env()), (WEB, stack_env())], drift=drift)
        self.assertIn("CI-12345678", [e["id"] for e in env["entries"]])

    def test_no_drift_result_with_several_stacks_fails_d_with_a_ci_entry(self):
        env = merge.combine_stacks([(API, stack_env()), (WEB, stack_env())], drift_reason="result is for an older head")
        self.assertEqual(env["checks"]["D"], {"status": "fail", "note": "no result from drift job: result is for an older head"})
        [ci] = env["entries"]
        self.assertEqual((ci["check"], ci["problem"]), ("CI", "drift job produced no result: result is for an older head"))
        self.assertTrue(env["summary"].startswith(f"fail {HEAD} "), env["summary"])


if __name__ == "__main__":
    unittest.main()
