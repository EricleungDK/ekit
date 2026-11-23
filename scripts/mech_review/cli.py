"""CLI: parse args, run the engine, print contract JSON, exit 0 (no fail entries) / 1 (any fail entry) / 2 (usage, git)."""
import argparse
import json
import math
import os
import re
import signal
import sys
import tempfile

from . import adapter_file, doctor, engine, gitio, merge, r0, red, report, resolve, stack_plan
from .stack import ADAPTERS


HELP = """\
mechanical PR checks over base...head (merge-base diff). Prints the contract JSON.

checks (status in envelope: pass | fail | partial | n/a | skipped; the CI report step may turn fail into waived):
  R2  test-diff guard: removed test fn (a rename with the same asserts is not
      a removal); added #[ignore] or a cfg that disables it or its mod; should_panic added to an
      existing test (confirm); fewer asserts in a surviving test fn, or helper asserts per file;
      assert replaced in place, any kind (confirm); changed expected value (confirm); added
      #[allow]/#[expect] without a non-empty reason= or same-line comment; change under protected
      paths (needs-human).
      Test fns are keyed by mod-qualified name (m1::works). A test that loses asserts is exempt
      only up to the asserts gained by a helper it calls by name (call-site, each gain used once).
  R1  red-first (red subcommand): the tests base..head adds or changes, run on the base's production
      code (a worktree at the merge base with head's test-path files on top), must catch the change:
      at least one fails there (a build failure there is compile-red: red; R4 builds it at head). Tests that pass there are
      guards. Commit order and subjects do not matter: a later commit can fix an R1 fail. R4 runs
      the same tests at head. Skipped unless --head-branch starts with an --agent-prefix (default: agent/ claude/
      codex/ copilot/ cursor/; `*` = every branch) and a production file changed; n/a when the toolchain is absent.
  R4  determinism (red subcommand): each new or changed #[test] runs 5x at head; any failing run
      is a fail. n/a when the toolchain is absent.
  R3  mutation on the diff (`mutants`): cargo-mutants `--in-diff` (rust), mutmut (python), Stryker 10.0.0 (ts: changed
      lines, `--mutate` ranges), run in a worktree at head. `baseline` (#46) runs first, once: rust measures the unmutated
      tree and counts the mutants; the shards then skip the baseline (`--baseline skip`, `--timeout` from the baseline)
      and run round-robin over min(shards, mutants, ceil(estimated min / (budget / 2))) shards. python (#64): the whole
      suite once (its session time from pytest's --junit-xml) and mutmut's listing (the mutants on changed lines) give
      the same count, no mutant on a changed line runs no shard; a baseline that measured nothing keeps one shard per
      changed file, at most --shards, and its note says why. Cap --max-mutants N
      (default 40; rust, python; ts by changed lines, #63): the riskiest N run (branch conditions, returns and booleans, arithmetic, the rest,
      strings and arguments last), dealt round-robin over the shards; the rest are untested: partial. Per-mutant timeout: --mutant-timeout SEC, else derived from the
      measured baseline (cargo-mutants' rule). Budget `--mutation-budget MIN` (default 10, per shard and for the baseline;
      python's baseline gives it to the suite run and to the listing each, so it can take about twice that).
      MISSED in a production file -> fail (agent-fixable), one entry per mutant; TIMEOUT and UNVIABLE ignored. Budget
      hit with no MISSED -> partial (tested/total), not blocking. A baseline that fails -> fail; one that times out ->
      n/a (names mutation-budget). Tool not installed -> n/a (env). No production file -> skipped.
      `--shard K/N` runs one of N shards (K is 0-based).
  R0  adapter proof, static half (`r0`, #20; first in `all`): git and adapter only, in a throwaway repo. Each R2 cheat
      (delete, comment out, rename, skip, expected value, weakened assert, suppression without a reason) must give its
      entry; the negative controls (rename with the same asserts, reordered asserts, asserts moved into a helper, the
      empty diff of every fixture) none; an adapter file with a bad ident_chars, no assert shape or an unbalanced
      bracket pair must fail to load cleanly. A failed case: one `fail` entry of class adapter-fix, and R1 R2 R4 are
      n/a (blocked; their entries kept and still counted). A case with no fixture: R0 unproven (never all pass).
  `r2` runs R2. `red` runs R1 and R4. `all` = R1, R2 and R4, after R0's static half (R3 is not in `all`: run `baseline`,
  then `mutants`). `.ekit/scenarios/**` is a test path for every stack, beside --test-paths.
  `mutants` runs R3; `baseline` prints the R3 baseline step: {run, count, mutants, timeout, checks, entries}. A check a subcommand does not run
  is skipped with `not run by <subcommand>`.
  Test runner: the stack default (rust: `cargo test`), or --test-cmd. Env MECH_TEST_STUB=<exe>
  replaces the executable (arguments kept): the injectable runner for tests.
  Crate dir: --project-dir DIR (repo-root relative, default .): R1, R4, R3 and the baseline run there; paths in results stay repo-root.

summary (one line, text format first line and envelope `summary`):
  `all pass <head sha>`: no entries and every check passed (never while a check is skipped or n/a).
  otherwise `<pass|fail> <head sha> (<F> fail, <C> confirm; ran: <checks>[; partial: R3 (<tested>/<total>)]
  [; skipped: <checks>][; n/a: <checks>])`, e.g. `pass <sha> (0 fail, 1 confirm; ran: R2; skipped: R1 R3 R4)`.
  `pass` = no fail entries; `fail` = at least one fail entry; `n/a` = toolchain absent, not run.

doctor (`doctor [--repo .] [--stack S] [--project-dir D] [--no-trial]`, no base or head): finds the stack and project dir,
  reads .github/workflows, trial-runs the tests and the mutation tool at HEAD in a throwaway worktree, and prints
  {ekit, head, detected, inputs, trial, entries, summary}: `inputs` is what the caller needs, each entry names one exact fix.
  Exit 0 no problems, 1 any problem, 2 usage or git error. Writes nothing.

resolve (`resolve --base B --head H [--repo .] [--stack auto|S] [--project-dir D] [--adapter FILE]`): the workflow's
  `stack` job. An explicit --stack is printed as given; auto takes the stacks from the base branch's stack plan, else finds
  the one project at base and at head (doctor's detection over the built-ins and the base's .ekit/adapters/<name>.toml,
  tracked files, git only). Prints {stack, project_dir, error, target_os}, and with several stacks from the plan stack null
  and `stacks` [{name, stack, project_dir, adapter, target_os}]: target_os (linux, macos or windows) is the base stack
  plan's entry's target-os, else the adapter's (--adapter or the repo's file: its target-os), else linux; null with no
  stack. Exit 0, 1 when no single project or no planned stack to run (error names them), 2 usage or git.
  r2 and r0 --stack NAME with no --adapter use the repo's adapter file for NAME at --base, when there is one.

r0 (`r0 --base B --head H --stack S [--adapter FILE] [--fixtures DIR] [--repo .] [--test-paths G] [--project-dir D]`): R0's static half
  for the built-in stack or the adapter file (the PR's version: the file as checked out), with its fixtures (the
  built-in's, `<adapter>.r0/` beside an adapter file, or --fixtures). Exit 0 pass or unproven, 1 a fail entry, 2 usage.

drift (`drift --base B --head H [--repo .] [--format json|text]`): the stack plan's drift check (#56), git only. Check D
  only with a plan (.ekit/stack-plan.toml): one adapter-fix entry for the manifests no stack covers, and messages for
  planned, retiring and vanished stacks. Exit 0 clean or messages only, 1 the adapter-fix entry, 2 bad plan, usage or git.

envelope: ekit (plugin version), base, head (full SHAs), checks, entries, summary.

exit: 0 no fail entries (confirm entries allowed), 1 any fail entry, 2 usage or git error.

Guard exceptions removed (#27): --pr-body is a usage error (exit 2). A fail stays fail until
  the code is fixed; a protected-path change is needs-human. The owner decides with a `/mech-waive <id> <reason>`
  PR comment, which the CI report step applies (mech-comment.py); nothing in the PR's own content can waive.

test paths: a .rs file matching a --test-paths glob is test code; every assert in it (helpers too) counts.
  Other .rs files count asserts inside #[test] fns and #[cfg(test)] mods only, never production code.
  Globs: ** any depth, * one segment.
"""


