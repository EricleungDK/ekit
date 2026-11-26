#!/usr/bin/env python3
"""ci-local: what CI runs on ekit's own PRs, on this machine, in CI's order (#84). ekit's development only: not part
of the plugin, and no other OS is simulated (the macOS job stays CI's).

usage: python3 -I scripts/ci-local.py [--base REF] [--head-branch NAME] [--r3-env-dir DIR] [--repo DIR]

Steps, each run whatever the one before gave, with the inputs of .github/workflows/mech-review-self.yml, then the
scenarios:
  mech   the mech checks (R1, R2, R4: mech-review.py all) with this checkout's engine, the mech-review.py beside this
         file, never an installed copy: --stack python, test paths tests/** and .ekit/scenarios/**, protected paths
         .github/**, and R0's runtime half (--r0, as the red-first job passes it) in a fresh dir, as on a cache miss.
         R1 runs on every branch (--agent-prefix '*'): a local branch is often not named as the PR's.
  suite  python -m unittest discover -s tests/py on CI's Python (3.14) through uv with no project
         (uv run --no-project): no uv.lock and no .venv in the repo; one left there anyway is a failed step.
  r3     scripts/r3-local.py with the same inputs and --mutation-budget 20: a fail entry or an unconfirmed survivor
         fails the step.
  scenarios  every .ekit/scenarios scenario (scenarios.py run, the one beside this file), which no CI job runs (#115):
         a FAIL fails the step, naming each; one this machine cannot run is not run here, naming it and what is
         missing: the runner's NOT-RUN (no shell for its run file), or a scenario that exits non-zero with its own one
         fail message on stderr, `ASSERT FAILED: unrunnable here: <what>` (lib.sh: fail "unrunnable here: ..."), as its
         last stderr line and its only ASSERT FAILED line. A timeout or a bad folder stays a FAIL. No verdict line, or
         PASS: 0/0, is not run here.
mech and r3 test the HEAD commit (uncommitted changes are not in them); suite and scenarios run the working tree.
Each step ends as `<step>: passed|failed|not run here: <detail>`; a step that could not run is not a pass.
--r3-env-dir keeps r3-local's tool and results (its --env-dir; your own dir, never one another run uses).
exit: 0 every step passed; 1 a step failed or could not run here; 2 usage, or a base that is not a commit (no step ran).
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

EXIT = __doc__[__doc__.index("exit: "):].strip()
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS)
ENGINE = os.path.join(SCRIPTS, "mech-review.py")
R3_LOCAL = os.path.join(SCRIPTS, "r3-local.py")
RUNNER = os.path.join(SCRIPTS, "scenarios.py")

# ekit's caller inputs (.github/workflows/mech-review-self.yml) and CI's Python (ubuntu-latest's python3)
STACK = "python"
TEST_PATHS = ("tests/**", ".ekit/scenarios/**")
PROTECTED_PATHS = (".github/**",)
MUTATION_BUDGET = "20"
CI_PYTHON = "3.14"
UV = ["uv", "run", "--no-project", "--python", CI_PYTHON]
LEFT_BEHIND = ("uv.lock", ".venv")  # what a uv run with a project writes into the repo

PASSED, FAILED, NOT_RUN = "passed", "failed", "not run here"
# a scenario's own fail message when this machine lacks a tool it needs (lib.sh: fail "unrunnable here: <what>")
UNRUNNABLE = re.compile(r"^ASSERT FAILED: unrunnable here: (.+)$")
# the runner's verdict line, once every scenario ran; an unfiltered run may print `N of M features working` after it
VERDICT = re.compile(r"^(PASS|FAIL|NOT-RUN): ((\d+)/(\d+) scenarios)$")


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


def _inputs(a):
    """the arguments the engine's `all` and r3-local share: the commits, the stack and the test paths"""
    return (["--repo", a.repo, "--base", a.base_sha, "--head", a.head_sha, "--stack", STACK]
            + [x for g in TEST_PATHS for x in ("--test-paths", g)])


