#!/usr/bin/env python3
"""ci-local: what CI runs on ekit's own PRs, on this machine, in CI's order (#84). ekit's development only: not part
of the plugin, and no other OS is simulated (the macOS job stays CI's).

usage: python3 -I scripts/ci-local.py [--base REF] [--head-branch NAME] [--r3-env-dir DIR] [--repo DIR]

Steps, each run whatever the one before gave, with the inputs of .github/workflows/mech-review-self.yml:
  mech   the mech checks (R1, R2, R4: mech-review.py all) with this checkout's engine, the mech-review.py beside this
         file, never an installed copy: --stack python, test paths tests/** and .ekit/scenarios/**, protected paths
         .github/**. R1 runs on every branch (--agent-prefix '*'): a local branch is often not named as the PR's.
  suite  python -m unittest discover -s tests/py on CI's Python (3.14) through uv with no project
         (uv run --no-project): no uv.lock and no .venv in the repo; one left there anyway is a failed step.
  r3     scripts/r3-local.py with the same inputs and --mutation-budget 20: a fail entry or an unconfirmed survivor
         fails the step.
mech and r3 test the HEAD commit (uncommitted changes are not in them); suite runs the working tree.
Each step ends as `<step>: passed|failed|not run here: <detail>`; a step that could not run is not a pass.
--r3-env-dir keeps r3-local's tool and results (its --env-dir; your own dir, never one another run uses).
exit: 0 every step passed; 1 a step failed or could not run here; 2 usage, or a base that is not a commit (no step ran).
"""
import argparse
import json
import os
import subprocess
import sys

EXIT = __doc__[__doc__.index("exit: "):].strip()
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS)
ENGINE = os.path.join(SCRIPTS, "mech-review.py")
R3_LOCAL = os.path.join(SCRIPTS, "r3-local.py")

# ekit's caller inputs (.github/workflows/mech-review-self.yml) and CI's Python (ubuntu-latest's python3)
STACK = "python"
TEST_PATHS = ("tests/**", ".ekit/scenarios/**")
PROTECTED_PATHS = (".github/**",)
MUTATION_BUDGET = "20"
CI_PYTHON = "3.14"
UV = ["uv", "run", "--no-project", "--python", CI_PYTHON]
LEFT_BEHIND = ("uv.lock", ".venv")  # what a uv run with a project writes into the repo

PASSED, FAILED, NOT_RUN = "passed", "failed", "not run here"


class Stop(Exception):
    pass


def run_cmd(argv, cwd=None):
    """(exit code, stdout, stderr) of one command; a missing executable is 127, as a shell reports it."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        return 127, "", f"{argv[0]}: {e}\n"
    return p.returncode, p.stdout, p.stderr


def _last(text, default):
    lines = [l for l in text.splitlines() if l.strip()]
    return lines[-1].strip() if lines else default


def _show(out, err):
    """a step's own output, as it printed it (captured, so it shows when the step ends)"""
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(err.rstrip(), file=sys.stderr)


def mech(run, a):
    branch = a.head_branch
    if branch is None:
        rc, out, _ = run(["git", "-C", a.repo, "rev-parse", "--abbrev-ref", "HEAD"])
        branch = out.strip() if rc == 0 and out.strip() else "HEAD"
    argv = [sys.executable, "-I", ENGINE, "all", "--repo", a.repo, "--base", a.base_sha, "--head", a.head_sha,
            "--stack", STACK, "--head-branch", branch, "--agent-prefix", "*"]
    argv += [x for g in TEST_PATHS for x in ("--test-paths", g)]
    argv += [x for g in PROTECTED_PATHS for x in ("--protected-paths", g)]
    rc, out, err = run(argv)
    if err.strip():
        print(err.rstrip(), file=sys.stderr)
    if rc > 1:
        return NOT_RUN, f"mech-review.py all exit {rc}: {_last(err, 'no result')}"
    try:
        env = json.loads(out)
        summary, checks, entries = env["summary"], env["checks"], env["entries"]
        print(summary)
        for e in entries:
            print(f"{e['severity']} {e['id']} {e['file']}:{e['line']} {e['problem']}")
        na = [f"{c} n/a ({k['note']})" for c, k in sorted(checks.items()) if k["status"] == "n/a"]
    except (ValueError, KeyError, TypeError) as e:
        return NOT_RUN, f"mech-review.py all exit {rc}: no usable result ({type(e).__name__}: {e})"
    if rc == 1:
        return FAILED, summary
    if na:  # the toolchain is missing here: CI has it, so this is not a pass
        return NOT_RUN, "; ".join(na)
    return PASSED, summary