class Removed(argparse.Action):
    """--pr-body tombstone: guard exceptions are gone (#27). Any use is a usage error."""

    def __call__(self, parser, namespace, values, option_string=None):
        parser.error("--pr-body removed: guard exceptions were removed (#27); a fail stays fail until the code is fixed")


def mutant_timeout_arg(value):
    """--mutant-timeout: `auto` (None: no --timeout is sent) or whole seconds >= 1."""
    if value == "auto":
        return None
    if value.isdigit() and int(value) >= 1:
        return int(value)
    raise argparse.ArgumentTypeError(f"{value!r}: want auto or whole seconds >= 1")


def budget_arg(value):
    """--mutation-budget: minutes, a finite number (nan or inf would reach the shard count and the runner's timeout)."""
    try:
        x = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r}: want minutes, a number") from None
    if not math.isfinite(x):
        raise argparse.ArgumentTypeError(f"{value!r}: want minutes, a finite number")
    return x


def max_mutants_arg(value):
    """--max-mutants: whole number >= 1."""
    if value.isdigit() and int(value) >= 1:
        return int(value)
    raise argparse.ArgumentTypeError(f"{value!r}: want a whole number >= 1")


def project_dir_arg(value):
    """Crate dir relative to the repo root: no `..`, not absolute; `./` and trailing `/` are dropped."""
    if not value or value.startswith("/") or ".." in value.split("/"):
        raise argparse.ArgumentTypeError(f"{value!r}: want a directory under the repo root (no .., not absolute)")
    return "/".join(p for p in value.split("/") if p not in ("", ".")) or "."


