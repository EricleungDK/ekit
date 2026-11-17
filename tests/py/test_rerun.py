"""mech-rerun.py as a subprocess against a local stand-in for the GitHub API: which report job a /mech-waive comment re-runs."""
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import _kit

SHA = "a" * 40
SCRIPT = os.path.join(_kit.SCRIPTS, "mech-rerun.py")


def run(id, status="completed", created="2026-11-17T10:00:00Z"):
    return {"id": id, "status": status, "created_at": created}


def job(id, name="mech-review / mech-review report"):
    return {"id": id, "name": name}


class Api:
    """One fake API per test. `runs` are the pull_request runs of head SHA, `jobs` maps a run id to its latest jobs.
    Every call is logged as (method, path, query); `fail` maps a path to an error status."""

    def __init__(self, runs=(), jobs=None, fail=None):
        api = self
        self.runs, self.jobs, self.fail, self.calls = list(runs), dict(jobs or {}), dict(fail or {}), []

        class H(BaseHTTPRequestHandler):
            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _route(self):
                url = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                api.calls.append((self.command, url.path, q))
                if self.headers.get("Authorization") != "Bearer t":
                    return self._send(401, {"message": "Bad credentials"})
                if url.path in api.fail:
                    return self._send(api.fail[url.path], {"message": "boom"})
                parts = url.path.split("/")
                if self.command == "GET" and url.path == "/repos/o/r/pulls/5":
                    return self._send(200, {"head": {"sha": SHA}})
                if self.command == "GET" and url.path == "/repos/o/r/actions/runs":
                    mine = q.get("head_sha") == SHA and q.get("event") == "pull_request"
                    found = api.runs if mine else []
                    return self._send(200, {"total_count": len(found), "workflow_runs": found})
                if self.command == "GET" and parts[:5] == ["", "repos", "o", "r", "actions"] and parts[5:6] == ["runs"] \
                        and parts[7:] == ["jobs"] and q.get("filter") == "latest":
                    found = api.jobs.get(int(parts[6]), [])
                    return self._send(200, {"total_count": len(found), "jobs": found})
                if self.command == "POST" and parts[5:6] == ["jobs"] and parts[7:] == ["rerun"]:
                    return self._send(201, {})
                self._send(404, {"message": "Not Found"})

            do_GET = do_POST = _route

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        # a short poll: shutdown() waits up to one poll interval, at every test's end
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def reruns(self):
        return [path for method, path, _ in self.calls if method == "POST"]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def rerun(api, argv=("--pr", "5"), **env):
    """mech-rerun.py as the workflow runs it (python3 -I), against the fake API."""
    base = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    base.update({"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r", "GITHUB_API_URL": api.url})
    base.update(env)
    try:
        return subprocess.run([sys.executable, "-I", SCRIPT, *argv], env={k: v for k, v in base.items() if v is not None},
                              capture_output=True, text=True, timeout=30)
    finally:
        api.close()


