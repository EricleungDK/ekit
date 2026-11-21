"""scripts/mech-summary.py (#38): a mech-review run's artifacts in a few lines, enough to classify a red report.

main(argv, run=...) in this process; the fake `run` stands for `gh` and copies fixture artifacts where `gh run download`
puts them. The envelopes have the engine's real shapes (the merge is the engine's own)."""
import json
import os
import shutil
import tempfile
import unittest

import _kit

ms = _kit.load("mech-summary")
BASE, HEAD = "b" * 40, "a" * 40
CHECKS = ("R1", "R2", "R3", "R4")


def env(owner, notes, entries=(), status=None, **r3):
    checks = {c: {"status": "skipped", "note": f"not run by {owner}"} for c in CHECKS}
    for c, (st, note) in notes.items():
        checks[c] = {"status": st, "note": note}
    checks["R3"].update(r3)
    fails = sum(e["severity"] == "fail" for e in entries)
    return {"ekit": "t", "base": BASE, "head": HEAD, "checks": checks, "entries": list(entries),
            "summary": f"{'fail' if fails else 'pass'} {HEAD} ({owner})"}


def ent(check, file, line, problem, sev="fail", id_=None):
    return {"id": id_ or f"{check}-{abs(hash((file, line, problem))) % 10**8:08d}", "check": check,
            "class": "agent-fixable", "severity": sev, "file": file, "line": line, "problem": problem,
            "hint": f"hint for {problem}", "forbidden": "f"}


R2_FAIL = ent("R2", "tests/test_a.py", 4, "assertions in test `t` dropped from 1 to 0", id_="R2-11111111")
R3_A = ent("R3", "src/a.py", 12, "missed: replace `<` with `<=`", id_="R3-22222222")
R3_A2 = ent("R3", "src/a.py", 3, "missed: replace return value with None", id_="R3-33333333")
R3_B = ent("R3", "src/b.py", 7, "missed: replace `+` with `-`", id_="R3-44444444")


def shard(k, note, entries=(), status="fail", tested=10, total=10, wall=50.0):
    e = env("mutants", {"R3": (status, note)}, entries, tested=tested, total=total, timing={"wall_s": wall})
    return e


def baseline(count, run=True, note=None):
    b = env("baseline", {"R3": ("skipped", note or f"3 changed production file(s) in {count} shard(s)")})
    b.update(run=run, count=count, mutants=None, timeout=None)
    return b


class Run(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = t.name
        self.art = os.path.join(self.tmp, "fixture")
        self.calls = []
        self.checks = [{"name": "mech-review / mech-review report", "state": "FAILURE",
                        "link": "https://github.com/o/r/actions/runs/555/job/9"},
                       {"name": "mech-review / mech-review guard (R2)", "state": "SUCCESS",
                        "link": "https://github.com/o/r/actions/runs/555/job/8"}]
        self.download_rc = 0

    def put(self, name, file, data):
        d = os.path.join(self.art, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, file), "w") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def red_run(self):
        """A red report: R2 fails, R3 fails in two shards, R1 and R4 pass."""
        self.put("mech-review-json", "mech-review.json",
                 env("r2", {"R2": ("fail", "1 fail, 0 confirm")}, [R2_FAIL]))
        self.put("mech-review-red-json", "mech-review-red.json",
                 env("red", {"R1": ("pass", "3 of 3 new test(s) fail on base"), "R4": ("pass", "3 test(s) run 5x")}))
        self.put("mech-review-baseline-json", "mech-review-baseline.json", baseline(2))
        self.put("mech-review-mutants-0", "mech-review-mutants.json",
                 shard(0, "10/10 tested: 2 missed in the diff", [R3_A, R3_A2], wall=61.5))
        self.put("mech-review-mutants-1", "mech-review-mutants.json",
                 shard(1, "10/10 tested: 1 missed in the diff", [R3_B], wall=48.25))

    def fake(self, argv, env=None, cwd=None):
        self.calls.append(list(argv))
        if argv[:3] == ["gh", "pr", "checks"]:
            return 0, json.dumps(self.checks), ""
        if argv[:3] == ["gh", "run", "download"]:
            if self.download_rc:
                return self.download_rc, "", "no artifacts found\n"
            dest = argv[argv.index("-D") + 1]
            shutil.copytree(self.art, dest, dirs_exist_ok=True)
            return 0, "", ""
        return 0, "", ""

    def main(self, *argv):
        return _kit.run_cli(list(argv), main=lambda a: ms.main(a, run=self.fake))