def build_parser():
    p = argparse.ArgumentParser(prog="mech-review.py", description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="example: python3 -I scripts/mech-review.py r2 --repo . --base main --head HEAD "
                                       "--stack rust --test-paths 'tests/**' --protected-paths '.github/**'")
    p.add_argument("check", choices=["r2", "red", "all", "mutants", "baseline", "merge", "plan"],
                   help="r2: test-diff guard (R2); red: red-first and determinism (R1, R4); all: R1, R2, R4; "
                        "mutants: mutation on the diff (R3); baseline: the R3 baseline step (run, shard count, derived timeout); "
                        "merge: combine the mutants results (--baseline, --shards, --envelope); plan: does the mutants job run")
    p.add_argument("--repo", default=".", help="git repo (default .)")
    p.add_argument("--base", required=True, help="base ref")
    p.add_argument("--head", required=True, help="head ref")
    p.add_argument("--stack", required=True, metavar="{" + ",".join(sorted(ADAPTERS)) + "}",
                   help="language adapter; with --adapter, the name the adapter file gives")
    p.add_argument("--adapter", metavar="FILE",
                   help="r2, red, all: an adapter file (TOML) that describes the stack named by --stack, in place of a "
                        "built-in; red and all need its [run] table (format: docs/mech-review-ci.md#adapter-file)")
    p.add_argument("--test-paths", action="append", default=[], metavar="GLOB", help="test file glob, repeatable")
    p.add_argument("--fixtures", metavar="DIR", help="all only: R0's fixture dir (default: the built-in stack's)")
    p.add_argument("--protected-paths", action="append", default=[], metavar="GLOB", help="protected file glob, repeatable")
    p.add_argument("--pr-body", nargs="?", action=Removed, help=argparse.SUPPRESS)
    p.add_argument("--format", choices=["json", "text"], default="json", help="json (contract, default) or text (summary + entries)")
    p.add_argument("--head-branch", metavar="NAME", help="head branch name (R1 needs it: CI passes github.head_ref)")
    p.add_argument("--agent-prefix", action="append", metavar="PREFIX",
                   help="agent branch prefix for R1, repeatable or comma-separated (default: " + " ".join(red.AGENT_PREFIXES)
                        + "); * matches every branch")
    p.add_argument("--test-cmd", metavar="CMD", help="test command for R1/R4 (default: the stack's: rust cargo test, python "
                                                       "pytest, ts node_modules/.bin/vitest or jest from package.json)")
    p.add_argument("--project-dir", type=project_dir_arg, default=".", metavar="DIR",
                   help="crate dir under the repo root (default .): R1, R4 and R3 run there; paths stay repo-root")
    p.add_argument("--mutants-cmd", metavar="CMD", help="mutation tool for R3 (default: the stack's: rust cargo mutants, python "
                                                          "mutmut, ts node_modules/.bin/stryker)")
    p.add_argument("--mutation-budget", type=budget_arg, default=10.0, metavar="MIN",
                   help="R3 budget in minutes for this run (default 10); a budget hit is partial, not a failure")
    p.add_argument("--mutant-timeout", type=mutant_timeout_arg, default=None, metavar="SEC|auto",
                   help="R3 per-mutant timeout: auto (default: cargo-mutants' own inline baseline sets it) or whole seconds "
                        "(the shards then skip the baseline: it was measured by `baseline`)")
    p.add_argument("--max-mutants", type=max_mutants_arg, default=40, metavar="N",
                   help="R3 (mutants, baseline): the most mutants tested per PR (default 40), riskiest first; past it R3 "
                        "is partial (rust, python; ts: riskiest changed lines, counted by Stryker's instrumenter)")
    p.add_argument("--shard", metavar="K/N", help="R3 only: run shard K of N (0-based, as cargo-mutants numbers them)")
    p.add_argument("--shards", type=int, default=None, metavar="N",
                   help="baseline: the most mutants shards (default 4; fewer when there are fewer mutants); merge: the number "
                        "of shards that ran (0 only when --baseline says none ran)")
    p.add_argument("--envelope", action="append", metavar="K=FILE",
                   help="merge only: result of shard K (0-based), repeatable; a missing shard fails R3 with a CI entry")
    p.add_argument("--baseline", metavar="FILE", help="merge only: the baseline step's result (`baseline` output)")
    p.add_argument("--baseline-reason", metavar="WHY",
                   help="merge only: why there is no baseline result (its job produced none): R3 fails with a CI entry")
    return p


