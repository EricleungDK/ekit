"""Mechanical review engine: runs the checks a subcommand asks for and builds the contract envelope."""
import os

from . import mutants, r0 as r0_mod, red, report, stack_plan
from . import gitio
from .gitio import Review, merge_base
from .r2 import r2
from .report import CHECKS, envelope, finalize
from .stack import ADAPTERS

# test paths the core adds for every stack (#20): scenarios are test code whatever the caller's test-paths say
CORE_TEST_PATHS = (".ekit/scenarios/**",)


def test_paths(globs):
    """the caller's test globs plus CORE_TEST_PATHS (once each)."""
    globs = list(globs)
    return globs + [g for g in CORE_TEST_PATHS if g not in globs]


def prove(stack, test_globs, adapter=None, adapter_path=None, fixtures_dir=None, parser_hold=r0_mod.NO_BASE):
    """R0's static half for one adapter: (check, raw entries). adapter: an adapter file's Adapter (adapter_path its file,
    read again as bytes for the malformed cases), else the built-in ADAPTERS[stack]. fixtures_dir: the fixture dir, else
    the adapter file's (beside it) or the built-in's. r0.FixtureError: a fixture dir that does not read."""
    raw = None
    if adapter is not None and adapter_path is not None:
        with open(adapter_path, "rb") as f:
            raw = f.read()
    if fixtures_dir is None:
        fixtures_dir = r0_mod.adapter_fixtures(adapter_path) if adapter_path else r0_mod.builtin_fixtures(stack)
    return r0_mod.static(adapter or ADAPTERS[stack](), r0_mod.load_fixtures(fixtures_dir), test_paths(test_globs),
                         adapter_raw=raw, where=adapter_path or "", parser_hold=parser_hold)


def r0(repo, base_ref, head_ref, stack, test_globs, adapter=None, adapter_path=None, fixtures_dir=None):
    """The `r0` subcommand: R0's static half as an envelope (the other checks skipped, `not run by r0`)."""
    base, head, mb = merge_base(repo, base_ref, head_ref)
    # a parser-backed adapter's command runs only when it is the base branch's (#27): never one the PR wrote, and
    # never with a word inside the reviewed checkout, in R0's own throwaway repos too
    if hasattr(adapter, "in_checkout"):
        adapter = adapter.in_checkout(repo)
    check, raw = prove(stack, test_globs, adapter, adapter_path, fixtures_dir,
                       r0_mod.parser_hold(repo, mb, adapter, adapter_path))
    raw += _edit_rules(repo, mb, head, check, [adapter_path] if adapter_path else [])
    checks = {c: {"status": "skipped", "note": "not run by r0"} for c in CHECKS}
    checks["R0"] = check
    return envelope(base, head, finalize(raw), checks)


def _edit_rules(repo, mb, head, check, adapter_paths):
    """R0's editing rules on mb..head: the needs-human entry, if any; it fails the R0 check (it blocks nothing)."""
    out = r0_mod.editing(repo, mb, head, [p for p in adapter_paths if not os.path.isabs(p)])
    if out:
        check["status"] = "fail"
        check["note"] += "; a person decides: a limit loosened or a target OS changed"
    return out


def plan(repo, base_ref, head_ref, stack, test_globs):
    """Does the mutants job run (git only, no toolchain): only when a production file changed. How many shards is the
    baseline step's answer (#46)."""
    base, head, mb = merge_base(repo, base_ref, head_ref)
    return {"run": bool(red.prod_changes(Review(repo, mb, head, ADAPTERS[stack](), test_paths(test_globs))))}


def baseline(repo, base_ref, head_ref, stack, test_globs, mutants_cmd=None, mutation_budget=None, shards=4, project_dir=".",
             max_mutants=mutants.DEFAULT_MAX_MUTANTS):
    """The baseline step (#46): the mutants job's plan and its one baseline run. Envelope with the R3 check and the
    run decision: run, count (shards), mutants, timeout (the derived per-mutant seconds). Git only for the file-sharded
    stacks; rust runs cargo-mutants' unmutated baseline once."""
    base, head, mb = merge_base(repo, base_ref, head_ref)
    p = mutants.baseline(Review(repo, mb, head, ADAPTERS[stack](), test_paths(test_globs), project_dir), mutants_cmd,
                         mutation_budget, shards, max_mutants=max_mutants)
    checks = {c: {"status": "skipped", "note": "not run by baseline"} for c in CHECKS}
    checks["R3"] = p["check"]
    env = envelope(base, head, p["entries"], checks)
    env.update({"run": p["run"], "count": p["count"], "mutants": p["mutants"], "timeout": p["timeout"]})
    return env


# which checks each subcommand runs; the rest are reported skipped with the subcommand named
WHICH = {"r2": ("R2",), "red": ("R1", "R4"), "all": ("R0", "R1", "R2", "R4"), "mutants": ("R3",)}


