"""R3 mutant cap, risk order and cost-based shard count (#26), at the CLI: `mutants --max-mutants N` and `baseline`.

cargo-mutants is a stub (MECH_TEST_STUB): `--list --json` prints STUB_LIST; a run writes mutants.json and outcomes.json
for the mutants its `--re` filters (or `--shard k/n`) select, each caught, plus an unmutated baseline that took
STUB_BUILD_S and STUB_TEST_S seconds. Every call's argv is logged to STUB_LOG, one JSON list per line."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

import _kit

STUB = r'''#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
if args[:2] == ["mutants", "--version"]:
    print("cargo-mutants 27.1.0")
    sys.exit(0)
listing = json.load(open(os.environ["STUB_LIST"]))
if "--list" in args:
    print(json.dumps(listing, indent=2))
    sys.exit(0)
res = [args[i + 1] for i, a in enumerate(args) if a == "--re"]
# cargo-mutants ORs --re with the crate config's examine_re (STUB_CONFIG_RE stands for that config)
conf = [os.environ["STUB_CONFIG_RE"]] if os.environ.get("STUB_CONFIG_RE") else []
picked = [m for m in listing if not res or any(re.search(r, m["name"]) for r in res + conf)]
if "--shard" in args:
    k, n = (int(x) for x in args[args.index("--shard") + 1].split("/"))
    picked = picked[k::n]
mo = os.path.join(args[args.index("--output") + 1], "mutants.out")
os.makedirs(mo)
json.dump(picked, open(os.path.join(mo, "mutants.json"), "w"))
outcomes = []
if "skip" not in args:
    outcomes.append({"scenario": "Baseline", "summary": "Success", "phase_results": [
        {"phase": "Build", "duration": float(os.environ.get("STUB_BUILD_S", "1"))},
        {"phase": "Test", "duration": float(os.environ.get("STUB_TEST_S", "1"))}]})
if "--build-timeout" not in args:
    missed = set(filter(None, os.environ.get("STUB_MISSED", "").split("|")))  # names that survive
    outcomes += [{"scenario": {"Mutant": m}, "summary": "MissedMutant" if m["name"] in missed else "CaughtMutant",
                  "phase_results": [{"phase": "Build", "duration": 1.0}, {"phase": "Test", "duration": 1.0}]}
                 for m in picked]
json.dump({"outcomes": outcomes, "total_mutants": len(picked)}, open(os.path.join(mo, "outcomes.json"), "w"))
sys.exit(0)
'''


def mutant(line, col, genre, desc):
    return {"file": "src/lib.rs", "genre": genre, "name": f"src/lib.rs:{line}:{col}: {desc}", "package": "x",
            "span": {"start": {"line": line, "column": col}, "end": {"line": line, "column": col + 1}}}


# cargo-mutants' order (source order); their risk classes are noted
GT = mutant(6, 7, "BinaryOperator", "replace > with >= in is_big")               # branch condition
GUARD = mutant(10, 9, "MatchArmGuard", "replace match guard with true in pick")  # branch condition
NOT = mutant(14, 5, "UnaryOperator", "delete ! in neg")                          # branch condition
RET = mutant(2, 5, "FnValue", "replace add -> i32 with 0")                       # return value
FALSE = mutant(6, 5, "FnValue", "replace is_big -> bool with false")             # boolean literal
PLUS = mutant(2, 7, "BinaryOperator", "replace + with - in add")                 # arithmetic
ARM = mutant(11, 9, "MatchArm", "delete match arm Some(x) in pick")              # the rest
LISTED = [RET, PLUS, FALSE, GT, GUARD, ARM, NOT]
RISK_ORDER = [GT, GUARD, NOT, RET, FALSE, PLUS, ARM]


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


class RustCap(unittest.TestCase):
    """A rust repo whose head changes src/lib.rs; the stub lists LISTED (or what a test sets)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, "src"))
        with open(os.path.join(self.repo, "Cargo.toml"), "w") as f:
            f.write('[package]\nname = "x"\nversion = "0.1.0"\n')
        self.write("src/lib.rs", "pub fn add(a: i32, b: i32) -> i32 { a + b }\n")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.write("src/lib.rs", "pub fn add(a: i32, b: i32) -> i32 { a + b } // head\n")
        git(self.repo, "commit", "-q", "-am", "head")
        self.stub = os.path.join(self.tmp.name, "stub.py")
        with open(self.stub, "w") as f:
            f.write(STUB)
        os.chmod(self.stub, 0o755)
        self.log = os.path.join(self.tmp.name, "calls.log")
        self.listing(LISTED)

    def write(self, rel, text):
        with open(os.path.join(self.repo, rel), "w") as f:
            f.write(text)

    def listing(self, ms):
        self.list_path = os.path.join(self.tmp.name, "list.json")
        with open(self.list_path, "w") as f:
            json.dump(ms, f)

    def cli(self, *args, rc=(0, 1), **env):
        e = dict(os.environ, MECH_TEST_STUB=self.stub, STUB_LOG=self.log, STUB_LIST=self.list_path, **env)
        open(self.log, "w").close()
        p = subprocess.run([sys.executable, "-I", os.path.join(_kit.SCRIPTS, "mech-review.py"), *args, "--repo", self.repo,
                            "--base", "HEAD~1", "--head", "HEAD", "--stack", "rust", "--test-paths", "tests/**"],
                           env=e, capture_output=True, text=True)
        self.assertIn(p.returncode, rc, p.stderr)
        return json.loads(p.stdout) if p.returncode in (0, 1) else None

    def runs(self):
        """argv of each mutation run (not --version, not --list)."""
        with open(self.log) as f:
            calls = [json.loads(line) for line in f]
        return [a for a in calls if "--output" in a]

    def picked(self):
        """names the one run's --re filters select from the listing."""
        (argv,) = self.runs()
        res = [argv[i + 1] for i, a in enumerate(argv) if a == "--re"]
        return {m["name"] for m in LISTED if any(re.search(r, m["name"]) for r in res)}