def render_text(env):
    lines = [env["summary"]] + [f"note: {n}" for n in env.get("notes", [])]
    for e in env["entries"]:
        lines.append(f"{e['severity']} {e['id']} {e['file']}:{e['line']} {e['problem']}")
        lines.append(f"  hint: {e['hint']}")
        lines.append(f"  forbidden: {e['forbidden']}")
    return "\n".join(lines)


SHARD = re.compile(r"^(\d+)/(\d+)$")


def _plan(args):
    """Print {run}: whether the mutants job runs (the baseline step sets the shard count, #46). Exit 0 (2 on a git error)."""
    try:
        out = engine.plan(args.repo, args.base, args.head, args.stack, args.test_paths)
    except gitio.Die as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out))
    return 0


def _baseline(parser, args):
    """Print the baseline step's result (#46): run, count, mutants, timeout and the R3 check. Exit 0 (2 on usage or git
    error). A baseline that fails or times out is a result here, not an exit code: the merge reports it."""
    if args.mutant_timeout is not None:
        parser.error("baseline takes no --mutant-timeout: the baseline is measured once and no per-mutant setting caps it")
    shards = 4 if args.shards is None else args.shards
    if shards < 1:
        parser.error("--shards N: want N >= 1")
    try:
        env = engine.baseline(args.repo, args.base, args.head, args.stack, args.test_paths, args.mutants_cmd,
                              args.mutation_budget, shards, project_dir=args.project_dir, max_mutants=args.max_mutants)
    except gitio.Die as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    print(json.dumps(env, indent=2))
    return 0


def _sha(repo, ref):
    """A full SHA is taken as is (the merge job has no checkout); any other ref is resolved in repo."""
    return ref if re.fullmatch(r"[0-9a-f]{40}", ref) else gitio.resolve(repo, ref)


def _merge(parser, args):
    """Combine the baseline result and the mutants shard envelopes into one R3 envelope on stdout. Exit 1 on any fail entry."""
    n = 1 if args.shards is None else args.shards
    if n < 0:
        parser.error("--shards N: want N >= 0")
    try:
        base = _sha(args.repo, args.base)
        head = _sha(args.repo, args.head)
    except gitio.Die as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    baseline, reason = None, args.baseline_reason
    if args.baseline:
        baseline = merge.load_envelope(args.baseline)
        if baseline is None:
            baseline, reason = None, "no usable result file"
        elif baseline["head"] != head:
            baseline, reason = None, f"result is for an older head, not {head}"
        elif "checks" not in baseline or "R3" not in baseline["checks"]:
            baseline, reason = None, "result has no R3 check"
    if baseline is not None and baseline.get("run") and n < 1:
        parser.error("--shards N: want N >= 1 when the baseline runs the shards")
    shards, reasons = {}, {}
    for item in args.envelope or []:
        k, sep, path = item.partition("=")
        if not sep or not k.isdigit() or int(k) >= n:
            parser.error(f"--envelope {item}: want K=FILE with 0 <= K < {n}")
        k = int(k)
        if k in shards or k in reasons:
            parser.error(f"--envelope {k} given twice: one result file per shard")
        env = merge.load_envelope(path)
        if env is None:
            reasons[k] = "no usable result file"
        elif env["head"] != head:
            reasons[k] = f"result is for an older head, not {head}"
        else:
            shards[k] = env
    for k in range(n):
        shards.setdefault(k, None)
        reasons.setdefault(k, "no result file given")
    env = merge.combine_mutants(base, head, n, shards, reasons, baseline=baseline, baseline_reason=reason)
    print(json.dumps(env, indent=2))
    return 1 if any(e["severity"] == "fail" for e in env["entries"]) else 0


