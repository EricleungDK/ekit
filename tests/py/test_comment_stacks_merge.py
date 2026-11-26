"""mech-comment.py --stacks with each stack's mutants merged on its own (#62): `merge --stack S --project-dir D` per
leg, then one comment. Two stacks with their own shards give one summary with each stack's R3 kept apart; a stack
given twice in the --stacks file is one CI `fail` entry naming it, in the sticky comment and failing the check, not a
crash, and the other stacks still report. In this process: cli.main for mutants and merge, mech-comment's main."""
import json
import os
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
import test_comment_cli as tc
import test_comment_stacks_cli as tsc
from test_merge_shards import NO_TOOL, call
from test_adapter_cli import Repo

SHA = tc.SHA
PY = {"pyproject.toml": "[project]\nname = 'x'\n", "calc.py": "def add(a, b):\n    return a + b\n",
      "tests/test_calc.py": "import calc\n\n\ndef test_add():\n    assert calc.add(1, 2) == 3\n"}
API, PROTECTED, WEB = tsc.API, tsc.PROTECTED, tsc.WEB
WEB_PY = dict(WEB, stack="python")


class DuplicatedStack(unittest.TestCase):
    setUp = tc.TestPoster.setUp
    tearDown = tc.TestPoster.tearDown
    save = tc.TestPoster.save
    call = tc.TestPoster.call
    manifest = tsc.TestStacksPoster.manifest
    clean_drift = tsc.TestStacksPoster.clean_drift

    def test_a_stack_given_twice_is_one_ci_fail_entry_in_the_comment_and_the_others_still_report(self):
        api = tc.Api()
        p = self.call(["--stacks", self.manifest((API, {"r2": self.save("api-r2.json", [])}),
                                                 (WEB, {"r2": self.save("web-r2.json", [])}),
                                                 (API, {"r2": self.save("api-again.json", [PROTECTED])})),
                       "--envelope", "drift=" + self.clean_drift(), "--head", SHA], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        [body] = api.writes
        self.assertIn("| api | fail | :0 | stack api (python in api) given twice; the second is not counted |", body)
        self.assertEqual(body.count("| fail | :0 |"), 1)  # that one CI entry, and no other
        self.assertNotIn("protected path changed", body)  # the second api row is not counted
        self.assertEqual(body.count("| api | python | api | pass "), 1)
        self.assertIn("| web | ts | web | pass ", body)
        self.assertIn(f"**fail {SHA} (1 fail, 0 confirm;", body)

    def test_a_stack_name_or_a_stack_and_folder_given_twice_is_named_with_both_rows(self):
        for dup, problem in (
                (dict(WEB, name="api"), "stack api (python in api) given twice: again as stack api (ts in web); "
                                        "the second is not counted"),
                (dict(API, name="api2"), "stack api (python in api) given twice: again as stack api2 (python in api); "
                                         "the second is not counted")):
            api = tc.Api()
            p = self.call(["--stacks", self.manifest((API, {"r2": self.save("api-r2.json", [])}),
                                                     (dup, {"r2": self.save("dup-r2.json", [PROTECTED])})),
                           "--envelope", "drift=" + self.clean_drift(), "--head", SHA], api)
            self.assertEqual(p.returncode, 1, p.stderr)
            [body] = api.writes
            self.assertIn(f"| fail | :0 | {problem} |", body)
            self.assertEqual(body.count("| fail | :0 |"), 1, dup)
            self.assertNotIn("protected path changed", body, dup)

    def test_a_stack_given_three_times_is_one_ci_fail_entry(self):
        api = tc.Api()
        p = self.call(["--stacks", self.manifest((API, {"r2": self.save("api-r2.json", [])}),
                                                 (API, {"r2": self.save("api-2.json", [PROTECTED])}),
                                                 (dict(API, name="api3"), {"r2": self.save("api-3.json", [PROTECTED])})),
                       "--envelope", "drift=" + self.clean_drift(), "--head", SHA], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        [body] = api.writes
        self.assertIn("| api | fail | :0 | stack api (python in api) given 3 times: again as stack api3 (python in api); "
                      "only the first is counted |", body)
        self.assertEqual(body.count("| fail | :0 |"), 1)
        self.assertNotIn("protected path changed", body)

    def test_a_duplicate_whose_first_row_has_no_result_still_posts_the_comment_with_its_entry(self):
        api = tc.Api()
        p = self.call(["--stacks", self.manifest((API, {"r2": os.path.join(self.tmp.name, "gone.json")}),
                                                 (API, {"r2": self.save("api-r2.json", [])})),
                       "--head", SHA, "--reason", "no JSON"], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        [body] = api.writes
        self.assertIn("| api | fail | :0 | stack api (python in api) given twice; the second is not counted |", body)
        self.assertIn("| api | fail | :0 | stack api (python in api) produced no result |", body)


class StacksWithTheirOwnShards(unittest.TestCase):
    setUp = tc.TestPoster.setUp
    tearDown = tc.TestPoster.tearDown
    call = tc.TestPoster.call
    manifest = tsc.TestStacksPoster.manifest

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_two_stacks_merged_per_leg_give_one_summary_with_each_stacks_r3_apart(self):
        repo = Repo(os.path.join(self.tmp.name, "r"))
        base = repo.commit(dict(**{f"api/{k}": v for k, v in PY.items()}, **{f"web/{k}": v for k, v in PY.items()}), "b")
        head = repo.commit({"api/calc.py": "def add(a, b):\n    return b + a\n",
                            "web/calc.py": "def add(a, b):\n    return b + a\n"}, "h")
        common = ["--repo", repo.path, "--base", base, "--head", head, "--stack", "python"]

        def mutants(leg, shard):
            rc, out, err = call(["mutants", *common, "--project-dir", leg["project_dir"], "--test-paths", "*/tests/**",
                                 "--mutants-cmd", NO_TOOL, "--shard", shard])
            self.assertEqual(rc, 0, err)
            return self.write(f"{leg['name']}-{shard.replace('/', '-')}.json", out)

        def merged(leg, n, *paths):
            argv = ["merge", *common, "--project-dir", leg["project_dir"], "--shards", str(n)]
            for k, path in enumerate(paths):
                argv += ["--envelope", f"{k}={path}"]
            rc, out, err = call(argv)
            return self.write(f"{leg['name']}-mutants.json", out)

        # api: its two shards; web: its one shard, and a result of api's given as its second
        api_m = merged(API, 2, mutants(API, "0/2"), mutants(API, "1/2"))
        web_m = merged(WEB_PY, 2, mutants(WEB_PY, "0/2"), mutants(API, "1/2"))
        checks = {c: {"status": "skipped", "note": "not run by drift"} for c in ("R1", "R2", "R3", "R4")}
        checks["D"] = {"status": "pass", "note": "clean", "messages": []}
        drift = self.write("drift.json", json.dumps(tsc.envelope(head, checks)))
        p = self.call(["--stacks", self.manifest((API, {"mutants": api_m}), (WEB_PY, {"mutants": web_m})),
                       "--envelope", f"drift={drift}", "--head", head], tc.Api())
        self.assertEqual(p.returncode, 1, p.stderr)
        with open(self.summary) as f:
            body = f.read()
        self.assertIn(f"| api | python | api | pass {head} (0 fail, 0 confirm; ran: none; skipped: R1 R2 R4; n/a: R3) |",
                      body)
        self.assertIn(f"| web | python | web | fail {head} (1 fail, 0 confirm; ran: R3; skipped: R1 R2 R4) |", body)
        self.assertIn("| web | fail | :0 | mutants shard 1/2 produced no result: result is for stack python in api, "
                      "not python in web |", body)
        self.assertEqual(body.count("| fail | :0 |"), 1)  # that one CI entry, and no other
        self.assertIn(f"**fail {head} (1 fail, 0 confirm;", body)


if __name__ == "__main__":
    unittest.main()