class TestRerun(unittest.TestCase):
    def test_a_finished_run_has_its_report_job_re_run(self):
        api = Api([run(11)], {11: [job(101, "mech-review / guard"), job(102)]})
        p = rerun(api)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(api.reruns(), ["/repos/o/r/actions/jobs/102/rerun"])
        self.assertIn("mech-rerun: re-ran job 102", p.stderr)

    def test_a_run_still_going_is_left_to_read_the_comment_itself(self):
        api = Api([run(11, status="in_progress")], {11: [job(102)]})
        p = rerun(api)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(api.reruns(), [])
        self.assertIn("mech-rerun: run 11 is in_progress; its report job will read the comment", p.stderr)

    def test_the_newest_run_for_the_head_decides(self):
        api = Api([run(11, created="2026-11-17T09:00:00Z"), run(13, created="2026-11-17T11:00:00Z"),
                   run(12, created="2026-11-17T10:00:00Z")],
                  {11: [job(111)], 12: [job(121)], 13: [job(131)]})
        p = rerun(api)
        self.assertEqual(api.reruns(), ["/repos/o/r/actions/jobs/131/rerun"], p.stderr)

    def test_runs_created_in_the_same_second_go_by_the_higher_id(self):
        api = Api([run(21), run(23), run(22)], {21: [job(211)], 22: [job(221)], 23: [job(231)]})
        p = rerun(api)
        self.assertEqual(api.reruns(), ["/repos/o/r/actions/jobs/231/rerun"], p.stderr)

    def test_no_run_for_the_head_says_mech_review_has_not_run_and_re_runs_nothing(self):
        api = Api()
        p = rerun(api)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(api.reruns(), [])
        self.assertIn(f"mech-rerun: mech-review has not run for head {SHA}; nothing to re-run", p.stderr)

    def test_a_newer_run_of_another_workflow_is_passed_over(self):
        api = Api([run(31, created="2026-11-17T10:00:00Z"), run(32, created="2026-11-17T11:00:00Z")],
                  {31: [job(311)], 32: [job(321, "suite"), job(322, "hooks-macos")]})
        p = rerun(api)
        self.assertEqual(api.reruns(), ["/repos/o/r/actions/jobs/311/rerun"], p.stderr)

    def test_a_job_named_mech_review_report_without_a_caller_prefix_is_the_report(self):
        api = Api([run(41)], {41: [job(411, "mech-review report")]})
        p = rerun(api)
        self.assertEqual(api.reruns(), ["/repos/o/r/actions/jobs/411/rerun"], p.stderr)

    def test_jobs_whose_names_only_look_like_the_report_are_not_it(self):
        api = Api([run(51)], {51: [job(511, "mech-review reports"), job(512, "x/mech-review report"),
                                   job(513, "mech-review report / extra")]})
        p = rerun(api)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(api.reruns(), [])
        self.assertIn(f"mech-rerun: mech-review has not run for head {SHA}; nothing to re-run", p.stderr)

    def test_no_token_is_a_usage_error_that_calls_nothing(self):
        api = Api([run(11)], {11: [job(102)]})
        p = rerun(api, GITHUB_TOKEN=None)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stderr.splitlines(), ["mech-rerun: GITHUB_TOKEN not set"])
        self.assertEqual(api.calls, [])

    def test_no_repository_is_a_usage_error_that_calls_nothing(self):
        api = Api([run(11)], {11: [job(102)]})
        p = rerun(api, GITHUB_REPOSITORY=None)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stderr.splitlines(), ["mech-rerun: GITHUB_REPOSITORY not set"])
        self.assertEqual(api.calls, [])

    def test_a_pr_number_that_is_not_a_number_is_a_usage_error(self):
        api = Api()
        p = rerun(api, ("--pr", "5; rm -rf /"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("--pr: invalid int value", p.stderr)
        self.assertEqual(api.calls, [])

    def test_a_pr_number_below_1_is_a_usage_error(self):
        api = Api()
        p = rerun(api, ("--pr", "0"))
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stderr.splitlines(), ["mech-rerun: --pr must be a PR number (1 or more), not 0"])
        self.assertEqual(api.calls, [])

    def test_a_pr_the_api_cannot_find_is_an_api_error(self):
        api = Api(fail={"/repos/o/r/pulls/5": 404})
        p = rerun(api)
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stderr.splitlines(), ['mech-rerun: GitHub API 404: {"message": "boom"}'])

    def test_runs_that_cannot_be_listed_are_an_api_error(self):
        api = Api(fail={"/repos/o/r/actions/runs": 500})
        p = rerun(api)
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stderr.splitlines(), ['mech-rerun: GitHub API 500: {"message": "boom"}'])

    def test_a_refused_re_run_is_an_api_error(self):
        api = Api([run(11)], {11: [job(102)]}, fail={"/repos/o/r/actions/jobs/102/rerun": 403})
        p = rerun(api)
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stderr.splitlines(), ['mech-rerun: GitHub API 403: {"message": "boom"}'])


if __name__ == "__main__":
    unittest.main()