def _doctor(argv):
    p = argparse.ArgumentParser(prog="mech-review.py doctor", description="find a repo's mech-review setup; see the main --help")
    p.add_argument("--repo", default=".", help="git repo (default .)")
    p.add_argument("--stack", choices=sorted(ADAPTERS), help="settles several candidate projects")
    p.add_argument("--project-dir", type=project_dir_arg, metavar="DIR", help="settles several candidate projects")
    p.add_argument("--no-trial", action="store_true", help="read the tree only; run nothing")
    args = p.parse_args(argv)

    def stop(*_):  # unwinds through the trial worktree's cleanup, like Ctrl-C
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stop)
    try:
        env = doctor.run(args.repo, stack=args.stack, project_dir=args.project_dir, run_trial=not args.no_trial)
    except gitio.Die as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    print(json.dumps(env, indent=2))
    return 1 if env["entries"] else 0


def _tracked(repo, ref):
    """The tracked paths at ref from the repo root (also when repo is a subdir), raw (-z: a name is never quoted or split)."""
    return [p for p in gitio.git(repo, "ls-tree", "-r", "-z", "--full-tree", "--name-only", gitio.resolve(repo, ref)).split("\0")
            if p]


def _is_repo(path):
    """True when path is in a git repo (a directory that is not, or none at all: False)."""
    try:
        gitio.git(path, "rev-parse", "--git-dir")
    except gitio.Die:
        return False
    return True


def _detect(args):
    """auto with no plan (#17): (result, {stack: adapter} of the repo's adapter files at the base), detection over the
    built-ins and those files, a file named like a built-in in its place."""
    base_paths = _tracked(args.repo, args.base)
    try:
        repo = stack_plan.repo_adapters(args.repo, gitio.resolve(args.repo, args.base), base_paths)
    except adapter_file.AdapterFileError as e:
        return resolve.fail(args.project_dir, str(e)), {}
    return resolve.pick_pr(base_paths, _tracked(args.repo, args.head), args.stack, args.project_dir,
                           {**ADAPTERS, **repo}), repo


def _named(args):
    """an explicit stack in a git repo (#17): (result, {stack: adapter}) with the adapter the repo defines for that name
    at the base (a plan entry's adapter file, or .ekit/adapters/<name>.toml), else the built-in."""
    base = gitio.resolve(args.repo, args.base)
    try:
        found = stack_plan.repo_adapter(args.repo, base, args.stack, args.project_dir)
    except adapter_file.AdapterFileError as e:
        return {"stack": None, "project_dir": args.project_dir, "error": f"stack {args.stack}: {e}"}, {}
    repo = {args.stack: found} if found is not None else {}
    names = {p.rpartition("/")[2][:-len(".toml")]: None for p in _tracked(args.repo, base)
             if p.rpartition("/")[0] == stack_plan.ADAPTERS_DIR and p.endswith(".toml")
             and stack_plan.valid_name(p.rpartition("/")[2][:-len(".toml")])}
    return resolve.pick_pr([], [], args.stack, args.project_dir, {**ADAPTERS, **names, **repo}), repo


RUN_SIDE = {"red": ("R1", "R4"), "all": ("R1", "R4"), "mutants": ("R3",), "baseline": ("R3",)}


def _not_built(args, adapter=None):
    """A run-side check on a stack the repo's adapter file describes (#17): the run side of an adapter file (#18, #19)
    is not built, so its checks are n/a with the reason, never a usage error or the built-in of that name run in its
    place. plan says run, so the baseline step reports R3's n/a; baseline runs no shard; all still runs R2 (adapter)."""
    if args.check == "plan":
        print(json.dumps({"run": True}))
        return 0
    try:
        base, head, _ = gitio.merge_base(args.repo, args.base, args.head)
        if args.check == "all":
            env = engine.run(args.repo, args.base, args.head, args.stack, args.test_paths, args.protected_paths,
                             which="r2", project_dir=args.project_dir, adapter=adapter)
            checks, entries = env["checks"], env["entries"]
            checks["R3"] = {"status": "skipped", "note": "not run by all: R3 runs only in the mutants subcommand (CI job "
                                                         "mutants)"}
            checks["R0"] = {"status": "skipped", "note": "not run by all on the repo's adapter file: r0 proves it"}
        else:
            checks, entries = {c: {"status": "skipped", "note": f"not run by {args.check}"} for c in report.CHECKS}, []
    except gitio.Die as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    for c in RUN_SIDE[args.check]:
        checks[c] = {"status": "n/a", "note": f"stack `{args.stack}` is the repo's adapter file: {c} through an adapter "
                                              f"file is not built yet (#18, #19)"}
    env = report.envelope(base, head, entries, checks)
    if args.check == "mutants":
        k, _, n = (args.shard or "0/1").partition("/")
        env["shard"] = {"k": int(k), "n": int(n), "max_mutants": args.max_mutants}
    if args.check == "baseline":
        env.update({"run": False, "count": 0, "mutants": 0, "timeout": None})
    print(json.dumps(env, indent=2) if args.format == "json" else render_text(env))
    return 1 if any(e["severity"] == "fail" for e in entries) else 0


