"""mech-comment.py --stacks (#17): the report of a repo with several stacks. Each stack's job results merge apart, and
ONE comment and ONE exit code come of them; a waiver names one stack's entry; a stack with nothing is a CI entry."""
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
import test_comment_cli as tc
from scripts.mech_review import merge
from scripts.mech_review.report import summarize

SHA = tc.SHA
API = {"name": "api", "stack": "python", "project_dir": "api"}
WEB = {"name": "web", "stack": "ts", "project_dir": "web"}
def envelope(head, checks):
    return {"ekit": "0", "base": "b" * 40, "head": head, "checks": checks, "entries": [],
            "summary": summarize(head, checks, [])}


PROTECTED = dict(tc.FAIL, id="R2-0badc0de", file=".github/ci.yml", line=0, problem="protected path changed",
                 **{"class": "needs-human"})


class TestStacksPoster(unittest.TestCase):
    setUp = tc.TestPoster.setUp
    tearDown = tc.TestPoster.tearDown
    save = tc.TestPoster.save
    call = tc.TestPoster.call

    def manifest(self, *legs):
        path = os.path.join(self.tmp.name, "stacks.json")
        with open(path, "w") as f:
            json.dump([dict(leg, envelopes=envs) for leg, envs in legs], f)
        return path

    def two_stacks(self, web_r2=None):
        return self.manifest((API, {"r2": self.save("api-r2.json", [PROTECTED])}),
                             (WEB, {"r2": web_r2 or self.save("web-r2.json", [PROTECTED])}))

    def clean_drift(self):
        """a drift result with D passing (a plan that matches the tree)"""
        checks = {c: {"status": "skipped", "note": "not run by drift"} for c in ("R1", "R2", "R3", "R4")}
        checks["D"] = {"status": "pass", "note": "clean", "messages": []}
        path = os.path.join(self.tmp.name, "drift-clean.json")
        with open(path, "w") as f:
            json.dump(envelope(SHA, checks), f)
        return path

    def labelled(self, leg):
        return merge.label_stack({"entries": [PROTECTED]}, leg)["entries"][0]["id"]

    def test_two_stacks_post_one_comment_with_a_row_each_and_fail_together(self):
        api = tc.Api()
        p = self.call(["--stacks", self.two_stacks(), "--head", SHA], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(len(api.writes), 1)
        body = api.writes[0]
        self.assertIn("| api | python | api | fail ", body)
        self.assertIn("| web | ts | web | fail ", body)
        for leg in (API, WEB):
            self.assertIn(f"| {self.labelled(leg)} | {leg['name']} | needs-human | .github/ci.yml:0 |", body)

    def test_a_waiver_on_one_stacks_entry_leaves_the_other_stacks_entry_failing(self):
        api = tc.Api([tc.person(f"/mech-waive {self.labelled(API)}: the owner edits the api workflow")])
        p = self.call(["--stacks", self.two_stacks(), "--head", SHA], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        body = api.writes[0]
        self.assertIn(f"Waived: {self.labelled(API)} by `eric`: the owner edits the api workflow", body)
        self.assertIn(f"| api | python | api | pass {SHA} (0 fail, 0 confirm, 1 waived;", body)
        self.assertIn(f"| {self.labelled(WEB)} | web | needs-human |", body)

    def test_waivers_on_every_stacks_entry_pass_the_check(self):
        api = tc.Api([tc.person(f"/mech-waive {self.labelled(API)}: ok"), tc.person(f"/mech-waive {self.labelled(WEB)}: ok")])
        p = self.call(["--stacks", self.two_stacks(), "--envelope", "drift=" + self.clean_drift(), "--head", SHA], api)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(f"**pass {SHA} (0 fail, 0 confirm, 2 waived;", api.writes[0])

    def test_a_stack_with_no_usable_result_is_a_ci_entry_and_the_check_fails(self):
        api = tc.Api()
        p = self.call(["--stacks", self.manifest((API, {"r2": self.save("api-r2.json", [])}),
                                                 (WEB, {"r2": os.path.join(self.tmp.name, "gone.json"),
                                                        "red": os.path.join(self.tmp.name, "gone.json")})),
                       "--head", SHA, "--reason", "no JSON from the job"], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        body = api.writes[0]
        self.assertIn("| web | fail | :0 | stack web (ts in web) produced no result |", body)
        self.assertIn(f"| api | python | api | pass {SHA}", body)

    def test_a_job_missing_in_one_stack_is_that_stacks_ci_entry(self):
        api = tc.Api()
        p = self.call(["--stacks", self.manifest((API, {"r2": self.save("api-r2.json", [])}),
                                                 (WEB, {"r2": self.save("web-r2.json", []),
                                                        "red": os.path.join(self.tmp.name, "gone.json")})),
                       "--head", SHA, "--reason", "no JSON from the job"], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("| web | fail | :0 | red job produced no result: no JSON from the job |", api.writes[0])

    def test_the_drift_result_is_the_repos_once(self):
        path, eid = tc.TestPoster.drift_result(self)
        api = tc.Api()
        p = self.call(["--stacks", self.manifest((API, {"r2": self.save("api-r2.json", [])}),
                                                 (WEB, {"r2": self.save("web-r2.json", [])})),
                       "--envelope", f"drift={path}", "--head", SHA], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn(f"| {eid} |  | fail | .ekit/stack-plan.toml:0 |", api.writes[0])
        self.assertEqual(api.writes[0].count(f"| {eid} |"), 1)

    def test_no_stack_with_any_result_is_the_crash_notice(self):
        gone = os.path.join(self.tmp.name, "gone.json")
        api = tc.Api()
        p = self.call(["--stacks", self.manifest((API, {"r2": gone}), (WEB, {"r2": gone})), "--head", SHA,
                       "--reason", "no JSON"], api)
        self.assertEqual(p.returncode, 4)
        self.assertIn("reason: api: r2 job: no JSON; web: r2 job: no JSON", api.writes[0])

    def test_stacks_take_no_job_envelope_but_drift(self):
        p = self.call(["--stacks", self.two_stacks(), "--envelope", "r2=" + self.save("r2.json", []), "--head", SHA],
                      tc.Api())
        self.assertEqual(p.returncode, 2)
        self.assertIn("mech-comment: with --stacks, --envelope takes drift=FILE only (the repo's)", p.stderr)

    def test_a_malformed_stacks_file_posts_the_crash_comment_naming_it(self):
        bad = os.path.join(self.tmp.name, "bad.json")
        leg = dict(API, envelopes={"r2": "x.json"})
        for text in ("[{}]", "[]", "{}", '"x"', json.dumps([dict(API, envelopes={})]), "not json",
                     json.dumps([leg, leg]), json.dumps([leg, dict(leg, name="api2")]),
                     json.dumps([leg, dict(leg, stack="ts", project_dir="web")])):
            with open(bad, "w") as f:
                f.write(text)
            api = tc.Api()
            p = self.call(["--stacks", bad, "--head", SHA], api)
            self.assertEqual(p.returncode, 4, text)
            self.assertIn(f"reason: --stacks {bad}: want a list of distinct {{name, stack, project_dir, envelopes}} "
                          "(one per stack: no name, and no stack and project dir, twice)", api.writes[0])

    def test_a_drift_result_for_another_head_is_a_ci_entry_as_for_one_stack(self):
        path, _ = tc.TestPoster.drift_result(self)
        with open(path) as f:
            env = json.load(f)
        with open(path, "w") as f:
            json.dump(dict(env, head="c" * 40), f)
        api = tc.Api()
        p = self.call(["--stacks", self.manifest((API, {"r2": self.save("api-r2.json", [])}),
                                                 (WEB, {"r2": self.save("web-r2.json", [])})),
                       "--envelope", f"drift={path}", "--head", SHA], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn(f"drift job produced no result: result is for an older head, not {SHA}", api.writes[0])
        self.assertIn(f"**fail {SHA} (1 fail, 0 confirm; ran: R2 D;", api.writes[0])

    def test_no_drift_result_with_several_stacks_is_a_ci_entry(self):
        api = tc.Api()
        p = self.call(["--stacks", self.manifest((API, {"r2": self.save("api-r2.json", [])}),
                                                 (WEB, {"r2": self.save("web-r2.json", [])})), "--head", SHA], api)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("drift job produced no result: no drift result given (a stack plan always has one)", api.writes[0])

if __name__ == "__main__":
    unittest.main()
