#!/usr/bin/env python3
"""mech-review report step: render the guard JSON, post or edit the sticky PR comment, set the exit code.

usage: python3 -I scripts/mech-comment.py --pr N [--envelope FILE | --envelope JOB=FILE ...] [--head SHA] [--reason TEXT]
       python3 -I scripts/mech-comment.py --pr N --stacks FILE [--envelope drift=FILE] [--head SHA] [--reason TEXT]
JOB is r2 (guard), r0, red (red-first), mutants (R3 shards merged) or drift (the stack plan's drift check, #56). Named envelopes are merged into one comment; a job with no usable result
fails its checks and adds a CI entry, the other job's entries stay.
several stacks (#17): --stacks FILE is a JSON list of {name, stack, project_dir, envelopes: {JOB: FILE}}, one per stack
     of the plan. Each stack's job results merge apart (as above); then one comment and one exit code come of them:
     a row per stack, entries labelled with their stack and ids made distinct by stack, each check the worst of the
     stacks'. A stack with no result at all fails, with a CI entry; a stack given twice counts once, with a CI
     entry naming it (#62). The drift result is the repo's: --envelope drift=FILE.
env: GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo), GITHUB_API_URL (default https://api.github.com),
     GITHUB_STEP_SUMMARY (optional: rendered comment is also appended there),
     MECH_COMMENT_AUTHOR (login whose marker comment is edited; default github-actions[bot]).
superseded: if the PR head is no longer this run's head, the comment is left alone (exit = own rc, 0 on crash).
waivers: a `/mech-waive <id> <reason>` comment on the PR from a person with write access (OWNER, MEMBER or
     COLLABORATOR, never a bot) turns that fail entry into `waived`; it no longer fails the check (mech_review/waiver.py).
     One from such a person that does not count (an edited comment, a placeholder reason) on an entry still failing
     is listed under `waivers_ignored` in the envelope, and the comment says why.
read-only token (a fork or Dependabot PR: GitHub answers 403 "Resource not accessible by integration"): the comment
     cannot be posted, so the result goes to the
     job summary and the log only, and the exit code is still the result's.
exit: 0 no fail entries; 1 any fail entry; 2 usage; 3 GitHub API error (other than that 403);
      4 no usable result (a crash comment is posted in place of the result).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mech_review import comment as C  # noqa: E402
from mech_review import merge, waiver  # noqa: E402 - sys.path is set just above


def load(path):
    """The envelope dict, or None if missing, unreadable or not an envelope."""
    if not path:
        return None
    try:
        with open(path) as fh:
            env = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(env, dict) or not all(k in env for k in ("head", "summary", "entries")):
        return None
    return env


def named(jobs, head, reason):
    """(merged envelope or None, crash reason) of named job results: a result for another head is not used."""
    parts, reasons = {}, {}
    for job, path in jobs:
        got = load(path)
        if got is not None and head and got["head"] != head:
            got, why = None, f"result is for an older head, not {head}"
        else:
            why = reason
        parts[job], reasons[job] = got, why
    crash = "; ".join(f"{j} job: {r}" for j, r in reasons.items())  # the reason, used when no job has a result
    return (merge.merge(parts, reasons) if any(e is not None for e in parts.values()) else None), crash


def read_stacks(path):
    """[{name, stack, project_dir, envelopes: {job: file}}] from the --stacks file, or None when it is not that. A stack
    in it twice (by name, or by stack and project dir) is read: combine_stacks counts it once and names it (#62)."""
    try:
        with open(path) as fh:
            legs = json.load(fh)
    except (OSError, ValueError):
        return None
    ok = isinstance(legs, list) and legs and all(
        isinstance(leg, dict) and all(isinstance(leg.get(k), str) for k in ("name", "stack", "project_dir"))
        and isinstance(leg.get("envelopes"), dict) and leg["envelopes"]
        and all(j in merge.OWNS and j != "drift" and isinstance(f, str) for j, f in leg["envelopes"].items())
        for leg in legs)
    return legs if ok else None


def main(argv):
    ap = argparse.ArgumentParser(prog="mech-comment.py")
    ap.add_argument("--pr", type=int, required=True, help="pull request number")
    ap.add_argument("--envelope", action="append", metavar="[JOB=]FILE",
                    help="result JSON (mech-review.py output); JOB=FILE with job r2, red, mutants or drift, repeatable, merged")
    ap.add_argument("--stacks", metavar="FILE",
                    help="several stacks: a JSON list of {name, stack, project_dir, envelopes: {JOB: FILE}}, merged apart, "
                         "reported as one; --envelope then takes drift=FILE only")
    ap.add_argument("--head", help="head sha, used for the crash comment")
    ap.add_argument("--reason", default="mech-review produced no JSON", help="crash reason")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token:
        print("mech-comment: GITHUB_TOKEN not set", file=sys.stderr)
        return 2
    if not repo:
        print("mech-comment: GITHUB_REPOSITORY not set", file=sys.stderr)
        return 2
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    author = os.environ.get("MECH_COMMENT_AUTHOR") or C.DEFAULT_AUTHOR

    files = args.envelope or []
    jobs = []
    for f in files:
        job, sep, path = f.partition("=")
        if not sep:
            jobs.append((None, f))
        elif job in merge.OWNS:
            jobs.append((job, path))
        else:
            print(f"mech-comment: unknown job '{job}' (r2, red, mutants or drift)", file=sys.stderr)
            return 2
    if jobs and any(j is None for j, _ in jobs) and any(j is not None for j, _ in jobs):
        print("mech-comment: name every --envelope (JOB=FILE) or none", file=sys.stderr)
        return 2
    if len(jobs) > 1 and jobs[0][0] is None:
        print("mech-comment: several --envelope need job names: r2=FILE red=FILE", file=sys.stderr)
        return 2

    stacks = drift = None
    if args.stacks is not None:
        if any(j != "drift" for j, _ in jobs):
            print("mech-comment: with --stacks, --envelope takes drift=FILE only (the repo's)", file=sys.stderr)
            return 2
        legs = read_stacks(args.stacks)
        stacks, crashes, env, drift_why = [], [], None, None
        if legs is None:  # no result to report: the crash comment names the file
            crashes = [f"--stacks {args.stacks}: want a non-empty list of {{name, stack, project_dir, envelopes: "
                       "{JOB: FILE}}, one per stack"]
            print(f"mech-comment: {crashes[0]}", file=sys.stderr)
        for leg in legs or []:
            got, why = named(list(leg["envelopes"].items()), args.head, args.reason)
            stacks.append(({k: leg[k] for k in ("name", "stack", "project_dir")}, got))
            crashes.append(f"{leg['name']}: {why}")
        # several stacks come from a plan, so a drift result is always due: none, or one for another head, fails D
        drift = load(jobs[0][1]) if jobs else None
        if not jobs:
            drift_why = "no drift result given (a stack plan always has one)"
        elif drift is None:
            drift_why = args.reason
        elif args.head and drift["head"] != args.head:
            drift, drift_why = None, f"result is for an older head, not {args.head}"
        crash = "; ".join(crashes)
        if stacks and (drift is not None or any(e is not None for _, e in stacks)):
            env = merge.combine_stacks(stacks, drift, drift_reason=drift_why)
    elif jobs and jobs[0][0] is not None:
        env, crash = named(jobs, args.head, args.reason)
    else:
        env = load(jobs[0][1] if jobs else None)
        if env is not None and args.head and env["head"] != args.head:
            print(f"mech-comment: envelope is for {env['head']}, not head {args.head}: stale", file=sys.stderr)
            env = None
            args.reason = f"guard result is for an older head, not {args.head}"
        crash = args.reason

    call = C.http_call(token)
    if env is None:
        if not args.head:
            print("mech-comment: no usable envelope and --head not given", file=sys.stderr)
            return 2
        body, rc = C.render_crash(args.head, crash), 4
        print(f"mech-comment: no usable result: {crash}", file=sys.stderr)
    else:
        try:
            notes = list(C.comments(call, api, repo, args.pr))
            waivers = waiver.collect(notes)
            if stacks is not None:  # each stack's own checks read its waivers too
                env = merge.combine_stacks(stacks, drift, waive=lambda e: waiver.apply(e, waivers), drift_reason=drift_why)
            else:
                env = waiver.apply(env, waivers)
            failing = {e["id"] for e in env["entries"] if e["severity"] == "fail"}
            ignored = [r for r in waiver.rejected(notes) if r["id"] in failing]  # the person is told; the check stays red
            if ignored:
                env = dict(env, waivers_ignored=ignored)
        except C.ApiError as e:  # the result stands as it is: an unread waiver never turns a fail into a pass
            print(f"mech-comment: PR comments not read, no waiver applied: {e}", file=sys.stderr)
        body, rc = C.render(env), C.exit_code(env)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(body)

    run_head = env["head"] if env is not None else args.head
    try:
        action, out = C.publish(call, api, repo, args.pr, run_head, body, author)
    except C.ApiError as e:
        if e.status == 403 and "Resource not accessible" in str(e.body):  # GitHub's words for a read-only token
            print("::warning::mech-review: this token cannot comment on the PR (a fork or Dependabot PR, or the caller "
                  "lacks `pull-requests: write`). The result is in the job summary; the check result is unchanged.")
            print(f"mech-comment: comment not posted: {e}", file=sys.stderr)
            return rc
        print(f"mech-comment: {e}", file=sys.stderr)
        return 3
    if action == "superseded":
        print(f"mech-comment: superseded by {out}; comment left as is", file=sys.stderr)
        return rc if env is not None else 0
    print(f"mech-comment: {action} comment {out}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