def _resolve(argv):
    """`stack: auto` (the workflow's stack job): print {stack, project_dir, error, target_os} (several stacks: `stacks`).
    Exit 0, 1 on error, 2 usage or git."""
    p = argparse.ArgumentParser()  # no help text of its own (#29): the main --help describes resolve
    p.add_argument("--repo", default=".")
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--stack", default=resolve.AUTO)
    p.add_argument("--project-dir", type=project_dir_arg, default=".")
    p.add_argument("--adapter")
    args = p.parse_args(argv)
    adapter = None
    if args.adapter is not None:
        try:
            adapter = adapter_file.load(args.adapter)
        except adapter_file.AdapterFileError as e:
            print(f"mech-review: {e}", file=sys.stderr)
            return 2
        if adapter.name != args.stack:
            print(f"mech-review: adapter file {args.adapter} describes stack `{adapter.name}`, not `{args.stack}`",
                  file=sys.stderr)
            return 2
    try:
        # #56: the base branch's plan (a PR cannot pick its own stacks or runner); a base plan that does not read never
        # blocks the run (its drift check fails D): see stack_plan.target_plan. An explicit stack with no git repo there
        # reads no plan. #17: with a plan, auto takes its stacks from it, and detection is not used.
        bad = plan = None
        repo = {}  # the repo's adapter files in play, by stack
        if args.stack == resolve.AUTO or _is_repo(args.repo):
            plan, bad = stack_plan.target_plan(args.repo, args.base, args.head)
        if adapter is not None:
            got = {"stack": adapter.name, "project_dir": args.project_dir, "error": None}
        elif args.stack == resolve.AUTO and plan is not None and bad is None:
            # only a base plan that reads picks stacks and adapters: the head plan of a PR that fixes a bad one sets
            # target_os at most (#56), and the PR is detected on its base tree with the base's adapter files
            got = resolve.from_plan(stack_plan.to_run(plan, _tracked(args.repo, args.base) + _tracked(args.repo, args.head)),
                                    args.project_dir)
        elif args.stack == resolve.AUTO:
            got, repo = _detect(args)
        elif _is_repo(args.repo):
            got, repo = _named(args)
        else:
            got = resolve.pick_pr([], [], args.stack, args.project_dir)
        entry = stack_plan.entry_for(plan, got["stack"], got["project_dir"])  # none for no stack
    except gitio.Die as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    got["target_os"] = entry.target_os if entry else resolve.target_os(got, adapter or repo.get(got["stack"]))
    if bad is not None and got["stack"] is not None:  # named, so a bad plan never moves the runner silently
        print(f"mech-review: {bad}", file=sys.stderr)
        print("mech-review: the base branch's stack plan does not read: " + (
            "this PR fixes it (it edits the plan or an adapter file and adds no manifest), so its own plan sets target_os"
            if plan is not None else f"no entry sets target_os, the adapter's ({got['target_os']}) applies; the drift "
                                     f"check fails D until a PR fixes the plan"), file=sys.stderr)
    print(json.dumps(got))
    return 1 if got["error"] else 0


def _drift(argv):
    """The drift check (#56): the stack plan against the tracked manifests, git only. Exit 0 clean or messages only,
    1 a fail entry, 2 usage (a bad plan names the entry and the field) or git error."""
    p = argparse.ArgumentParser(prog="mech-review.py drift",
                                description="compare .ekit/stack-plan.toml with the tracked manifests (git only); the "
                                            "base branch's plan judges, a PR that only edits the plan or its adapter "
                                            "files and adds no manifest is judged by its own")
    p.add_argument("--repo", default=".", help="git repo (default .)")
    p.add_argument("--base", required=True, help="base ref")
    p.add_argument("--head", required=True, help="head ref")
    p.add_argument("--format", choices=["json", "text"], default="json", help="json (contract, default) or text")
    args = p.parse_args(argv)
    rc = None
    try:
        env = engine.drift(args.repo, args.base, args.head)
    except gitio.Die as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    except stack_plan.PlanError as e:  # a usage error, and a failing result beside it: never read as no plan
        print(f"mech-review: {e}", file=sys.stderr)
        env, rc = engine.drift_error(args.repo, args.base, args.head, e), 2
    if args.format == "json":
        print(json.dumps(env))  # compact: every reader parses it
    else:
        print(render_text(env))
        for m in env["checks"].get("D", {}).get("messages", []):
            print(f"message: {m}")
    return rc or (1 if any(e["severity"] == "fail" for e in env["entries"]) else 0)