def mech(run, a):
    branch = a.head_branch
    if branch is None:
        rc, out, _ = run(["git", "-C", a.repo, "rev-parse", "--abbrev-ref", "HEAD"])
        branch = out.strip() if rc == 0 and out.strip() else "HEAD"
    argv = [sys.executable, "-I", ENGINE, "all"] + _inputs(a) + ["--head-branch", branch, "--agent-prefix", "*"]
    argv += [x for g in PROTECTED_PATHS for x in ("--protected-paths", g)]
    # CI's red-first job passes --r0 a cache dir it first empties; a miss proves the runtime half there, as this does
    with tempfile.TemporaryDirectory(prefix="ekit-ci-local-r0-") as r0:
        rc, out, err = run(argv + ["--r0", r0])
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
    argv = [sys.executable, "-I", R3_LOCAL] + _inputs(a) + ["--mutation-budget", MUTATION_BUDGET]
    argv += ["--env-dir", a.r3_env_dir] if a.r3_env_dir else []
    rc, out, err = run(argv)
    _show(out, err)
    summary = next(iter(out.splitlines()), "")
    if rc == 0:
        return PASSED, summary or "no production file changed in scope"
    if rc == 1:
        bad = [l for l in out.splitlines()[1:] if l.startswith(("fail ", "unconfirmed "))]  # [0]: the summary
        return FAILED, f"{summary} ({len(bad)} fail or unconfirmed entr{'y' if len(bad) == 1 else 'ies'})"
    return NOT_RUN, f"r3-local.py exit {rc}: {_last(err, 'no result')}"


def _runner():
    """scripts/scenarios.py as a module: where its run wrote results.json, and which rows it could not run (env)"""
    spec = importlib.util.spec_from_file_location("ekit_scenarios", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fail_message(transcript):
    """the scenario's own fail message: the last line it wrote to stderr, when that is its only `ASSERT FAILED: ` line
    (lib.sh's fail writes one, then exits). Else "": a tail of captured output, or a quoted failure, is no message."""
    if not isinstance(transcript, str):  # open() takes an int as a file descriptor: never one of this process's
        raise TypeError(f"transcript {transcript!r} is not a path")
    with open(transcript, encoding="utf-8", errors="replace") as f:
        text = f.read()
    err = text.partition("\n--- stderr ---\n")[2].rsplit("\n--- exit:", 1)[0]
    lines = [x.strip() for x in err.splitlines() if x.strip()]
    return lines[-1] if lines and [x for x in lines if x.startswith("ASSERT FAILED: ")] == lines[-1:] else ""


def scenarios(run, a):
    rc, out, err = run([sys.executable, "-I", RUNNER, "--repo", a.repo, "run"])
    _show(out, err)
    verdict = next(filter(None, map(VERDICT.match, reversed(out.splitlines()))), None)
    if not verdict:  # no scenarios, or the runner stopped before its verdict
        return NOT_RUN, f"scenarios.py run exit {rc}: {_last(err, _last(out, 'no result'))}"
    word, counted, passed, total = verdict.groups()
    if total == "0":
        return NOT_RUN, f"no scenario ran ({verdict.group(0)})"
    if rc == 0 and word == "PASS" and passed == total:  # all three say so, or the rows below decide
        return PASSED, counted
    try:  # each scenario's reason and transcript: what tells a missing tool from a failure
        why, rows, failed, unrunnable = _read_rows(a.repo)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:  # results.json of another shape
        return NOT_RUN, f"{verdict.group(0)}, but no readable results.json ({type(e).__name__}: {e})"
    if why:  # the run itself wrote into the repo: none of its verdicts proves anything
        return FAILED, why
    if failed:
        also = f"; not run here: {'; '.join(unrunnable)}" if unrunnable else ""
        return FAILED, f"{len(failed)} of {len(rows)} failed: {', '.join(failed)}{also}"
    if unrunnable:
        return NOT_RUN, "; ".join(unrunnable)
    return NOT_RUN, f"{verdict.group(0)}, but results.json names no failed or unrunnable scenario"


def _read_rows(repo):
    """(the run's own reason, its rows, failed rows, unrunnable rows) from the results.json the run wrote"""
    sc = _runner()
    with open(os.path.join(sc.outdir(repo), "results.json"), encoding="utf-8") as f:
        doc = json.load(f)
    rows, failed, unrunnable = list(doc["scenarios"]), [], []
    for r in rows:
        if not r.get("reason"):
            continue
        if sc.not_here(r):  # the runner's own: no shell for the run file
            unrunnable.append(f"{r['id']}: {r['reason']}")
            continue
        # only a plain exit-code failure can be a missing tool: a timeout or a bad folder is the runner's own FAIL
        m = r["reason"] == f"exit {r.get('exit')}" and UNRUNNABLE.match(_fail_message(r["transcript"]))
        if m:
            unrunnable.append(f"{r['id']}: {m.group(1)}")
        else:
            failed.append(f"{r['id']} ({r['reason']})")
    return doc.get("reason"), rows, failed, unrunnable


STEPS = (("mech", mech), ("suite", suite), ("r3", r3), ("scenarios", scenarios))


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