def run(repo, base_ref, head_ref, stack, test_globs, protected_globs=(), which="r2", agent_prefix=None,
        head_branch=None, test_cmd=None, runner=None, mutants_cmd=None, mutation_budget=None, shard=None,
        mutant_timeout=None, mutant_runner=None, project_dir=".", adapter=None,
        max_mutants=mutants.DEFAULT_MAX_MUTANTS, fixtures_dir=None):
    """adapter: an Adapter instance (from an adapter file, --adapter) used in place of the built-in ADAPTERS[stack].
    `all` runs R0's static half first (#20); when it fails, the checks it blocks (r0.BLOCKS) that ran are n/a (their
    entries kept, marked `blocked`)."""
    base, head, mb = merge_base(repo, base_ref, head_ref)
    rv = Review(repo, mb, head, adapter or ADAPTERS[stack](), test_paths(test_globs), project_dir)
    want = WHICH[which]
    checks = {c: {"status": "skipped", "note": f"not run by {which}"} for c in CHECKS}
    raw = []
    if "R0" in want:
        checks["R0"], more = prove(stack, test_globs, adapter, None, fixtures_dir)
        raw += more + _edit_rules(repo, mb, head, checks["R0"], [])
    if "R2" in want:
        raw += r2(rv, list(protected_globs))
        fails = sum(1 for e in raw if e["severity"] == "fail")
        checks["R2"] = {"status": "fail" if fails else "pass", "note": f"{fails} fail, {len(raw) - fails} confirm"}
    if "R1" in want or "R4" in want:
        cmd = test_cmd  # None: each checkout resolves its stack's command (red.r1/r4)
        run_test = runner or red.default_runner()
    if "R1" in want:
        checks["R1"], more = red.r1(rv, head_branch, agent_prefix, cmd, run_test)
        raw += more
    if "R4" in want:
        checks["R4"], more = red.r4(rv, cmd, run_test)
        raw += more
    if which == "all":
        checks["R3"] = {"status": "skipped", "note": "not run by all: R3 runs only in the mutants subcommand (CI job mutants)"}
    r3 = []
    if "R3" in want:
        checks["R3"], r3 = mutants.run(rv, mutants_cmd, mutation_budget, shard, mutant_timeout, mutant_runner,
                                       max_mutants=max_mutants)
    entries = sorted(finalize(raw) + r3, key=lambda e: (e["file"], e["line"] == 0, e["line"], e["id"]))
    if "R0" in want:  # a failed R0 makes the checks it blocks n/a; their entries stay, marked, and still count
        stop = r0_mod.blocked(checks["R0"], checks)
        checks.update(stop)
        entries = r0_mod.mark(entries, stop)
    env = envelope(base, head, entries, checks)
    if "R3" in want:  # which shard this result is, and its cap: merge checks them (#42)
        k, _, n = (shard or "0/1").partition("/")
        env["shard"] = {"k": int(k), "n": int(n), "max_mutants": max_mutants}
    return env


def drift(repo, base_ref, head_ref, now=None):
    """The drift check (#56) as an envelope: check D and at most one `fail` entry (class adapter-fix) naming every
    manifest no plan entry covers; D's messages (planned, retiring and vanished stacks) ride in checks.D.messages.
    No plan on base or head: no D at all, nothing else changes. stack_plan.PlanError: a bad plan (usage error)."""
    base = gitio.resolve(repo, base_ref)
    head = gitio.resolve(repo, head_ref)
    checks = {c: {"status": "skipped", "note": "not run by drift"} for c in CHECKS}
    has_plan, note, uncovered, messages = stack_plan.check_pr(repo, base, head, now)
    entries = finalize([stack_plan.drift_entry(uncovered)]) if uncovered else []
    if has_plan:
        checks["D"] = {"status": "fail" if uncovered else "pass", "note": note, "messages": messages}
    return envelope(base, head, entries, checks)


def drift_error(repo, base_ref, head_ref, error):
    """The drift result of a plan that does not read (stack_plan.PlanError, e.g. no tomllib): D fails with one CI entry
    naming the error. A CI entry is not waivable: the plan is fixed in a PR of its own, which its own plan judges. Written
    beside the usage error (exit 2), so no reader takes a missing result for a repo with no plan."""
    base = gitio.resolve(repo, base_ref)
    head = gitio.resolve(repo, head_ref)
    checks = {c: {"status": "skipped", "note": "not run by drift"} for c in CHECKS}
    checks["D"] = {"status": "fail", "note": f"the stack plan does not read: {error}", "messages": []}
    e = report.entry("CI", stack_plan.PATH, 0, "drift:bad-plan", "adapter-fix", "fail",
                     f"the stack plan does not read: {error}",
                     f"fix the named entry and field in {stack_plan.PATH}, in a PR that edits only the plan or its adapter "
                     f"files (its own plan judges it)", "deleting the plan or the entry to make the check pass")
    return envelope(base, head, finalize([e]), checks)
