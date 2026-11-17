#!/bin/bash
# Structural test of the mech-waive reusable workflow (a /mech-waive comment re-runs the report job) and ekit's self caller.
# Stdlib line-based parse (no PyYAML), as in mech-review-workflow.test.sh.
source "$(dirname "$0")/lib.sh"
python3 -I - "$ROOT" <<'PY'
import os
import re
import sys

ROOT = sys.argv[1]
FAILS = 0


def check(name, cond, detail=""):
    global FAILS
    if cond:
        print(f"  ok   {name}")
    else:
        FAILS += 1
        print(f"  FAIL {name}")
        if detail:
            print(f"       {detail}")


def read(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read().splitlines()


def indent(line):
    return len(line) - len(line.lstrip(" "))


def meaningful(line):
    s = line.strip()
    return bool(s) and not s.startswith("#")


def block(lines, key, at=None):
    """Raw lines under the first mapping key `key` (optionally at indent `at`). None if absent."""
    if lines is None:
        return None
    for n, line in enumerate(lines):
        if meaningful(line) and line.strip().startswith(key + ":") and (at is None or indent(line) == at):
            base = indent(line)
            out = []
            for later in lines[n + 1:]:
                if meaningful(later) and indent(later) <= base:
                    break
                out.append(later)
            return out
    return None


def child_lines(blk):
    lines = [l for l in (blk or []) if meaningful(l)]
    if not lines:
        return []
    base = min(indent(l) for l in lines)
    return [l for l in lines if indent(l) == base]


def child_keys(blk):
    return {l.strip().split(":")[0] for l in child_lines(blk) if not l.strip().startswith("-")}


def value(blk, key):
    for l in child_lines(blk):
        if l.strip().startswith(key + ":"):
            return l.strip()[len(key) + 1:].strip().strip("'\"")
    return None


def text(lines):
    return "\n".join(lines or [])


def perms(lines):
    blk = block(lines, "permissions", 0) or []
    return {k: value(blk, k) for k in child_keys(blk)}


def scalar(blk, key):
    """A child key's value with its folded or literal continuation lines joined by spaces."""
    head = value(blk, key)
    if head is None:
        return None
    more = [l.strip() for l in (block(blk, key) or []) if meaningful(l)]
    return " ".join([head.lstrip(">|-")] + more).strip() if head[:1] in (">", "|") else head


def step(lines, name):
    """Lines of the step `- name: <name>` (to the next `- name:`), stripped. [] if absent."""
    start = next((n for n, l in enumerate(lines) if l.strip() == f"- name: {name}"), None)
    if start is None:
        return []
    out = []
    for l in lines[start + 1:]:
        if l.strip().startswith("- name:"):
            break
        out.append(l.strip())
    return out


THREE = {"actions": "write", "pull-requests": "read", "contents": "read"}

# ---- reusable workflow ----
RW = ".github/workflows/mech-waive.yml"
W = read(RW)
check("reusable: file exists", W is not None, RW)
W = W or []
header = [l for l in W[:next((n for n, l in enumerate(W) if l.startswith("on:")), len(W))] if l.startswith("#")]
ht = " ".join(l.lstrip("# ") for l in header)
check("reusable: header says callers trigger on issue_comment created, edited, deleted",
      "issue_comment" in ht and "created, edited, deleted" in ht, ht)
check("reusable: header says issue_comment workflows run from the default branch", "default branch" in ht, ht)
check("reusable: header says it never runs PR code", "never runs PR code" in ht, ht)

on = block(W, "on", 0) or []
check("reusable: on is workflow_call only", child_keys(on) == {"workflow_call"}, str(child_keys(on)))
check("reusable: workflow_call takes no inputs", child_keys(block(on, "workflow_call") or []) == set(),
      str(child_keys(block(on, "workflow_call") or [])))
check("reusable: top permissions exactly actions write, pull-requests read, contents read", perms(W) == THREE, str(perms(W)))
check("reusable: no write permission but actions",
      [k for k, v in perms(W).items() if v == "write"] == ["actions"], str(perms(W)))
check("reusable: no job-level permissions (the top-level three are the whole grant)",
      [l for l in W if re.match(r"\s+permissions:", l)] == [], str([l for l in W if "permissions:" in l]))
check("reusable: no pull_request_target", "pull_request_target" not in text(W))

jobs = block(W, "jobs", 0) or []
check("reusable: exactly one job", len(child_keys(jobs)) == 1, str(child_keys(jobs)))
J = block(jobs, next(iter(child_keys(jobs)), "")) or []
jt = text(J)
check("reusable: job named mech-waive re-run report", value(J, "name") == "mech-waive re-run report", str(value(J, "name")))

cond = scalar(J, "if") or ""
clauses = [c.strip() for c in cond.split("&&")]
check("if: every clause must hold (joined by && only, no ||)", "||" not in cond and len(clauses) == 5, cond)
check("if: the comment is on a PR", "github.event.issue.pull_request" in clauses, str(clauses))
check("if: the body has /mech-waive", "contains(github.event.comment.body, '/mech-waive')" in clauses, str(clauses))
check("if: not a bot", "github.event.comment.user.type != 'Bot'" in clauses, str(clauses))
check("if: not the sticky comment (its ready-made /mech-waive lines would loop)",
      "!startsWith(github.event.comment.body, '<!-- mech-review -->')" in clauses, str(clauses))
check("if: author is OWNER, MEMBER or COLLABORATOR",
      "contains(fromJSON('[\"OWNER\", \"MEMBER\", \"COLLABORATOR\"]'), github.event.comment.author_association)" in clauses,
      str(clauses))

conc = block(J, "concurrency") or []
check("concurrency: one group per PR number", "github.event.issue.number" in (value(conc, "group") or ""), text(conc))
check("concurrency: a queued re-run is not cancelled", value(conc, "cancel-in-progress") == "false", text(conc))

co = step(J, "ekit engine checkout (the ref this workflow was called at)")
check("checkout: the ekit engine at job.workflow_repository / job.workflow_sha",
      "uses: actions/checkout@v4" in co and "repository: ${{ job.workflow_repository }}" in co
      and "ref: ${{ job.workflow_sha }}" in co and "path: ekit" in co, str(co))
check("checkout: persist-credentials false", "persist-credentials: false" in co, str(co))
check("checkout: the only checkout is the engine's (never the PR code)",
      jt.count("actions/checkout@") == 1 and jt.count("repository: ${{ job.workflow_repository }}") == 1, jt)
check("checkout: no PR head ref anywhere", re.search(r"pull_request\.head|head\.sha|head_ref|refs/pull", jt) is None, jt)

rs = step(J, "re-run the report job")
check("re-run: invokes mech-rerun.py with the env-passed PR number",
      'run: python3 -I ekit/scripts/mech-rerun.py --pr "$PR_NUMBER"' in rs, str(rs))
check("re-run: PR number from the issue, through env", "PR_NUMBER: ${{ github.event.issue.number }}" in rs, str(rs))
check("re-run: token through env", "GITHUB_TOKEN: ${{ github.token }}" in rs, str(rs))
check("no ${{ }} inside any run: (injection)", not any(l.strip().startswith("run:") and "${{" in l for l in W),
      str([l for l in W if l.strip().startswith("run:")]))
check("reusable: no comment body ever reaches a step (only the if: reads it)",
      sum("github.event.comment.body" in l for l in W) == 2, str([l for l in W if "comment.body" in l]))

# ---- ekit's own caller ----
SW = ".github/workflows/mech-waive-self.yml"
S = read(SW)
check("self: file exists", S is not None, SW)
S = S or []
son = block(S, "on", 0) or []
check("self: on issue_comment only", child_keys(son) == {"issue_comment"}, str(child_keys(son)))
types = (value(block(son, "issue_comment") or [], "types") or "").strip("[]")
check("self: issue_comment types created, edited, deleted",
      [t.strip() for t in types.split(",")] == ["created", "edited", "deleted"], types)
check("self: permissions exactly actions write, pull-requests read, contents read", perms(S) == THREE, str(perms(S)))
sjobs = block(S, "jobs", 0) or []
local = [k for k in child_keys(sjobs) if value(block(sjobs, k) or [], "uses") == "./.github/workflows/mech-waive.yml"]
check("self: exactly one job, and it calls the local reusable workflow", len(local) == 1 and len(child_keys(sjobs)) == 1,
      str(child_keys(sjobs)))
check("self: no pull_request_target", "pull_request_target" not in text(S))

print("")
sys.exit(1 if FAILS else 0)
PY