def names(ms):
    return {m["name"] for m in ms}


class TestRustCap(RustCap):
    def test_more_sites_than_the_cap_runs_the_riskiest_and_reads_partial(self):
        env = self.cli("mutants", "--max-mutants", "4")
        r3 = env["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 4, 7))
        self.assertIn("partial: R3 (4/7)", env["summary"])
        self.assertEqual(self.picked(), names(RISK_ORDER[:4]))

    def test_the_same_mutants_are_picked_on_every_run_whatever_the_tools_order(self):
        self.cli("mutants", "--max-mutants", "4")
        first = self.picked()
        self.listing(list(reversed(LISTED)))
        self.cli("mutants", "--max-mutants", "4")
        self.assertEqual(self.picked(), first)

    def test_risk_order_branch_then_returns_and_booleans_then_arithmetic_then_the_rest(self):
        for cap in (3, 5, 6):
            self.cli("mutants", "--max-mutants", str(cap))
            self.assertEqual(self.picked(), names(RISK_ORDER[:cap]), cap)

    def test_within_the_cap_every_mutant_runs_and_a_clean_run_is_a_pass(self):
        r3 = self.cli("mutants", "--max-mutants", "7")["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("pass", 7, 7))

    def test_the_default_cap_is_40(self):
        self.listing([mutant(100 + i, 5, "FnValue", f"replace f{i} -> i32 with 0") for i in range(45)])
        r3 = self.cli("mutants")["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 40, 45))

    def test_max_mutants_below_one_is_a_usage_error(self):
        self.cli("mutants", "--max-mutants", "0", rc=(2,))

    def test_a_budget_that_is_not_a_finite_number_is_a_usage_error(self):
        for sub in ("baseline", "mutants"):
            for value in ("nan", "inf"):
                self.cli(sub, "--mutation-budget", value, rc=(2,))


class TestRustShards(RustCap):
    def test_the_capped_mutants_are_dealt_round_robin_in_risk_order(self):
        r3 = self.cli("mutants", "--max-mutants", "4", "--shard", "0/2")["checks"]["R3"]
        self.assertEqual(self.picked(), names([GT, NOT]))
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 2, 5))  # shard 0 holds the 3 past the cap
        r3 = self.cli("mutants", "--max-mutants", "4", "--shard", "1/2")["checks"]["R3"]
        self.assertEqual(self.picked(), names([GUARD, RET]))
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("pass", 2, 2))

    def test_the_merged_shards_read_partial_tested_over_total(self):
        files = []
        for k in (0, 1):
            env = self.cli("mutants", "--max-mutants", "4", "--shard", f"{k}/2")
            path = os.path.join(self.tmp.name, f"s{k}.json")
            with open(path, "w") as f:
                json.dump(env, f)
            files += ["--envelope", f"{k}={path}"]
        env = self.cli("merge", "--shards", "2", *files)
        r3 = env["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 4, 7))
        self.assertIn("partial: R3 (4/7)", env["summary"])


class TestRustCapNotHonoured(RustCap):
    """cargo-mutants unions --re with examine_re from .cargo/mutants.toml: such a run tests mutants past the cap."""

    def test_a_run_that_tests_mutants_outside_the_pick_is_not_a_result(self):
        for shard in ("0/2", "1/2"):
            env = self.cli("mutants", "--max-mutants", "4", "--shard", shard, STUB_CONFIG_RE="src/")
            r3 = env["checks"]["R3"]
            self.assertEqual(r3["status"], "n/a", (shard, r3))
            self.assertIn("examine_re", r3["note"])
            self.assertEqual([e for e in env["entries"] if e["check"] == "R3"], [])

    def test_a_missed_mutant_inside_the_pick_is_still_reported(self):
        # shard 0/2 of the 4 picked holds GT and NOT; ARM is past the cap but runs through the config regex
        env = self.cli("mutants", "--max-mutants", "4", "--shard", "0/2", STUB_CONFIG_RE="src/",
                       STUB_MISSED="|".join((GT["name"], ARM["name"])))
        self.assertEqual(env["checks"]["R3"]["status"], "n/a")
        self.assertEqual([e["problem"] for e in env["entries"] if e["check"] == "R3"], [f"MISSED mutant {GT['name']}"])

    def test_the_note_counts_what_the_status_counts(self):
        r3 = self.cli("mutants", "--max-mutants", "4", "--shard", "0/2")["checks"]["R3"]
        self.assertTrue(r3["note"].startswith("2/5 tested"), r3["note"])


class TestBaselineShardCount(RustCap):
    """shard count = min(4, mutants, ceil(estimated minutes / (budget / 2))), the estimate being the mutants R3 tests
    times the baseline's measured build and test seconds."""

    def count(self, build_s, test_s, *extra):
        env = self.cli("baseline", "--shards", "4", "--mutation-budget", "10", *extra,
                       STUB_BUILD_S=str(build_s), STUB_TEST_S=str(test_s))
        self.assertTrue(env["run"], env["checks"]["R3"])
        return env["count"]

    def test_a_small_pr_gets_one_shard(self):
        self.assertEqual(self.count(0.2, 0.05), 1)  # 7 mutants x 0.25 s

    def test_the_estimate_sets_the_count(self):
        # 7 x 60 s = 7 min, 5 min a shard: 2 shards; 7 x 90 s = 10.5 min: 3
        self.assertEqual((self.count(30, 30), self.count(45, 45)), (2, 3))

    def test_a_large_pr_gets_at_most_4(self):
        self.assertEqual(self.count(300, 300), 4)

    def test_never_more_shards_than_mutants(self):
        self.listing([GT, RET])
        self.assertEqual(self.count(300, 300), 2)

    def test_the_estimate_counts_only_the_mutants_under_the_cap(self):
        # 7 listed, 2 tested: 2 x 120 s = 4 min, one shard
        self.assertEqual(self.count(60, 60, "--max-mutants", "2"), 1)
        self.assertEqual(self.count(60, 60), 3)  # all 7: 14 min


PY_BASE = "def f(a, b):\n    return a\n"
PY_HEAD = 'def f(a, b):\n    if a > b:\n        return a - b\n    return "x"\n'
PY_ORIG = '    if a > b:\n        return a - b\n    return "x"\n'
PY_MUTANTS = {  # mutmut's copy of f per mutant: the body with one edit
    1: PY_ORIG.replace("a > b", "a >= b"),           # branch condition
    2: PY_ORIG.replace("a - b", "a + b"),            # arithmetic
    3: PY_ORIG.replace('"x"', '"XXxXX"'),            # string
    4: PY_ORIG.replace("return a - b", "return None"),  # return value
    5: PY_ORIG.replace("a > b", "a < b"),            # branch condition
}
PY_NAME = "calc.x_f__mutmut_{}".format
PY_RISK_ORDER = [PY_NAME(n) for n in (1, 5, 4, 2, 3)]


class CopyingMutmut:
    """mutmut as R3 drives it, every mutant killed once it runs: the list-only run writes mutants/calc.py (the function
    copies) and its .meta; a run with filters runs the mutants they match; `results` lists each one's status."""

    def __init__(self, list_timeout=False, head=PY_HEAD, orig=PY_ORIG, mutants=PY_MUTANTS):
        self.runs, self.ran, self.list_timeout = [], set(), list_timeout
        self.head, self.orig, self.mutants = head, orig, mutants

    def __call__(self, argv, cwd, timeout):
        verb, args = argv[1], argv[2:]
        if verb == "--version":
            return 0, "mutmut, version 3.8.1"
        if verb == "results":
            return 0, "".join(f"    {PY_NAME(n)}: {'killed' if PY_NAME(n) in self.ran else 'not checked'}\n"
                              for n in sorted(self.mutants))
        if verb != "run":
            return 2, f"unexpected {argv}"
        self.runs.append(args)
        if args == [_kit_mutants().LIST_ONLY]:
            os.makedirs(os.path.join(cwd, "mutants"), exist_ok=True)
            copies = self.head + "\n\ndef x_f__mutmut_orig(a, b):\n" + self.orig + "".join(
                f"\n\ndef x_f__mutmut_{n}(a, b):\n" + body for n, body in sorted(self.mutants.items()))
            with open(os.path.join(cwd, "mutants", "calc.py"), "w") as f:
                f.write(copies)
            with open(os.path.join(cwd, "mutants", "calc.py.meta"), "w") as f:
                json.dump({"exit_code_by_key": dict.fromkeys(PY_NAME(n) for n in self.mutants)}, f)
            if self.list_timeout:
                return "timeout", ""
            return 1, "Filtered for specific mutants, but nothing matches"
        import fnmatch
        self.ran |= {PY_NAME(n) for n in self.mutants if any(fnmatch.fnmatchcase(PY_NAME(n), p) for p in args)}
        return 0, "done"


def _kit_mutants():
    from scripts.mech_review import mutants
    return mutants


class PyRepo(unittest.TestCase):
    """a python repo whose head turns calc.py from PY_BASE into HEAD."""
    HEAD = PY_HEAD

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        for name, text in (("pyproject.toml", "[project]\nname = 'calc'\n"), ("calc.py", PY_BASE)):
            with open(os.path.join(self.repo, name), "w") as f:
                f.write(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        with open(os.path.join(self.repo, "calc.py"), "w") as f:
            f.write(self.HEAD)
        git(self.repo, "commit", "-q", "-am", "head")

    def r3(self, fake, **kw):
        from scripts.mech_review.gitio import Review, merge_base
        from scripts.mech_review.stack import ADAPTERS
        base, head, mb = merge_base(self.repo, "HEAD~1", "HEAD")
        rv = Review(self.repo, mb, head, ADAPTERS["python"](), ["tests/**"], ".")
        return _kit_mutants().run(rv, None, 5, kw.get("shard"), None, fake, max_mutants=kw.get("cap", 40))


ML_ORIG = "    if (a > b and\n            b > 10):\n        return a - b\n    return a\n"
ML_MUTANTS = {1: ML_ORIG.replace("a - b", "a + b"),   # arithmetic, in the body
              2: ML_ORIG.replace("b > 10", "b > 11")}  # a number on the if's continuation line: a branch condition


class TestPythonConditionOrder(PyRepo):
    HEAD = "def f(a, b):\n" + ML_ORIG

    def test_a_continuation_line_of_an_if_ranks_as_a_branch_condition(self):
        # by its text alone mutant 2 is arithmetic like mutant 1, and mutant 1 would come first on the tie
        fake = CopyingMutmut(head=self.HEAD, orig=ML_ORIG, mutants=ML_MUTANTS)
        check, _ = self.r3(fake, cap=1)
        self.assertEqual(fake.ran, {PY_NAME(2)})
        self.assertEqual((check["status"], check["tested"], check["total"]), ("partial", 1, 2))


class TestPythonCap(PyRepo):
    def test_more_mutants_than_the_cap_runs_the_riskiest_and_reads_partial(self):
        fake = CopyingMutmut()
        check, entries = self.r3(fake, cap=3)
        self.assertEqual(sorted(fake.runs[1]), sorted(PY_RISK_ORDER[:3]))
        self.assertEqual(fake.ran, set(PY_RISK_ORDER[:3]))
        self.assertEqual((check["status"], check["tested"], check["total"]), ("partial", 3, 5))
        self.assertIn("2 past the cap (max-mutants 3): untested", check["note"])

    def test_risk_order_branch_then_returns_then_arithmetic_then_strings(self):
        for cap in (1, 2, 3, 4):
            fake = CopyingMutmut()
            self.r3(fake, cap=cap)
            self.assertEqual(fake.ran, set(PY_RISK_ORDER[:cap]), cap)

    def test_within_the_cap_every_mutant_of_the_touched_function_runs(self):
        fake = CopyingMutmut()
        check, _ = self.r3(fake)
        self.assertEqual(fake.runs[1], ["calc.x_f__mutmut_*"])  # as before the cap: the function's filter
        self.assertEqual((check["status"], check["tested"], check["total"]), ("pass", 5, 5))

    def test_shards_deal_the_capped_mutants_round_robin_in_risk_order(self):
        fake0, fake1 = CopyingMutmut(), CopyingMutmut()
        c0, _ = self.r3(fake0, cap=3, shard="0/2")
        c1, _ = self.r3(fake1, cap=3, shard="1/2")
        self.assertEqual((fake0.ran, fake1.ran), ({PY_RISK_ORDER[0], PY_RISK_ORDER[2]}, {PY_RISK_ORDER[1]}))
        self.assertEqual(((c0["status"], c0["tested"], c0["total"]), (c1["status"], c1["tested"], c1["total"])),
                         (("partial", 2, 4), ("pass", 1, 1)))

    def test_a_listing_cut_by_the_budget_leaves_a_shards_total_unknown(self):
        # each shard's listing may be partial, so a dealt count could count a mutant twice or not at all. Unsharded,
        # the listed count stands (test_mutmut_run: 0/2 tested when the budget ends the listing)
        for shard in ("0/2", "1/2"):
            check, entries = self.r3(CopyingMutmut(list_timeout=True), cap=3, shard=shard)
            self.assertEqual((check["status"], check["tested"], check["total"]), ("partial", 0, None), shard)
            self.assertEqual([e for e in entries if e["severity"] == "fail"], [])

    def test_a_shard_with_no_share_of_the_capped_list_is_empty_and_merges_counting_each_mutant_once(self):
        from scripts.mech_review import merge
        fake1 = CopyingMutmut()
        c1, e1 = self.r3(fake1, cap=1, shard="1/2")
        self.assertEqual((c1["status"], c1["tested"], c1["total"], e1), ("pass", 0, 0, []))
        self.assertEqual(c1["note"], "0 mutants in this shard")
        self.assertEqual(fake1.runs, [[_kit_mutants().LIST_ONLY]])  # listed, nothing of its own to run
        c0, e0 = self.r3(CopyingMutmut(), cap=1, shard="0/2")
        self.assertEqual((c0["status"], c0["tested"], c0["total"]), ("partial", 1, 5))
        env = {"base": "b" * 40, "head": "h" * 40, "summary": "", "checks": {}}
        shards = {0: dict(env, entries=e0, checks={"R3": c0}), 1: dict(env, entries=e1, checks={"R3": c1})}
        r3 = merge.combine_shards("b" * 40, "h" * 40, 2, shards, {})["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 1, 5))

    def test_a_production_change_only_outside_project_dir_is_no_mutant(self):
        from scripts.mech_review.gitio import Review, merge_base
        from scripts.mech_review.stack import ADAPTERS
        os.makedirs(os.path.join(self.repo, "pkg"))
        os.makedirs(os.path.join(self.repo, "other"))
        with open(os.path.join(self.repo, "pkg", "pyproject.toml"), "w") as f:
            f.write("[project]\nname = 'pkg'\n")
        with open(os.path.join(self.repo, "other", "x.py"), "w") as f:
            f.write("def x():\n    return 1\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "pkg")
        with open(os.path.join(self.repo, "other", "x.py"), "w") as f:
            f.write("def x():\n    return 2\n")
        git(self.repo, "commit", "-q", "-am", "outside")
        base, head, mb = merge_base(self.repo, "HEAD~1", "HEAD")
        fake = CopyingMutmut()
        check, entries = _kit_mutants().run(Review(self.repo, mb, head, ADAPTERS["python"](), ["tests/**"], "pkg"),
                                            None, 5, None, None, fake)
        self.assertEqual((check, entries, fake.runs), ({"status": "pass", "note": "0 mutants in the diff (no changed "
                                                        "production file under project-dir)", "tested": 0, "total": 0},
                                                       [], []))


class TestPythonRisk(unittest.TestCase):
    """the risk class of a mutmut edit (removed line, added line); expected classes are the spec's order."""

    def test_each_kind_of_edit(self):
        M = _kit_mutants()
        table = [
            (("if a > b:", "if a >= b:"), M.RISK_BRANCH),
            (("x = a and b", "x = a or b"), M.RISK_BRANCH),
            (("match cmd:", "match None:"), M.RISK_BRANCH),
            (("case 1:", "case 2:"), M.RISK_BRANCH),
            (("x = True", "x = False"), M.RISK_RETURN),
            (("return a - b", "return None"), M.RISK_RETURN),
            (("return a", "return b"), M.RISK_RETURN),
            (("c = a - b", "c = a + b"), M.RISK_ARITH),
            (("n = 10", "n = 11"), M.RISK_ARITH),
            (('return "x"', 'return "XXxXX"'), M.RISK_LAST),
            (("return f(a, b)", "return f(a)"), M.RISK_LAST),       # an argument dropped
            (("return f(a, b)", "return f(None, b)"), M.RISK_LAST),  # an argument set to None
            (("log(a, b)", "log(a)"), M.RISK_LAST),
            (("log(a, b)", "log(None, b)"), M.RISK_LAST),
            (("total = n * 2 + 1", "total = None"), M.RISK_REST),  # an assigned value replaced: no operator swap
            (("return a, b", "return a"), M.RISK_RETURN),  # a tuple element, not a call's argument
            (("break", "return"), M.RISK_REST),
        ]
        for (removed, added), want in table:
            self.assertEqual(M.py_risk(removed, added), want, (removed, added))

    def test_a_number_on_a_continuation_line_of_an_if_is_a_branch_condition(self):
        M = _kit_mutants()
        orig = ["def f(n):", "    if (n > 0 and", "            n > 10):", "        return 1", "    return 0"]
        self.assertEqual([M.in_condition(orig, k) for k in range(5)], [False, True, True, False, False])
        self.assertEqual(M.py_risk("n > 10):", "n > 11):", condition=True), M.RISK_BRANCH)
        self.assertEqual(M.py_risk("n > 10):", "n > 11):"), M.RISK_ARITH)

    def test_a_while_assert_and_guard_test_are_conditions_a_body_is_not(self):
        M = _kit_mutants()
        orig = ["def f(xs):", "    while xs:", "        x = xs.pop() + 1", "    assert (", "        x)",
                "    return [y for y in xs", "            if y]"]
        self.assertEqual([M.in_condition(orig, k) for k in range(7)], [False, True, False, True, True, False, True])

    def test_a_method_whose_docstring_has_a_line_at_column_0_still_parses(self):
        orig = ["    def m(self, n):", '        """doc', "at column 0", '        """', "        if (n > 0 and",
                "                n > 10):", "            return 1"]
        self.assertEqual([_kit_mutants().in_condition(orig, k) for k in range(7)],
                         [False, False, False, False, True, True, False])

    def test_a_copy_that_does_not_parse_is_not_a_condition(self):
        self.assertFalse(_kit_mutants().in_condition(["def f(:", "    pass"], 1))


if __name__ == "__main__":
    unittest.main()