class Output(Run):
    def test_a_red_report_is_classified_from_the_output(self):
        self.red_run()
        r = self.main("555")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            f"run 555: fail {HEAD} (4 fail, 0 confirm; ran: R1 R2 R3 R4)",
            "R1 pass: 3 of 3 new test(s) fail on base",
            "R2 fail: 1 fail, 0 confirm",
            "R3 fail (20/20 tested)",
            "R4 pass: 3 test(s) run 5x",
            "shards:",
            "  shard 0/2: fail: 10/10 tested: 2 missed in the diff (wall 61.5 s)",
            "  shard 1/2: fail: 10/10 tested: 1 missed in the diff (wall 48.25 s)",
            "fail entries (4) by file:",
            "  src/a.py",
            "    R3-33333333 :3 missed: replace return value with None",
            "    R3-22222222 :12 missed: replace `<` with `<=`",
            "  src/b.py",
            "    R3-44444444 :7 missed: replace `+` with `-`",
            "  tests/test_a.py",
            "    R2-11111111 :4 assertions in test `t` dropped from 1 to 0",
            "waivers: not applied here (the sticky comment applies /mech-waive)",
        ])

    def test_the_download_is_the_runs_into_a_temp_dir(self):
        self.red_run()
        self.main("555", "--repo", "o/r")
        (dl,) = [c for c in self.calls if c[:3] == ["gh", "run", "download"]]
        self.assertEqual(dl[:4], ["gh", "run", "download", "555"])
        self.assertEqual(dl[dl.index("-R") + 1], "o/r")
        self.assertFalse(os.path.exists(dl[dl.index("-D") + 1]))

    def test_a_run_id_is_downloaded_with_no_pr_lookup(self):
        self.red_run()
        r = self.main("44583031414")
        self.assertEqual([c[:4] for c in self.calls], [["gh", "run", "download", "44583031414"]])
        self.assertTrue(r.stdout.startswith("run 44583031414: fail "), r.stdout)

    def test_targets_that_name_a_pr(self):
        self.assertEqual([ms._pr(t) for t in ("47", "#47", "https://github.com/o/r/pull/47", "http://h/x/pull/9/",
                                              "999999", "1000000", "44583031414", "pr47", "#")],
                         ["47", "47", "47", "9", "999999", None, None, None, None])

    def test_no_repo_flag_means_no_R(self):
        self.red_run()
        self.main("555")
        (dl,) = [c for c in self.calls if c[:3] == ["gh", "run", "download"]]
        self.assertNotIn("-R", dl)

    def test_a_pr_number_finds_the_report_checks_run(self):
        self.red_run()
        r = self.main("47", "--repo", "o/r")
        self.assertEqual(r.returncode, 1)
        self.assertIn(["gh", "pr", "checks", "47", "--json", "name,state,link", "-R", "o/r"], self.calls)
        self.assertTrue(r.stdout.startswith("run 555: "), r.stdout)

    def test_a_pr_url_and_a_hash_number_are_prs(self):
        self.red_run()
        for target in ("https://github.com/o/r/pull/47", "#47"):
            self.calls.clear()
            self.main(target)
            self.assertEqual(self.calls[0][:4], ["gh", "pr", "checks", "47"])

    def test_the_newest_report_run_wins(self):
        self.red_run()
        self.checks.append({"name": "mech-review / mech-review report", "state": "FAILURE",
                            "link": "https://github.com/o/r/actions/runs/1000/job/3"})
        r = self.main("47")
        self.assertTrue(r.stdout.startswith("run 1000: "), r.stdout)

    def test_a_pr_with_no_report_check_is_exit_2(self):
        self.checks = [self.checks[1]]
        r = self.main("47")
        self.assertEqual(r.returncode, 2)
        self.assertIn("mech-summary: PR 47 has no `mech-review report` check", r.stderr)

    def test_a_failed_checks_call_is_exit_2(self):
        def run(argv, env=None, cwd=None):
            return 1, "", "no pull requests found\n"

        r = _kit.run_cli(["47"], main=lambda a: ms.main(a, run=run))
        self.assertEqual(r.returncode, 2)
        self.assertIn("mech-summary: gh pr checks 47: no pull requests found", r.stderr)

    def test_pending_checks_still_answer(self):
        self.red_run()

        def run(argv, env=None, cwd=None):
            rc, out, err = self.fake(argv)
            return (8 if argv[:3] == ["gh", "pr", "checks"] else rc), out, err

        r = _kit.run_cli(["47"], main=lambda a: ms.main(a, run=run))
        self.assertEqual(r.returncode, 1, r.stderr)

    def test_a_failed_download_is_exit_2(self):
        self.download_rc = 1
        r = self.main("555")
        self.assertEqual(r.returncode, 2)
        self.assertIn("mech-summary: gh run download 555: no artifacts found", r.stderr)

    def test_a_dir_of_artifacts_needs_no_gh(self):
        self.red_run()
        r = self.main("--dir", self.art)
        self.assertEqual(self.calls, [])
        self.assertTrue(r.stdout.startswith(f"{self.art}: fail "), r.stdout)

    def test_neither_target_nor_dir_is_a_usage_error(self):
        self.assertEqual(self.main().returncode, 2)

    def test_no_artifact_at_all_is_exit_2(self):
        os.makedirs(self.art)
        r = self.main("--dir", self.art)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no mech-review artifact", r.stderr)