def _load_adapter(path, stack):
    """(the adapter file's Adapter, None), or (None, usage error text)."""
    try:
        adapter = adapter_file.load(path)
    except adapter_file.AdapterFileError as e:
        return None, str(e)
    if adapter.name != stack:
        return None, f"adapter file {path} describes stack `{adapter.name}`, not `{stack}`"
    return adapter, None


def _r0_repo(args, adapter, path):
    """r0 on the repo's adapter file (#17): the file and its fixtures as they are at the base, written to a throwaway
    dir that r0 runs from, so the file keeps its repo path (in the proof's messages, and for R0's editing rules, which
    read its change in the PR from git)."""
    repo = os.path.abspath(args.repo)
    fixtures = os.path.abspath(args.fixtures) if args.fixtures else None
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            stack_plan.write_adapter(repo, gitio.resolve(repo, args.base), path, tmp)
            os.chdir(tmp)
            env = engine.r0(repo, args.base, args.head, args.stack, args.test_paths, adapter=adapter, adapter_path=path,
                            fixtures_dir=fixtures)
        except (gitio.Die, r0.FixtureError) as e:
            print(f"mech-review: {e}", file=sys.stderr)
            return 2
        finally:
            os.chdir(here)
    print(json.dumps(env, indent=2) if args.format == "json" else render_text(env))
    return 1 if any(e["severity"] == "fail" for e in env["entries"]) else 0


