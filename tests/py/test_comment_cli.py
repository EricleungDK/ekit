"""mech-comment.py end to end against a local stand-in for the GitHub API: waivers and the read-only-token fallback."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import _kit
from mech_review import comment
from mech_review.report import summarize

SHA = "a" * 40
POSTER = os.path.join(_kit.SCRIPTS, "mech-comment.py")


def envelope(entries):
    checks = {c: {"status": "skipped", "note": "not run"} for c in ("R1", "R3", "R4")}
    checks["R2"] = {"status": "fail" if entries else "pass", "note": ""}
    return {"ekit": "0", "base": "b" * 40, "head": SHA, "checks": checks, "entries": entries,
            "summary": summarize(SHA, checks, entries)}


FAIL = {"id": "R2-deadbeef", "check": "R2", "class": "agent-fixable", "severity": "fail", "file": "tests/a.rs", "line": 7,
        "problem": "removed test fn b", "hint": "restore it", "forbidden": "deleting tests"}


class Api:
    """One fake API per test: `comments` are served, writes are logged or refused with `write_status`."""

    def __init__(self, comments=(), write_status=None):
        api = self
        self.comments, self.write_status, self.writes = list(comments), write_status, []

        class H(BaseHTTPRequestHandler):
            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if "/pulls/" in self.path:
                    return self._send(200, {"head": {"sha": SHA}})
                self._send(200, api.comments if "page=1" in self.path else [])

            def _write(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if api.write_status:
                    return self._send(api.write_status, {"message": "Resource not accessible by integration"})
                api.writes.append(body["body"])
                self._send(201, {"id": 1})

            do_POST = do_PATCH = _write

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def person(body, assoc="OWNER", kind="User"):
    return {"id": 5, "user": {"login": "eric", "type": kind}, "author_association": assoc, "body": body, "html_url": "u"}


class TestPoster(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.summary = os.path.join(self.tmp.name, "summary.md")

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, entries, api):
        path = os.path.join(self.tmp.name, "env.json")
        with open(path, "w") as f:
            json.dump(envelope(entries), f)
        env = {"PATH": os.environ["PATH"], "GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r", "GITHUB_API_URL": api.url,
               "GITHUB_STEP_SUMMARY": self.summary}
        try:
            return subprocess.run([sys.executable, "-I", POSTER, "--pr", "5", "--envelope", path], env=env,
                                  capture_output=True, text=True)
        finally:
            api.close()

    def test_an_owner_waiver_turns_the_check_green_and_shows_in_the_comment(self):
        api = Api([person("/mech-waive R2-deadbeef: moved to the e2e suite")])
        p = self.post([FAIL], api)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(api.writes), 1)
        self.assertIn("Waived: R2-deadbeef by `eric`: moved to the e2e suite", api.writes[0])
        self.assertIn("(0 fail, 0 confirm, 1 waived; ran: R2; skipped: R1 R3 R4)", api.writes[0])

    def test_a_waiver_from_an_outsider_or_a_bot_changes_nothing(self):
        for who in (person("/mech-waive R2-deadbeef: trust me", assoc="CONTRIBUTOR"),
                    person("/mech-waive R2-deadbeef: trust me", kind="Bot")):
            api = Api([who])
            p = self.post([FAIL], api)
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertNotIn("Waived:", api.writes[0])

    def test_the_bots_own_comment_cannot_waive(self):
        api = Api([{"id": 9, "user": {"login": comment.DEFAULT_AUTHOR, "type": "Bot"}, "author_association": "NONE",
                    "body": comment.MARKER + "\n/mech-waive R2-deadbeef: quoted from the PR"}])
        self.assertEqual(self.post([FAIL], api).returncode, 1)

    def test_a_read_only_token_keeps_the_result_and_writes_the_summary(self):
        p = self.post([FAIL], Api(write_status=403))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("::warning::mech-review: this token cannot comment on the PR", p.stdout)
        with open(self.summary) as f:
            self.assertIn("R2-deadbeef", f.read())

    def test_a_read_only_token_on_a_passing_result_exits_0(self):
        p = self.post([], Api(write_status=403))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("::warning::", p.stdout)

    def test_any_other_api_error_is_still_exit_3(self):
        p = self.post([FAIL], Api(write_status=500))
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertNotIn("::warning::", p.stdout)


if __name__ == "__main__":
    unittest.main()
