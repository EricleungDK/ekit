"""A stand-in for the GitHub REST API, for the mech-waive scenario. Stdlib only.

usage: python3 fake_github.py STATE_JSON LOG_FILE PORT_FILE
STATE_JSON is re-read on every request, so the scenario edits it between steps:
  {"head": sha, "comments": [issue comment objects], "runs": [workflow run objects], "jobs": {run id: [job objects]}}
Every write is appended to LOG_FILE as one JSON line {method, path, body}. A posted comment is added to the state as
the bot's (github-actions[bot]), and a PATCH edits it, as GitHub would. The port it listens on goes to PORT_FILE.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

STATE, LOG, PORT_FILE = sys.argv[1:4]
BOT = {"login": "github-actions[bot]", "type": "Bot"}


def load():
    with open(STATE) as fh:
        return json.load(fh)


def save(state):
    with open(STATE, "w") as fh:
        json.dump(state, fh)


class H(BaseHTTPRequestHandler):
    def send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        parts = u.path.strip("/").split("/")  # repos/o/r/...
        s = load()
        rest = parts[3:]
        if rest[:1] == ["pulls"]:
            return self.send(200, {"number": int(rest[1]), "head": {"sha": s["head"]}})
        if rest[:1] == ["issues"] and rest[2:] == ["comments"]:
            page = int(q.get("page", ["1"])[0])
            per = int(q.get("per_page", ["30"])[0])
            return self.send(200, s["comments"][(page - 1) * per:page * per])
        if rest == ["actions", "runs"]:
            runs = [r for r in s.get("runs", []) if r["head_sha"] == q.get("head_sha", [""])[0]
                    and r["event"] == q.get("event", [""])[0]]
            return self.send(200, {"total_count": len(runs), "workflow_runs": runs})
        if rest[:2] == ["actions", "runs"] and rest[3:] == ["jobs"]:
            jobs = s.get("jobs", {}).get(rest[2], [])
            return self.send(200, {"total_count": len(jobs), "jobs": jobs})
        self.send(404, {"message": "Not Found"})

    def write(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"null")
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"method": method, "path": urlparse(self.path).path, "body": body}) + "\n")
        parts = urlparse(self.path).path.strip("/").split("/")
        rest = parts[3:]
        s = load()
        if method == "POST" and rest[:1] == ["issues"] and rest[2:] == ["comments"]:
            cid = 9000 + len(s["comments"])
            s["comments"].append({"id": cid, "user": BOT, "author_association": "NONE", "body": body["body"],
                                  "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
                                  "html_url": f"https://github.test/c/{cid}"})
            save(s)
            return self.send(201, {"id": cid})
        if method == "PATCH" and rest[:2] == ["issues", "comments"]:
            for c in s["comments"]:
                if str(c["id"]) == rest[2]:
                    c["body"] = body["body"]
            save(s)
            return self.send(200, {"id": int(rest[2])})
        if method == "POST" and rest[:2] == ["actions", "jobs"] and rest[3:] == ["rerun"]:
            return self.send(201, {})
        self.send(404, {"message": "Not Found"})

    def do_POST(self):
        self.write("POST")

    def do_PATCH(self):
        self.write("PATCH")

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
with open(PORT_FILE, "w") as fh:
    fh.write(str(srv.server_address[1]))
srv.serve_forever()