def suite(run, a):
    rc, out, err = run(UV + ["python", "-I", "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], cwd=a.repo)
    if rc == 127:
        return NOT_RUN, f"uv not found ({_last(err, 'not on PATH')}): CI's Python {CI_PYTHON} comes through uv"
    if rc != 0:
        return NOT_RUN, f"uv has no Python {CI_PYTHON} here: {_last(err, f'exit {rc}')}"
    if out.strip() != CI_PYTHON:
        return NOT_RUN, f"uv ran Python {out.strip() or '?'}, not {CI_PYTHON}"
    before = {n for n in LEFT_BEHIND if os.path.lexists(os.path.join(a.repo, n))}
    rc, out, err = run(UV + ["python", "-m", "unittest", "discover", "-s", "tests/py"], cwd=a.repo)
    _show(out, err)
    ran = next((l.strip() for l in reversed((err + out).splitlines()) if l.startswith("Ran ")), "no `Ran` line")
    left = [n for n in LEFT_BEHIND if n not in before and os.path.lexists(os.path.join(a.repo, n))]
    if left:
        return FAILED, f"left {' and '.join(left)} in the repo (want uv run --no-project)"
    if rc != 0:
        return FAILED, f"{ran}, {_last(err + out, f'exit {rc}')} (Python {CI_PYTHON})"
    return PASSED, f"{ran} (Python {CI_PYTHON})"


def r3(run, a):
    argv = [sys.executable, "-I", R3_LOCAL, "--repo", a.repo, "--base", a.base_sha, "--head", a.head_sha,
            "--stack", STACK]
    argv += [x for g in TEST_PATHS for x in ("--test-paths", g)]
    argv += ["--mutation-budget", MUTATION_BUDGET] + (["--env-dir", a.r3_env_dir] if a.r3_env_dir else [])
    rc, out, err = run(argv)
    _show(out, err)
    summary = next(iter(out.splitlines()), "")
    if rc == 0:
        return PASSED, summary or "no production file changed in scope"
    if rc == 1:
        bad = [l for l in out.splitlines()[1:] if l.startswith(("fail ", "unconfirmed "))]  # [0]: the summary
        return FAILED, f"{summary} ({len(bad)} fail or unconfirmed entr{'y' if len(bad) == 1 else 'ies'})"
    return NOT_RUN, f"r3-local.py exit {rc}: {_last(err, 'no result')}"


STEPS = (("mech", mech), ("suite", suite), ("r3", r3))


def _sha(run, repo, ref):
    rc, out, err = run(["git", "-C", repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"])
    if rc != 0:
        raise Stop(f"{ref}: not a commit ({_last(err, f'git exit {rc}')})")
    return out.strip()


def parse(argv):
    p = argparse.ArgumentParser(prog="ci-local.py", description="what CI runs on ekit's own PRs, on this machine (#84)",
                                epilog=EXIT)
    p.add_argument("--base", default="origin/main", help="base ref (default origin/main, the PR's base)")
    p.add_argument("--head-branch", metavar="NAME", help="head branch for R1 (default: the checked-out branch)")
    p.add_argument("--r3-env-dir", metavar="DIR", help="r3-local's --env-dir (default: its temp dir, removed)")
    p.add_argument("--repo", default=ROOT, help="git repo (default: this checkout)")
    return p.parse_args(argv)


def main(argv, run=run_cmd):
    a = parse(argv)
    a.repo = os.path.abspath(a.repo)
    try:
        a.base_sha, a.head_sha = _sha(run, a.repo, a.base), _sha(run, a.repo, "HEAD")
    except Stop as e:
        print(f"ci-local: {e}", file=sys.stderr)
        return 2
    print(f"ci-local: base {a.base_sha} head {a.head_sha}")
    _, dirty, _ = run(["git", "-C", a.repo, "status", "--porcelain"])
    if dirty.strip():
        print(f"ci-local: uncommitted changes are not in mech and r3 (they test {a.head_sha})", file=sys.stderr)
    results = []
    for name, step in STEPS:
        print(f"== {name}", flush=True)
        results.append((name,) + step(run, a))
    for name, verdict, detail in results:
        print(f"{name}: {verdict}: {detail}")
    return 0 if all(v == PASSED for _, v, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