def _r0(argv):
    """R0's static half (#20): the adapter against the cheat suite and the controls, git and adapter only. Exit 0 pass
    or unproven, 1 a fail entry, 2 usage or git error."""
    p = argparse.ArgumentParser(prog="mech-review.py r0",
                                description="prove the stack adapter (R0, static half): every R2 cheat caught, every "
                                            "negative control clean, malformed adapter tables refused; git and adapter "
                                            "only, in a throwaway repo")
    p.add_argument("--repo", default=".", help="git repo (default .)")
    p.add_argument("--base", required=True, help="base ref")
    p.add_argument("--head", required=True, help="head ref")
    p.add_argument("--stack", required=True, help="a built-in (" + ", ".join(sorted(ADAPTERS)) + ") or, with --adapter, "
                                                  "the adapter file's name")
    p.add_argument("--adapter", metavar="FILE", help="an adapter file (TOML) in place of the built-in: R0 proves it")
    p.add_argument("--fixtures", metavar="DIR", help="the fixture dir (default: the built-in's, or `<adapter>.r0/` beside "
                                                     "the adapter file)")
    p.add_argument("--test-paths", action="append", default=[], metavar="GLOB", help="test file glob, repeatable")
    p.add_argument("--project-dir", type=project_dir_arg, default=".", metavar="DIR",
                   help="the stack's dir (default .): the plan entry whose adapter file r0 proves (#17)")
    p.add_argument("--format", choices=["json", "text"], default="json", help="json (contract, default) or text")
    args = p.parse_args(argv)
    adapter = None
    if args.adapter is not None:
        adapter, err = _load_adapter(args.adapter, args.stack)
        if err:
            print(f"mech-review: {err}", file=sys.stderr)
            return 2
    else:
        try:  # #17: the repo's adapter file for this stack at the base, as r2 takes it
            found, path = stack_plan.repo_adapter_at(args.repo, gitio.resolve(args.repo, args.base), args.stack,
                                                     args.project_dir)
        except (gitio.Die, adapter_file.AdapterFileError) as e:
            print(f"mech-review: {e}", file=sys.stderr)
            return 2
        if found is not None:
            return _r0_repo(args, found, path)
        if args.stack not in ADAPTERS:
            p.error(f"argument --stack: invalid choice: {args.stack!r} (choose from "
                    + ", ".join(repr(s) for s in sorted(ADAPTERS)) + ")")
    try:
        env = engine.r0(args.repo, args.base, args.head, args.stack, args.test_paths, adapter=adapter,
                        adapter_path=args.adapter, fixtures_dir=args.fixtures)
    except (gitio.Die, r0.FixtureError) as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # never exit 1 with no result: the guard keeps an exit-1 result
        print(f"mech-review: r0 crashed: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(json.dumps(env, indent=2) if args.format == "json" else render_text(env))
    return 1 if any(e["severity"] == "fail" for e in env["entries"]) else 0


def main(argv):
    if argv[:1] == ["r0"]:
        return _r0(argv[1:])
    if argv[:1] == ["drift"]:
        return _drift(argv[1:])
    if argv[:1] == ["doctor"]:
        return _doctor(argv[1:])
    if argv[:1] == ["resolve"]:
        return _resolve(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    adapter = None
    if args.adapter is None and args.check != "merge":
        try:  # #17: the repo's adapter file for this stack at the base, in place of a built-in of that name
            adapter = stack_plan.repo_adapter(args.repo, gitio.resolve(args.repo, args.base), args.stack, args.project_dir)
        except (gitio.Die, adapter_file.AdapterFileError) as e:
            print(f"mech-review: {e}", file=sys.stderr)
            return 2
    # merge reads no tree (the report job has no checkout) and R3 comes from the results it merges: any stack name
    if adapter is None and args.adapter is None and args.stack not in ADAPTERS and not (
            args.check == "merge" and stack_plan.valid_name(args.stack)):
        parser.error(f"argument --stack: invalid choice: {args.stack!r} (choose from "
                     + ", ".join(repr(s) for s in sorted(ADAPTERS)) + ")")
    if args.adapter is not None:
        if args.check not in ("r2", "red", "all"):
            parser.error("--adapter applies to r2, red and all (R3 through an adapter file is not built yet)")
        try:
            adapter = adapter_file.load(args.adapter)
        except adapter_file.AdapterFileError as e:
            print(f"mech-review: {e}", file=sys.stderr)
            return 2
        if args.check != "r2" and adapter.run is None:
            parser.error(f"--adapter applies to r2 only for {args.adapter}: it has no [run] table, and {args.check} runs "
                         "R1 and R4 through [run] and [commands] (format: docs/mech-review-ci.md#adapter-file)")
        if adapter.name != args.stack:
            print(f"mech-review: adapter file {args.adapter} describes stack `{adapter.name}`, not `{args.stack}`",
                  file=sys.stderr)
            return 2
    if args.fixtures is not None and args.check != "all":
        parser.error("--fixtures applies to all and r0 only (R0's fixture dir)")
    if args.check == "merge":
        return _merge(parser, args)
    if adapter is not None and args.adapter is None and args.check != "r2" and args.stack in ADAPTERS:
        # until adapter files have a run side (#18, #19), a repo file named like a built-in judges R2 only: R1, R3 and
        # R4 run the built-in, so adding the file turns no check off. `all` runs one adapter for all its checks
        if args.check == "all":
            parser.error(f"all on stack `{args.stack}`, which the repo's adapter file overrides: R2 is the file's, R1 "
                         f"and R4 the built-in's; run r2 and red apart")
        adapter = None
    if adapter is not None and args.adapter is None and args.check in ("plan", "baseline"):
        return _not_built(args)
    if args.check == "plan":
        return _plan(args)
    if args.check == "baseline":
        return _baseline(parser, args)
    if args.shard is not None:
        m = SHARD.match(args.shard)
        if args.check != "mutants":
            parser.error("--shard applies to the mutants check only")
        if not m or int(m.group(1)) >= int(m.group(2)) or int(m.group(2)) < 1:
            parser.error(f"--shard {args.shard}: want K/N with 0 <= K < N")
    if adapter is not None and args.adapter is None and args.check != "r2":
        return _not_built(args, adapter)
    try:
        env = engine.run(args.repo, args.base, args.head, args.stack, args.test_paths, args.protected_paths,
                         which=args.check, agent_prefix=args.agent_prefix, head_branch=args.head_branch,
                         test_cmd=args.test_cmd, mutants_cmd=args.mutants_cmd,
                         mutation_budget=args.mutation_budget, shard=args.shard, mutant_timeout=args.mutant_timeout,
                         project_dir=args.project_dir, adapter=adapter, max_mutants=args.max_mutants,
                         fixtures_dir=args.fixtures)
    except (gitio.Die, r0.FixtureError) as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    if adapter is not None and args.check != "r2":  # #18: a command the file declares as none is named (red, all);
        env["notes"] = adapter.notes()  # r2 through a file prints what the built-in prints
    if args.format == "json":
        print(json.dumps(env, indent=2))
    else:
        print(render_text(env))
    return 1 if any(e["severity"] == "fail" for e in env["entries"]) else 0
