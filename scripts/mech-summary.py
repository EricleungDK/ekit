#!/usr/bin/env python3
"""mech-summary: one mech-review run in a few lines, from its artifacts (#38).

usage: python3 -I scripts/mech-summary.py <run-id | PR number | #N | PR URL> [--repo OWNER/NAME]
       python3 -I scripts/mech-summary.py --dir DIR   (artifacts already downloaded: one subdir per artifact)

A PR resolves to the run of its newest `mech-review report` check (`gh pr checks`). A run still in progress is a note,
not a result. Otherwise the run's artifacts are downloaded (`gh run download`) to a temp dir, merged as the report job
merges them (the R3 shards with the baseline, then the jobs), and printed: the summary line, each check's status and
note, each shard's note, the fail entries grouped by file. The merged R3 artifact (mech-review-mutants-merged-json) is
used when the run has one. The job list (`gh run view`) tells a baseline that never ran (plan: no production change)
from one that crashed (R3 fails, as in the report). A drift result (mech-review-drift-json, #56) adds check D and
its stack plan messages; a run without one reads as before, unless the guard job failed (its drift step leaves a
result unless it crashed): then D fails, as in the report. Waivers are not applied: the sticky comment applies /mech-waive.
exit: 0 no fail entry; 1 a fail entry; 2 usage, gh error, run in progress, unreadable result, or no artifact.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir from sys.path

from mech_review import merge, report  # noqa: E402 - imported after the sys.path line above

REPORT = "mech-review report"
BASELINE_JOB = "mech-review baseline (R3, once)"  # job names as in mech-review.yml (a test pins them)
PLAN_JOB = "mech-review plan (R3 runs?)"
GUARD_JOB = "mech-review guard (R2)"
NO_DRIFT = "no drift artifact and the guard job did not succeed (see its log)"
JOBS = {"r2": ("mech-review-json", "mech-review.json"), "red": ("mech-review-red-json", "mech-review-red.json")}
# the guard job's drift check (#56, the owner's upload step): merged when the run has it; a run without it reads as before
DRIFT = ("mech-review-drift-json", "mech-review-drift.json")
BASELINE = ("mech-review-baseline-json", "mech-review-baseline.json")
MERGED = ("mech-review-mutants-merged-json", "mutants-merged.json")  # the owner's upload step (docs/mech-review-ci.md)
NO_BASELINE = "no baseline artifact: R3 not planned, or the baseline job crashed (see the run's jobs)"
NO_BASELINE_JSON = "no JSON from the baseline job (see its log)"  # the report job's --baseline-reason


class Stop(Exception):
    pass


def run_cmd(argv, env=None, cwd=None):
    try:
        p = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        return 127, "", f"{argv[0]}: {e}\n"
    return p.returncode, p.stdout, p.stderr


def _repo(repo):
    return ["-R", repo] if repo else []


def _pr(target):
    """The PR number a target names (N below a million, #N, a /pull/N URL with any page after it), or None (a run id)."""
    m = re.fullmatch(r"#(\d+)|https?://\S+/pull/(\d+)(?:[/#?]\S*)?|(\d{1,6})", target)
    return m.group(m.lastindex) if m else None  # one alternative matched: its group is the number


def run_of_pr(run, pr, repo):
    rc, out, err = run(["gh", "pr", "checks", pr, "--json", "name,state,link", *_repo(repo)])
    if rc not in (0, 8) or not out.strip():  # 8: some checks still pending; the list is still printed
        raise Stop(f"gh pr checks {pr}: {err.strip()}")
    ids = [int(m.group(1)) for c in json.loads(out) if c["name"].endswith(REPORT)
           for m in [re.search(r"/runs/(\d+)", c.get("link") or "")] if m]
    if not ids:
        raise Stop(f"PR {pr} has no `{REPORT}` check")
    return str(max(ids))


def _load(d, art):
    return merge.load_envelope(os.path.join(d, *art))  # None when missing or unreadable


def _baseline(d):
    """(baseline envelope, None) or (None, why it is unusable: None when there is no artifact)."""
    path = os.path.join(d, *BASELINE)
    if not os.path.exists(path):
        return None, None
    b = merge.load_envelope(path)
    ok = (b is not None and all(k in b for k in ("run", "count", "base")) and isinstance(b.get("checks"), dict)
          and "R3" in b["checks"])
    return (b, None) if ok else (None, "no usable result file")


def mutants_env(d, jobs, ends):
    """(R3 envelope or None, shard lines, R3 line override or None), as the report job's merge step builds it.
    jobs: {job name suffix: conclusion} from `gh run view`, or None (--dir: unknown). ends: (base, head) of the run."""
    b, bad = _baseline(d)
    merged = _load(d, MERGED)
    if b is None and merged is None:
        if bad is None:
            concl = (jobs or {}).get(BASELINE_JOB)
            plan = (jobs or {}).get(PLAN_JOB)
            if concl is None:  # --dir, or a job list without it: unknown
                return None, [], f"R3 skipped: {NO_BASELINE}"
            if concl == "skipped" and plan == "success":
                return None, [], "R3 skipped: not run: the plan found no production file changed"
            bad = NO_BASELINE_JSON  # the report merges with --baseline-reason: baseline ran, or plan did not succeed
        return merge.combine_mutants(*ends, 0, {}, {}, baseline=None, baseline_reason=bad), [], None
    n = b["count"] if b is not None and b["run"] else 0
    shards, reasons, lines = {}, {}, []
    for k in range(n):
        name = f"mech-review-mutants-{k}"
        path = os.path.join(d, name, "mech-review-mutants.json")
        env = merge.load_envelope(path)
        if not os.path.exists(path):
            reasons[k] = f"no artifact {name}"
        elif env is None:
            reasons[k] = "no usable result file"
        elif env["head"] != b["head"]:
            reasons[k] = f"result is for an older head, not {b['head']}"
        elif not isinstance(env["checks"], dict) or "R3" not in env["checks"]:
            reasons[k] = "result has no R3 check"
        else:
            shards[k] = env
            c = env["checks"]["R3"]
            wall = (c.get("timing") or {}).get("wall_s")
            lines.append(f"  shard {k}/{n}: {c['status']}: {c['note']}" + (f" (wall {wall} s)" if wall is not None else ""))
            continue
        lines.append(f"  shard {k}/{n}: no result ({reasons[k]})")
    if merged is not None:
        return merged, lines, None
    return merge.combine_mutants(b["base"], b["head"], n, shards, reasons, baseline=b), lines, None


def _check_line(name, c):
    if name == "R3" and c.get("tested") is not None:
        total = "?" if c.get("total") is None else c["total"]
        return f"R3 {c['status']} ({c['tested']}/{total} tested)"
    return f"{name} {c['status']}: {c['note']}"


def summarize(d, label, jobs=None):
    parts, reasons = {}, {}
    for job, art in JOBS.items():
        parts[job] = _load(d, art)
        if parts[job] is None:
            reasons[job] = f"no artifact {art[0]}"
    present = [e for e in parts.values() if e is not None]
    ends = (present[0]["base"], present[0]["head"]) if present else ("", "")
    try:
        mut, shard_lines, r3_line = mutants_env(d, jobs, ends)
        if mut is not None:
            parts["mutants"] = mut
        if os.path.exists(os.path.join(d, *DRIFT)):
            parts["drift"] = _load(d, DRIFT)
            reasons["drift"] = "no usable result file"
        elif (jobs or {}).get(GUARD_JOB, "success") != "success":
            # the drift step leaves a result unless it crashed, and then the guard job fails: never read as no plan
            parts["drift"], reasons["drift"] = None, NO_DRIFT
        if all(v is None for v in parts.values()):
            raise Stop(f"no mech-review artifact in {label}")
        env = merge.merge(parts, reasons)
        checks = [r3_line if name == "R3" and r3_line else _check_line(name, env["checks"][name])
                  for name in report.names(env["checks"])]
        checks += [f"  stack plan: {m}" for m in (env["checks"].get("D") or {}).get("messages") or []]
    except (KeyError, TypeError, ValueError) as e:
        raise Stop(f"unreadable result in {label} ({type(e).__name__}: {e})")
    fails = [e for e in env["entries"] if e["severity"] == "fail"]
    failed = [c for c in report.names(env["checks"]) if env["checks"][c]["status"] == "fail"]
    print(f"{label}: {env['summary']}")  # report.summarize reads `fail` for a failed check with no fail entry
    for line in checks:
        print(line)
    if shard_lines:
        print("shards:")
        for line in shard_lines:
            print(line)
    confirms = sum(1 for e in env["entries"] if e["severity"] == "confirm")
    if fails:
        print(f"fail entries ({len(fails)}) by file:")
        last = None
        for e in sorted(fails, key=lambda e: (e["file"] == "", e["file"], e["line"])):
            if e["file"] != last:
                last = e["file"]
                print(f"  {last or '(no file: CI)'}")
            print(f"    {e['id']} :{e['line']} {e['problem']}")
    if confirms:
        print(f"confirm entries: {confirms} (see the PR comment)")
    if fails:
        print("waivers: not applied here (the sticky comment applies /mech-waive)")
    return 1 if fails or failed else 0  # a failed check is a red run, entry or not


def run_jobs(run, rid, repo):
    """{job name suffix: conclusion} of a finished run, or Stop with the in-progress note on stdout."""
    rc, out, err = run(["gh", "run", "view", rid, "--json", "status,jobs", *_repo(repo)])
    if rc != 0:
        raise Stop(f"gh run view {rid}: {err.strip()}")
    try:
        view = json.loads(out)
        status, jobs = view["status"], view["jobs"]
        done = sum(1 for j in jobs if j["status"] == "completed")
        conclusions = {j["name"].rsplit(" / ", 1)[-1]: j["conclusion"] for j in jobs}
    except (ValueError, KeyError, TypeError) as e:
        raise Stop(f"gh run view {rid}: unreadable output ({type(e).__name__}: {e})")
    if status != "completed":
        print(f"run {rid}: in progress ({done} of {len(jobs)} jobs done): rerun when it completes")
        raise Stop(None)
    return conclusions


def main(argv, run=run_cmd):
    p = argparse.ArgumentParser(prog="mech-summary.py", description="a mech-review run in a few lines (#38)")
    p.add_argument("target", nargs="?", help="run id, PR number, #N or PR URL")
    p.add_argument("--repo", metavar="OWNER/NAME", help="GitHub repo (default: the current dir's)")
    p.add_argument("--dir", metavar="DIR", help="artifacts already downloaded here; no gh call")
    a = p.parse_args(argv)
    if not a.target and not a.dir:
        p.error("give a run id or PR, or --dir")
    try:
        if a.dir:
            return summarize(a.dir, a.dir)
        pr = _pr(a.target)
        rid = run_of_pr(run, pr, a.repo) if pr else a.target
        jobs = run_jobs(run, rid, a.repo)
        tmp = tempfile.mkdtemp(prefix="ekit-summary-")
        try:
            rc, _, err = run(["gh", "run", "download", rid, "-D", tmp, *_repo(a.repo)])
            if rc != 0:
                raise Stop(f"gh run download {rid}: {err.strip()}")
            return summarize(tmp, f"run {rid}", jobs)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Stop as e:
        if e.args[0]:
            print(f"mech-summary: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
