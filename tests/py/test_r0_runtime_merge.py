"""R0 runtime half (#21) in the merged result: the red-first job's R0 part (run) and the mutants job's (r3, shard 0)
are combined with the guard's static half into one R0 check; their entries are kept, and a failed part blocks the checks
it proves in every job's result. Through mech-comment.py's and `merge`'s own entry points, in this process."""
import json
import os
import tempfile
import unittest

import _kit
from scripts.mech_review import merge, report

B, H = "b" * 40, "a" * 40


def env(checks, entries=()):
    full = {c: {"status": "skipped", "note": "x"} for c in report.CHECKS}
    full.update(checks)
    return report.envelope(B, H, list(entries), full)


def r0_entry(key="runtime:run:control-pass"):
    return report.finalize([report.entry("R0", "ekit:scripts/mech_review/r0_fixtures/python", 0, key, "adapter-fix",
                                         "fail", "R0 runtime half (run) failed", "h", "f")])[0]


STATIC = {"status": "pass", "note": "static half: 15 of 15 cases proved", "half": "static"}
RUN_FAIL = {"status": "fail", "note": "runtime half (run): failed: control-pass", "half": "runtime", "part": "run",
            "blocks": ["R1", "R2", "R4"], "cause": "R0 runtime half (run) failed"}
RUN_PASS = {"status": "pass", "note": "runtime half (run): fingerprint 0123 (ran)", "half": "runtime", "part": "run"}


class Merged(unittest.TestCase):
    def test_a_failed_run_part_from_red_fails_r0_and_blocks_r2_from_the_guard(self):
        parts = {"r2": env({"R2": {"status": "pass", "note": "0 fail"}}),
                 "r0": env({"R0": STATIC}),
                 "red": env({"R1": {"status": "pass", "note": "1 red"}, "R4": {"status": "pass", "note": "ok"},
                             "R0": RUN_FAIL}, [r0_entry()])}
        got = merge.merge(parts, {})
        r0 = got["checks"]["R0"]
        self.assertEqual(r0["status"], "fail")
        self.assertEqual(r0["note"], "static half: 15 of 15 cases proved; runtime half (run): failed: control-pass")
        self.assertEqual([p["half"] for p in r0["parts"]], ["static", "runtime"])
        self.assertEqual({c: got["checks"][c]["status"] for c in ("R1", "R2", "R4")}, dict.fromkeys(("R1", "R2", "R4"), "n/a"))
        self.assertEqual([e["check"] for e in got["entries"]], ["R0"])
        self.assertTrue(got["summary"].startswith(f"fail {H} (1 fail, 0 confirm"), got["summary"])

    def test_a_passed_run_part_keeps_r0_pass(self):
        parts = {"r0": env({"R0": STATIC}), "red": env({"R0": RUN_PASS})}
        got = merge.merge(parts, {})
        self.assertEqual(got["checks"]["R0"]["status"], "pass")

    def test_red_without_r0_leaves_the_static_half_as_it_is(self):
        parts = {"r0": env({"R0": STATIC}), "red": env({"R1": {"status": "pass", "note": "x"}})}
        self.assertEqual(merge.merge(parts, {})["checks"]["R0"], STATIC)

    def test_the_mutants_merge_carries_shard_0s_r3_control(self):
        r3 = {"status": "fail", "note": "runtime half (r3): failed: r3-weak", "half": "runtime", "part": "r3",
              "blocks": ["R3"], "cause": "R0 runtime half (r3) failed"}
        shard0 = env({"R3": {"status": "pass", "note": "0 missed"}, "R0": r3}, [r0_entry("runtime:r3:r3-weak")])
        shard0["shard"] = {"k": 0, "n": 2, "max_mutants": 40}
        shard0["stack"] = {"stack": "python", "project_dir": "."}  # merge counts only its stack's results (#62)
        shard1 = env({"R3": {"status": "pass", "note": "0 missed"}})
        shard1["shard"] = {"k": 1, "n": 2, "max_mutants": 40}
        shard1["stack"] = {"stack": "python", "project_dir": "."}
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for k, e in enumerate((shard0, shard1)):
                paths.append(os.path.join(tmp, f"s{k}.json"))
                with open(paths[-1], "w") as f:
                    json.dump(e, f)
            r = _kit.run_cli(["merge", "--repo", tmp, "--base", B, "--head", H, "--stack", "python", "--shards", "2",
                              "--envelope", f"0={paths[0]}", "--envelope", f"1={paths[1]}"])
        got = json.loads(r.stdout)
        self.assertEqual(got["checks"]["R0"], r3)
        self.assertEqual([e["check"] for e in got["entries"]], ["R0"])
        whole = merge.merge({"r0": env({"R0": STATIC}), "mutants": got}, {})
        self.assertEqual((whole["checks"]["R0"]["status"], whole["checks"]["R3"]["status"]), ("fail", "n/a"))


    def test_several_stacks_a_failed_run_part_in_one_stacks_red_fails_r0_for_the_whole(self):
        """#74 (several stacks, #17): each stack's jobs merge apart, then combine_stacks takes the worst per check."""
        good = merge.merge({"r0": env({"R0": STATIC}), "red": env({"R0": RUN_PASS})}, {})
        bad = merge.merge({"r0": env({"R0": STATIC}), "red": env({"R0": RUN_FAIL}, [r0_entry()])}, {})
        legs = [({"name": "py", "stack": "python", "project_dir": "py"}, good),
                ({"name": "web", "stack": "ts", "project_dir": "web"}, bad)]
        got = merge.combine_stacks(legs)
        self.assertEqual(got["checks"]["R0"]["status"], "fail")
        self.assertEqual([s["checks"]["R0"]["status"] for s in got["stacks"]], ["pass", "fail"])
        self.assertEqual([e["check"] for e in got["entries"]], ["R0"])


    def test_only_r0_entries_ride_in_with_a_runtime_part_and_only_with_one(self):
        stray = report.finalize([report.entry("R2", "a.py", 1, "stray", "agent-fixable", "fail", "R2 in red", "h", "f")])
        with_part = env({"R0": RUN_FAIL}, [r0_entry()] + stray)
        without = env({"R1": {"status": "pass", "note": "x"}}, [r0_entry("runtime:run:other")])
        got = merge.merge({"r0": env({"R0": STATIC}), "red": with_part}, {})
        self.assertEqual([e["check"] for e in got["entries"]], ["R0"])  # the stray R2 entry stays out
        got = merge.merge({"r0": env({"R0": STATIC}), "red": without}, {})
        self.assertEqual(got["entries"], [])  # no runtime part: its R0 entry stays out

    def test_a_shard_keeps_its_r3_entries_and_r0_only_with_its_r0_part(self):
        stray = report.finalize([report.entry("R2", "a.py", 1, "stray", "agent-fixable", "fail", "R2 in a shard", "h", "f")])
        r3 = report.finalize([report.entry("R3", "a.py", 2, "missed:a", "agent-fixable", "fail", "MISSED", "h", "f")])
        part = {"status": "pass", "note": "runtime half (r3)", "half": "runtime", "part": "r3"}
        s0 = env({"R3": {"status": "fail", "note": "1 missed"}, "R0": part}, r3 + stray)
        s1 = env({"R3": {"status": "pass", "note": "0 missed"}}, [r0_entry("runtime:r3:x")])
        got = merge.combine_shards(B, H, 2, {0: s0, 1: s1}, {})
        self.assertEqual(sorted(e["check"] for e in got["entries"]), ["R3"])


if __name__ == "__main__":
    unittest.main()
