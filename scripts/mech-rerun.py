#!/usr/bin/env python3
"""mech-waive step: re-run the PR head's `mech-review report` job, so a new `/mech-waive` comment is read.

usage: python3 -I scripts/mech-rerun.py --pr N
env: GITHUB_TOKEN (needs `actions: write`), GITHUB_REPOSITORY (owner/repo), GITHUB_API_URL (default https://api.github.com).
which job: the pull_request runs of the PR's head sha, newest first; the first one with a job named `mech-review report`
     (or `<caller job> / mech-review report`, a reusable workflow's job) decides. Still running: nothing is re-run, that
     run's report reads the comment when it gets there. Completed: that job is re-run (POST .../jobs/{id}/rerun).
     No such run or job for the head: a notice, nothing to re-run (the next push runs mech-review, which reads it).
exit: 0 re-run, still running, or nothing to re-run; 2 usage; 3 GitHub API error.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mech_review import comment as C  # noqa: E402 - sys.path is set just above

JOB = "mech-review report"


def rerun(call, api, repo, pr):
    """Re-run the report job of the newest mech-review run on the PR's head, if it has finished. Returns what was done."""
    sha = call("GET", f"{api}/repos/{repo}/pulls/{pr}", None)["head"]["sha"]
    runs = call("GET", f"{api}/repos/{repo}/actions/runs?head_sha={sha}&event=pull_request&per_page=100", None)["workflow_runs"]
    for run in sorted(runs, key=lambda r: (r["created_at"], r["id"]), reverse=True):
        jobs = call("GET", f"{api}/repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100", None)["jobs"]
        for job in jobs:
            if job["name"] == JOB or job["name"].endswith(" / " + JOB):
                if run["status"] != "completed":
                    return f"run {run['id']} is {run['status']}; its report job will read the comment, nothing re-run"
                call("POST", f"{api}/repos/{repo}/actions/jobs/{job['id']}/rerun", None)
                return f"re-ran job {job['id']} ({job['name']}, run {run['id']})"
    return f"mech-review has not run for head {sha}; nothing to re-run (its first run reads the comment)"


def main(argv):
    ap = argparse.ArgumentParser(prog="mech-rerun.py")
    ap.add_argument("--pr", type=int, required=True, help="pull request number")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if args.pr < 1:
        print(f"mech-rerun: --pr must be a PR number (1 or more), not {args.pr}", file=sys.stderr)
        return 2
    if not token:
        print("mech-rerun: GITHUB_TOKEN not set", file=sys.stderr)
        return 2
    if not repo:
        print("mech-rerun: GITHUB_REPOSITORY not set", file=sys.stderr)
        return 2
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    try:
        done = rerun(C.http_call(token), api, repo, args.pr)
    except C.ApiError as e:
        print(f"mech-rerun: {e}", file=sys.stderr)
        return 3
    print(f"mech-rerun: {done}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