class Jobs(Run):
    def test_a_missing_shard_is_named_and_fails_r3(self):
        self.red_run()
        self.put("mech-review-mutants-0", "mech-review-mutants.json", shard(0, "4/4 caught", status="pass", tested=4, total=4))
        shutil.rmtree(os.path.join(self.art, "mech-review-mutants-1"))
        r = self.main("--dir", self.art)
        out = r.stdout.splitlines()
        self.assertIn("  shard 1/2: no result (no artifact mech-review-mutants-1)", out)
        self.assertIn("R3 fail (4/4 tested)", out)

    def test_a_job_with_no_result_is_a_ci_entry_with_no_file(self):
        self.red_run()
        shutil.rmtree(os.path.join(self.art, "mech-review-json"))
        out = self.main("--dir", self.art).stdout.splitlines()
        i = out.index("  (no file: CI)")
        self.assertEqual(out[i - 1], "    R3-44444444 :7 missed: replace `+` with `-`")
        self.assertTrue(out[i + 1].startswith("    CI-"), out[i + 1])
        self.assertTrue(out[i + 1].endswith(" :0 r2 job produced no result: no artifact mech-review-json"), out[i + 1])

    def test_a_shard_for_an_older_head_is_no_result(self):
        self.red_run()
        old = shard(1, "x")
        old["head"] = "c" * 40
        self.put("mech-review-mutants-1", "mech-review-mutants.json", old)
        r = self.main("--dir", self.art)
        self.assertIn(f"  shard 1/2: no result (result is for an older head, not {HEAD})", r.stdout.splitlines())

    def test_an_unreadable_shard_is_no_result(self):
        self.red_run()
        self.put("mech-review-mutants-1", "mech-review-mutants.json", "{not json")
        r = self.main("--dir", self.art)
        self.assertIn("  shard 1/2: no result (no usable result file)", r.stdout.splitlines())

    def test_a_missing_red_first_result_is_named(self):
        self.red_run()
        shutil.rmtree(os.path.join(self.art, "mech-review-red-json"))
        r = self.main("--dir", self.art)
        out = r.stdout.splitlines()
        self.assertIn("R1 fail: no result from red job: no artifact mech-review-red-json", out)
        self.assertTrue(any("red job produced no result: no artifact mech-review-red-json" in x for x in out), out)

    def test_no_baseline_artifact_is_named_as_not_run_or_crashed(self):
        self.red_run()
        for d in ("mech-review-baseline-json", "mech-review-mutants-0", "mech-review-mutants-1"):
            shutil.rmtree(os.path.join(self.art, d))
        r = self.main("--dir", self.art)
        out = r.stdout.splitlines()
        self.assertIn("R3 skipped: no baseline artifact: R3 not planned, or the baseline job crashed (see the run's jobs)",
                      out)
        self.assertNotIn("shards:", out)

    def test_a_baseline_that_runs_no_shard_is_the_r3_result(self):
        self.red_run()
        self.put("mech-review-baseline-json", "mech-review-baseline.json",
                 baseline(0, run=False, note="no changed production file under the project dir"))
        r = self.main("--dir", self.art)
        out = r.stdout.splitlines()
        self.assertIn("R3 skipped: no changed production file under the project dir", out)
        self.assertNotIn("shards:", out)

    def test_the_merged_artifact_is_used_when_present(self):
        self.red_run()
        merged = env("mutants", {"R3": ("pass", "from the merged artifact")}, tested=5, total=5)
        self.put("mech-review-mutants-merged-json", "mutants-merged.json", merged)
        r = self.main("--dir", self.art)
        out = r.stdout.splitlines()
        self.assertIn("R3 pass (5/5 tested)", out)
        self.assertFalse(any("R3-" in x for x in out), out)

    def test_a_green_run_lists_no_fails_and_no_waiver_line(self):
        self.put("mech-review-json", "mech-review.json", env("r2", {"R2": ("pass", "0 fail")}))
        self.put("mech-review-red-json", "mech-review-red.json",
                 env("red", {"R1": ("pass", "ok"), "R4": ("pass", "ok")}))
        self.put("mech-review-baseline-json", "mech-review-baseline.json", baseline(1))
        self.put("mech-review-mutants-0", "mech-review-mutants.json",
                 shard(0, "4/4 tested: 4 caught", status="pass", tested=4, total=4))
        r = self.main("--dir", self.art)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], f"{self.art}: all pass {HEAD}")
        self.assertFalse(any(x.startswith(("fail entries", "waivers")) for x in r.stdout.splitlines()))

    def test_confirm_entries_are_counted_not_listed(self):
        self.red_run()
        self.put("mech-review-json", "mech-review.json",
                 env("r2", {"R2": ("fail", "1 fail, 1 confirm")}, [R2_FAIL, ent("R2", "tests/t.py", 9, "x changed", "confirm")]))
        r = self.main("--dir", self.art)
        self.assertIn("confirm entries: 1 (see the PR comment)", r.stdout.splitlines())

    def test_a_shard_with_no_wall_time_has_no_wall_note(self):
        self.red_run()
        s = shard(1, "bare")
        del s["checks"]["R3"]["timing"]
        self.put("mech-review-mutants-1", "mech-review-mutants.json", s)
        r = self.main("--dir", self.art)
        self.assertIn("  shard 1/2: fail: bare", r.stdout.splitlines())

    def test_unknown_total_is_a_question_mark(self):
        self.red_run()
        self.put("mech-review-mutants-1", "mech-review-mutants.json", shard(1, "budget hit", status="partial", total=None))
        r = self.main("--dir", self.art)
        self.assertIn("R3 fail (20/? tested)", r.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
