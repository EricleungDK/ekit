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
if "skip" not in args:  # STUB_BASELINE=Failure: the unmutated tests fail (exit STUB_RC, 4 for cargo-mutants)
    outcomes.append({"scenario": "Baseline", "summary": os.environ.get("STUB_BASELINE", "Success"), "phase_results": [
        {"phase": "Build", "duration": float(os.environ.get("STUB_BUILD_S", "1"))},
        {"phase": "Test", "duration": float(os.environ.get("STUB_TEST_S", "1"))}]})
if "--build-timeout" not in args and os.environ.get("STUB_BASELINE", "Success") == "Success":
    missed = set(filter(None, os.environ.get("STUB_MISSED", "").split("|")))  # names that survive
    outcomes += [{"scenario": {"Mutant": m}, "summary": "MissedMutant" if m["name"] in missed else "CaughtMutant",
                  "phase_results": [{"phase": "Build", "duration": 1.0}, {"phase": "Test", "duration": 1.0}]}
                 for m in picked]
if os.environ.get("STUB_HANG"):  # the budget stops the run after its first mutant (outcomes are written as it goes)
    outcomes = [o for o in outcomes if o["scenario"] == "Baseline"] + [o for o in outcomes if o["scenario"] != "Baseline"][:1]
json.dump({"outcomes": outcomes, "total_mutants": len(picked)}, open(os.path.join(mo, "outcomes.json"), "w"))
if os.environ.get("STUB_HANG"):
    import time
    time.sleep(30)
sys.exit(int(os.environ.get("STUB_RC", "0")))
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
            f.write(STUB)  # no exec bit: a .py stub runs with this Python, as on Windows, which runs no shebang
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

    def picked(self, listed=None):
        """names the one run's --re filters select from the listing (LISTED unless given)."""
        (argv,) = self.runs()
        res = [argv[i + 1] for i, a in enumerate(argv) if a == "--re"]
        return {m["name"] for m in listed or LISTED if any(re.search(r, m["name"]) for r in res)}


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

    def test_ties_go_by_line_then_column_a_missing_one_first(self):
        # one risk class (MatchArm); names sort differently from positions, so only the position tie order passes
        def arm(name, start):
            return {"file": "src/lib.rs", "genre": "MatchArm", "name": name, "package": "x",
                    **({"span": {"start": start}} if start is not None else {})}
        want = [arm("zzz: delete match arm in f", None),                   # no position: line 0, column 0
                arm("src/lib.rs:1: delete match arm in g", {"line": 1}),   # no column: 0
                arm("yyy: delete match arm in h", {"line": 6}),
                arm("src/lib.rs:6:1: delete match arm in i", {"line": 6, "column": 1}),
                arm("src/lib.rs:6:9: delete match arm in j", {"line": 6, "column": 9}),
                arm("src/lib.rs:6:10: delete match arm in k", {"line": 6, "column": 10})]
        self.listing(list(reversed(want)))
        for cap in range(1, 6):
            self.cli("mutants", "--max-mutants", str(cap))
            self.assertEqual(self.picked(want), names(want[:cap]), cap)

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


class TestMaxMutantsFlag(unittest.TestCase):
    def test_a_cap_of_one_is_accepted(self):
        from scripts.mech_review import cli
        args = cli.build_parser().parse_args(["mutants", "--base", "a", "--head", "b", "--stack", "python",
                                              "--max-mutants", "1"])
        self.assertEqual(args.max_mutants, 1)


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

    def test_a_missed_mutant_inside_the_pick_is_reported_from_the_repo_root_under_project_dir(self):
        repo = os.path.join(self.tmp.name, "nested")
        os.makedirs(os.path.join(repo, "sub", "src"))
        with open(os.path.join(repo, "sub", "Cargo.toml"), "w") as f:
            f.write('[package]\nname = "x"\nversion = "0.1.0"\n')
        git(repo, "init", "-q")
        for text, msg in (("pub fn a() {}\n", "base"), ("pub fn a() {} // head\n", "head")):
            with open(os.path.join(repo, "sub", "src", "lib.rs"), "w") as f:
                f.write(text)
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", msg)
        self.repo = repo
        # a name that does not start with its file keeps its own text (verdict writes it so)
        weird = {"file": "src/lib.rs", "genre": "MatchArmGuard", "name": "weird: replace match guard with true in w",
                 "package": "x", "span": {"start": {"line": 20, "column": 1}}}
        self.listing(LISTED + [weird])
        env = self.cli("mutants", "--max-mutants", "4", "--project-dir", "sub", STUB_CONFIG_RE="src/",
                       STUB_MISSED="|".join((GT["name"], weird["name"], ARM["name"])))
        self.assertEqual(env["checks"]["R3"]["status"], "n/a")
        self.assertEqual(sorted(e["problem"] for e in env["entries"] if e["check"] == "R3"),
                         [f"MISSED mutant sub/{GT['name']}", f"MISSED mutant {weird['name']}"])

    def test_a_capped_run_the_budget_stops_counts_the_mutants_past_the_cap(self):
        r3 = self.cli("mutants", "--max-mutants", "4", "--mutation-budget", "0.02", STUB_HANG="1")["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 1, 7))
        self.assertTrue(r3["note"].startswith("1/7 tested: budget hit"), r3["note"])

    def test_a_capped_run_with_a_missed_mutant_fails_and_counts_the_mutants_past_the_cap(self):
        env = self.cli("mutants", "--max-mutants", "4", STUB_MISSED=GT["name"])
        r3 = env["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("fail", 4, 7))
        self.assertTrue(r3["note"].startswith("4/7 tested: 1 missed"), r3["note"])
        self.assertIn("3 past the cap (max-mutants 4): untested", r3["note"])

    def test_a_capped_run_whose_baseline_fails_is_that_fail(self):
        env = self.cli("mutants", "--max-mutants", "4", STUB_BASELINE="Failure", STUB_RC="4")
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertEqual([e["problem"] for e in env["entries"]], ["baseline tests fail at head: mutants not run"])

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

    def test_the_note_names_the_mutants_and_how_many_are_under_the_cap(self):
        for extra, want in (((), "baseline ok: 7 mutants, 7 under max-mutants 40, in 1 shard(s)"),
                            (("--max-mutants", "2"), "baseline ok: 7 mutants, 2 under max-mutants 2, in 1 shard(s)")):
            env = self.cli("baseline", "--shards", "4", "--mutation-budget", "10", *extra)
            self.assertTrue(env["checks"]["R3"]["note"].startswith(want), env["checks"]["R3"]["note"])

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

    def __init__(self, list_timeout=False, head=PY_HEAD, orig=PY_ORIG, mutants=PY_MUTANTS, reverse=False,
                 run_timeout=False):
        self.runs, self.ran, self.list_timeout, self.run_timeout = [], set(), list_timeout, run_timeout
        self.head, self.orig, self.mutants, self.reverse = head, orig, mutants, reverse

    def __call__(self, argv, cwd, timeout):
        verb, args = argv[1], argv[2:]
        if verb == "--version":
            return 0, "mutmut, version 3.8.1"
        if verb == "results":  # reverse: mutmut lists them in another order
            return 0, "".join(f"    {PY_NAME(n)}: {'killed' if PY_NAME(n) in self.ran else 'not checked'}\n"
                              for n in sorted(self.mutants, reverse=self.reverse))
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
        return ("timeout", "") if self.run_timeout else (0, "done")  # run_timeout: the budget ends the run, all done


def _kit_mutants():
    from scripts.mech_review import mutants
    return mutants


class PyRepo(unittest.TestCase):
    """a python repo whose head turns calc.py from BASE into HEAD."""
    BASE, HEAD = PY_BASE, PY_HEAD

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        for name, text in (("pyproject.toml", "[project]\nname = 'calc'\n"), ("calc.py", self.BASE)):
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


OFF_ORIG = "    x = a + 1\n    y = b * 2\n    z = x - y\n    return z > 0\n"  # head: only the return line changed
OFF_MUTANTS = {1: OFF_ORIG.replace("a + 1", "a - 1"),    # unchanged lines of the touched function
               2: OFF_ORIG.replace("a + 1", "a + 2"),
               3: OFF_ORIG.replace("b * 2", "b / 2"),
               4: OFF_ORIG.replace("x - y", "x + y"),
               5: OFF_ORIG.replace("z > 0", "z >= 0"),   # the changed line: branch
               6: OFF_ORIG.replace("z > 0", "z > 1"),    # arithmetic (a number)
               7: OFF_ORIG.replace("z > 0", "z < 0")}    # branch
ON_DIFF = [PY_NAME(n) for n in (5, 7, 6)]  # risk order


class TestPythonCapOnChangedLines(PyRepo):
    """#26 follow-on: the cap's slots go only to mutants that can become findings, those on a changed line."""
    BASE = "def f(a, b):\n" + OFF_ORIG.replace("return z > 0", "return z")
    HEAD = "def f(a, b):\n" + OFF_ORIG

    def fake(self, **kw):
        return CopyingMutmut(head=self.HEAD, orig=OFF_ORIG, mutants=OFF_MUTANTS, **kw)

    def test_only_mutants_on_changed_lines_are_picked_and_counted(self):
        for reverse in (False, True):
            fake = self.fake(reverse=reverse)
            check, entries = self.r3(fake, cap=2)
            self.assertEqual(fake.ran, set(ON_DIFF[:2]), reverse)
            self.assertEqual((check["status"], check["tested"], check["total"]), ("partial", 2, 3), reverse)
            self.assertIn("4 on unchanged lines of touched functions: not run", check["note"])
            self.assertEqual([e for e in entries if e["severity"] == "fail"], [])

    def test_within_the_cap_only_the_changed_lines_mutants_run(self):
        fake = self.fake()
        check, _ = self.r3(fake)
        self.assertEqual(fake.ran, set(ON_DIFF))
        self.assertEqual((check["status"], check["tested"], check["total"]), ("pass", 3, 3))

    def test_a_budget_hit_still_counts_the_mutants_on_unchanged_lines(self):
        check, _ = self.r3(self.fake(run_timeout=True), cap=2)
        self.assertEqual(check["status"], "partial")
        self.assertIn("4 on unchanged lines of touched functions: not run", check["note"])

    def test_an_empty_shard_still_counts_the_mutants_on_unchanged_lines(self):
        check, entries = self.r3(self.fake(), cap=1, shard="1/2")
        self.assertEqual((check["status"], check["tested"], check["total"], entries), ("pass", 0, 0, []))
        self.assertEqual(check["note"], "0 mutants in this shard; 4 on unchanged lines of touched functions: not run")

    def test_shards_run_each_picked_mutant_once(self):
        f0, f1 = self.fake(), self.fake()
        c0, _ = self.r3(f0, cap=2, shard="0/2")
        c1, _ = self.r3(f1, cap=2, shard="1/2")
        self.assertEqual((f0.ran, f1.ran), ({ON_DIFF[0]}, {ON_DIFF[1]}))
        self.assertEqual(((c0["tested"], c0["total"]), (c1["tested"], c1["total"])), ((1, 2), (1, 1)))


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


PY_STUB = r"""#!/usr/bin/env python3
import fnmatch, json, os, sys
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
spec = json.load(open(os.environ["STUB_SPEC"]))
if args[:1] == ["-B"]:  # the whole suite (mutants.SUITE with this stub for python3)
    if os.environ.get("STUB_PYTEST_HANG"):
        import time
        time.sleep(30)
    # pytest's JUnit XML, as pytest 9.2.0 writes it: the testsuite's time is the session's
    xml = [a.split("=", 1)[1] for a in args if a.startswith("--junit-xml=")]
    if xml and os.environ.get("STUB_JUNIT") != "none":
        with open(xml[-1], "w") as f:
            f.write(os.environ.get("STUB_JUNIT") or
                    '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest" '
                    'errors="0" failures="0" skipped="0" tests="3" time="%s" timestamp="2026-11-22T08:33:07+00:00" '
                    'hostname="vm"><testcase classname="test_a" name="test_a" time="0.000" /></testsuite>'
                    '</testsuites>' % os.environ.get("STUB_TEST_S", "0.05"))
    print(os.environ.get("STUB_PYTEST", "...                                       [100%]"))
    sys.exit(int(os.environ.get("STUB_PYTEST_RC", "0")))
if args == ["--version"]:
    # mutmut 3.8.1 reads its config before any command: with no [tool.mutmut] (and no src/) even --version fails
    if "[tool.mutmut]" not in (open("pyproject.toml").read() if os.path.exists("pyproject.toml") else ""):
        print("FileNotFoundError: Could not figure out where the code to mutate is.")
        sys.exit(1)
    print(os.environ.get("STUB_VERSION", "mutmut, version 3.8.1"))
    sys.exit(0)
ran_path = os.path.join("mutants", "ran.json")
ran = json.load(open(ran_path)) if os.path.exists(ran_path) else []
if args[:1] == ["results"] and os.environ.get("STUB_RESULTS_RC"):
    print("Traceback (most recent call last):")
    sys.exit(int(os.environ["STUB_RESULTS_RC"]))
if args[:1] == ["results"]:
    print("".join(f"    {n}: {'killed' if n in ran else 'not checked'}\n" for n in spec["names"]), end="")
    sys.exit(0)
if args[:1] == ["run"] and args[1:] == [spec["list_only"]] and os.environ.get("STUB_LISTING", "early") != "early":
    if os.environ["STUB_LISTING"] == "hang":
        import time
        time.sleep(30)
    print(os.environ["STUB_LISTING"])  # e.g. mutmut's "Stopping early, ..."
    sys.exit(1)
if args[:1] == ["run"] and args[1:] == [spec["list_only"]]:
    # mutmut runs the tests in its copy under mutants/: a top-level entry they need must be in also_copy
    import re
    listed = re.search(r"^also_copy = \[(.*)\]$", open("pyproject.toml").read(), re.M)
    if any(f'"{n}"' not in (listed.group(1) if listed else "") for n in spec.get("needs", [])):
        print("failed to collect stats. runner returned 1")
        sys.exit(1)
    os.makedirs("mutants", exist_ok=True)
    with open(os.path.join("mutants", "calc.py"), "w") as f:
        f.write(spec["copies"])
    with open(os.path.join("mutants", "calc.py.meta"), "w") as f:
        json.dump({"exit_code_by_key": dict.fromkeys(spec["names"])}, f)
    if os.environ.get("STUB_LISTING") == "early":  # no test reaches a mutated function: mutants written, none run
        print("Stopping early, because tests recorded trampoline hits but none match any mutant key.")
    else:
        print("Filtered for specific mutants, but nothing matches")
    sys.exit(1)
if args[:1] == ["run"]:
    ran += [n for n in spec["names"] if any(fnmatch.fnmatchcase(n, p) for p in args[1:])]
    json.dump(ran, open(ran_path, "w"))
    print("done")
    sys.exit(0)
print(f"unexpected {args}")
sys.exit(2)
"""


class PyCli(PyRepo):
    """R3 for python at the CLI (in-process, `_kit.run_cli`), mutmut and pytest a stub (MECH_TEST_STUB): pytest prints
    STUB_PYTEST and writes its JUnit XML with a session time of STUB_TEST_S seconds; mutmut's list-only run writes the
    function copies of `mutants` (CopyingMutmut's)."""

    def setUp(self):
        super().setUp()
        side = tempfile.TemporaryDirectory()  # outside the repo (the repo is self.tmp)
        self.addCleanup(side.cleanup)
        self.stub = os.path.join(side.name, "stub.py")
        with open(self.stub, "w") as f:
            f.write(PY_STUB)
        self.log = os.path.join(side.name, "calls.log")
        self.spec_path = os.path.join(side.name, "spec.json")
        self.spec(PY_MUTANTS)

    def spec(self, mutants, head=PY_HEAD, orig=PY_ORIG, needs=()):
        copies = head + "\n\ndef x_f__mutmut_orig(a, b):\n" + orig + "".join(
            f"\n\ndef x_f__mutmut_{n}(a, b):\n" + body for n, body in sorted(mutants.items()))
        with open(self.spec_path, "w") as f:
            json.dump({"names": [PY_NAME(n) for n in sorted(mutants)], "copies": copies,
                       "list_only": _kit_mutants().LIST_ONLY, "needs": list(needs)}, f)

    def cli(self, *args, **env):
        from unittest import mock
        e = {"MECH_TEST_STUB": self.stub, "STUB_LOG": self.log, "STUB_SPEC": self.spec_path, **env}
        with mock.patch.dict(os.environ, e):
            r = _kit.run_cli([*args, "--repo", self.repo, "--base", "HEAD~1", "--head", "HEAD", "--stack", "python",
                              "--test-paths", "tests/**"])
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return json.loads(r.stdout)


class TestPythonBaselineShardCount(PyCli):
    """#64, as #26's rust shard count: min(4, mutants, ceil(estimated minutes / (budget / 2))), the estimate being the
    mutants R3 tests (those on changed lines, under the cap) times the suite's test time, measured by the baseline."""

    def count(self, test_s, *extra):
        env = self.cli("baseline", "--shards", "4", "--mutation-budget", "10", *extra,
                       STUB_TEST_S=f"{test_s:.3f}")
        self.assertTrue(env["run"], env["checks"]["R3"])
        return env["count"]

    def test_a_small_pr_gets_one_shard(self):
        self.assertEqual(self.count(0.05), 1)  # 5 mutants x 0.05 s

    def test_the_estimate_sets_the_count(self):
        # 5 x 90 s = 7.5 min, 5 min a shard: 2 shards; 5 x 150 s = 12.5 min: 3
        self.assertEqual((self.count(90), self.count(150)), (2, 3))

    def test_a_large_pr_gets_at_most_4(self):
        self.assertEqual(self.count(600), 4)

    def test_a_listing_that_stops_early_still_counts_as_the_check_reads_it(self):
        # mutmut stops early when no test reaches a mutated function; its mutants are written and the check runs on
        env = self.cli("baseline", "--shards", "4", "--mutation-budget", "10", STUB_LISTING="early", STUB_TEST_S="90")
        self.assertEqual((env["run"], env["count"], env["mutants"]), (True, 2, 5))

    def test_the_time_is_the_junit_reports_whatever_the_terminal_shows(self):
        # addopts `-q` (pytest -qq: no summary line), colour, a summary without `passed`, an old wording, a huge line
        for shown in (".                                    [100%]",
                      "\x1b[32m.\x1b[0m\n\x1b[32m\x1b[1m3 passed\x1b[0m\x1b[32m in 0.05s\x1b[0m",
                      "2 xpassed in 0.10s", "5 skipped in 0.1s", "3 passed in 0.12 seconds",
                      "1 passed " * 10000):  # 90 KB (an env var holds 128 KB)
            env = self.cli("baseline", "--shards", "4", "--mutation-budget", "10", STUB_PYTEST=shown,
                           STUB_TEST_S="90.0")
            self.assertEqual((env["count"], env["checks"]["R3"]["timing"]["baseline_test_s"]), (2, 90.0), shown[:40])

    def test_a_deleted_production_file_is_no_file_to_list(self):
        git(self.repo, "reset", "-q", "--hard", "HEAD~1")
        with open(os.path.join(self.repo, "old.py"), "w") as f:
            f.write("def old():\n    return 1\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--amend", "--no-edit")
        with open(os.path.join(self.repo, "calc.py"), "w") as f:
            f.write(PY_HEAD)
        git(self.repo, "rm", "-q", "old.py")
        git(self.repo, "commit", "-q", "-am", "head")
        self.assertEqual(self.count(90), 2)

    def test_the_listing_copies_what_the_tests_need(self):
        os.makedirs(os.path.join(self.repo, "data"))
        with open(os.path.join(self.repo, "data", "x.txt"), "w") as f:
            f.write("x\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--amend", "--no-edit")
        self.spec(PY_MUTANTS, needs=["data"])  # mutmut's copy holds data/ only through also_copy
        self.assertEqual(self.count(90), 2)

    def test_never_more_shards_than_mutants(self):
        self.spec({n: PY_MUTANTS[n] for n in (1, 2)})
        self.assertEqual(self.count(600), 2)

    def test_the_estimate_counts_only_the_mutants_under_the_cap(self):
        # 5 listed, 2 tested: 2 x 120 s = 4 min, one shard; all 5: 10 min, 2
        self.assertEqual((self.count(120, "--max-mutants", "2"), self.count(120)), (1, 2))

    def test_only_the_mutants_on_changed_lines_are_counted(self):
        # OFF_MUTANTS: 7 in the touched function, 3 on its changed line
        with open(os.path.join(self.repo, "calc.py"), "w") as f:
            f.write("def f(a, b):\n" + OFF_ORIG.replace("return z > 0", "return z"))
        git(self.repo, "commit", "-q", "-am", "base 2")
        with open(os.path.join(self.repo, "calc.py"), "w") as f:
            f.write("def f(a, b):\n" + OFF_ORIG)
        git(self.repo, "commit", "-q", "-am", "head 2")
        self.spec(OFF_MUTANTS, head="def f(a, b):\n" + OFF_ORIG, orig=OFF_ORIG)
        env = self.cli("baseline", "--shards", "4", "--mutation-budget", "10", STUB_TEST_S="600.0")
        self.assertEqual((env["run"], env["count"], env["mutants"]), (True, 3, 3))

    def test_no_mutant_on_a_changed_line_runs_no_shard(self):
        # as rust's baseline for no mutant: never more shards than mutants, and 0 is none
        with open(os.path.join(self.repo, "calc.py"), "w") as f:
            f.write("def f(a, b):\n" + OFF_ORIG.replace("return z > 0", "return z"))
        git(self.repo, "commit", "-q", "-am", "base 2")
        with open(os.path.join(self.repo, "calc.py"), "w") as f:
            f.write("def f(a, b):\n" + OFF_ORIG)
        git(self.repo, "commit", "-q", "-am", "head 2")
        self.spec({n: OFF_MUTANTS[n] for n in (1, 2, 3, 4)}, head="def f(a, b):\n" + OFF_ORIG, orig=OFF_ORIG)
        env = self.cli("baseline", "--shards", "4", "--mutation-budget", "10", STUB_TEST_S="600.0")
        r3 = env["checks"]["R3"]
        self.assertEqual((env["run"], env["count"], env["mutants"], r3["status"], r3["tested"], r3["total"]),
                         (False, 0, 0, "pass", 0, 0))
        self.assertEqual(r3["note"], "0 mutants on changed lines")
        side = tempfile.TemporaryDirectory()
        self.addCleanup(side.cleanup)
        path = os.path.join(side.name, "baseline.json")
        with open(path, "w") as f:
            json.dump(env, f)
        merged = self.cli("merge", "--shards", "0", "--baseline", path)
        self.assertEqual(merged["checks"]["R3"]["status"], "pass")

    def test_the_measured_time_is_in_the_baseline_json(self):
        env = self.cli("baseline", "--shards", "4", "--mutation-budget", "10",
                       STUB_TEST_S="90.0")
        r3 = env["checks"]["R3"]
        self.assertEqual((env["count"], env["mutants"], env["timeout"]), (2, 5, None))
        self.assertEqual(r3["timing"]["baseline_test_s"], 90.0)
        self.assertIsInstance(r3["timing"]["wall_s"], float)
        self.assertTrue(r3["note"].startswith("baseline ok: 5 mutants on changed lines, 5 under max-mutants 40, in 2 "
                                              "shard(s) (estimated 7.5 min"), r3["note"])


class TestPythonShardsFromTheBaseline(PyCli):
    """#64: the baseline's count is the shards the mutants job runs; each lists every changed file and runs its
    round-robin share of the capped, risk-ordered list; merge takes them with #42's checks."""

    def ran(self):
        with open(self.log) as f:
            calls = [json.loads(line) for line in f]
        return [a[1:] for a in calls if a[:1] == ["run"] and a[1:] != [_kit_mutants().LIST_ONLY]]

    def test_the_counted_shards_run_the_capped_mutants_once_each_and_merge(self):
        base = self.cli("baseline", "--shards", "4", "--mutation-budget", "10", "--max-mutants", "3",
                        STUB_TEST_S="240.0")  # 3 x 240 s = 12 min: 3 shards
        self.assertEqual(base["count"], 3)
        side = tempfile.TemporaryDirectory()
        self.addCleanup(side.cleanup)
        with open(os.path.join(side.name, "baseline.json"), "w") as f:
            json.dump(base, f)
        files, ran = [], []
        for k in range(3):
            open(self.log, "w").close()
            env = self.cli("mutants", "--shard", f"{k}/3", "--max-mutants", "3", "--mutation-budget", "10")
            ran.append(self.ran())
            path = os.path.join(side.name, f"s{k}.json")
            with open(path, "w") as f:
                json.dump(env, f)
            files += ["--envelope", f"{k}={path}"]
        self.assertEqual(ran, [[[PY_RISK_ORDER[k]]] for k in range(3)])
        merged = self.cli("merge", "--shards", "3", "--baseline", os.path.join(side.name, "baseline.json"), *files)
        r3 = merged["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 3, 5))
        self.assertEqual(r3["timing"]["baseline_test_s"], 240.0)
        self.assertEqual([e["check"] for e in merged["entries"] if e["check"] == "CI"], [])


class TestPythonBaselineMeasuredNothing(PyCli):
    """#64: a baseline that measured no test time keeps the file rule (one shard per changed production file, at most
    4) and its note says so."""

    def unmeasured(self, **env):
        out = self.cli("baseline", "--shards", "4", "--mutation-budget", "10", **env)
        r3 = out["checks"]["R3"]
        self.assertEqual((out["run"], out["count"], out["mutants"], r3["status"]), (True, 1, None, "skipped"))
        self.assertTrue(r3["note"].startswith("1 changed production file(s) in 1 shard(s); test time not measured ("),
                        r3["note"])
        self.assertTrue(r3["note"].endswith("): one shard per changed file"), r3["note"])
        self.assertNotIn("timing", r3)
        return r3["note"]

    SUITE = "`python3 -B -m pytest -x -q -p no:cacheprovider --ignore=mutants`"  # the whole suite, as the docs name it

    def test_a_red_suite(self):
        self.assertEqual(self.unmeasured(STUB_PYTEST="1 failed, 2 passed in 3.00s", STUB_PYTEST_RC="1"),
                         f"1 changed production file(s) in 1 shard(s); test time not measured ({self.SUITE} ended "
                         "with 1): one shard per changed file")

    def test_a_suite_that_writes_no_junit_report(self):
        # a repo whose addopts holds `-p no:junitxml`: green, but no time to read
        for junit in ("none", "<testsuites><testsuite name='pytest'/></testsuites>", "<testsuites", "<x time='-1'/>"):
            self.assertEqual(self.unmeasured(STUB_JUNIT=junit),
                             f"1 changed production file(s) in 1 shard(s); test time not measured ({self.SUITE} "
                             "wrote no session time in its JUnit XML): one shard per changed file", junit)

    def test_a_suite_the_budget_ends(self):
        out = self.cli("baseline", "--shards", "4", "--mutation-budget", "0.02", STUB_PYTEST_HANG="1")
        self.assertEqual(out["checks"]["R3"]["note"],
                         f"1 changed production file(s) in 1 shard(s); test time not measured ({self.SUITE} did not "
                         "finish within mutation-budget (0.02 min)): one shard per changed file")

    def test_no_mutmut(self):
        self.assertIn("mutmut not runnable: `mutmut`", self.unmeasured(STUB_VERSION="bash: mutmut: command not found"))

    def test_a_listing_that_stops(self):
        note = self.unmeasured(STUB_LISTING="failed to collect stats. runner returned 1")
        self.assertEqual(note, "1 changed production file(s) in 1 shard(s); test time not measured (mutmut's listing "
                               "ended with 1: failed to collect stats. runner returned 1): one shard per changed file")

    def test_a_listing_the_budget_ends(self):
        out = self.cli("baseline", "--shards", "4", "--mutation-budget", "0.02", STUB_LISTING="hang")
        self.assertEqual(out["checks"]["R3"]["note"],
                         "1 changed production file(s) in 1 shard(s); test time not measured (mutmut's listing did "
                         "not finish within mutation-budget (0.02 min)): one shard per changed file")
        self.assertEqual((out["run"], out["count"]), (True, 1))

    def test_results_that_cannot_be_read(self):
        self.assertIn("(mutmut results ended with 1)", self.unmeasured(STUB_RESULTS_RC="1"))

    def test_a_repo_that_configures_mutmut_itself(self):
        with open(os.path.join(self.repo, "pyproject.toml"), "a") as f:
            f.write("\n[tool.mutmut]\npaths_to_mutate = ['calc.py']\n")
        with open(os.path.join(self.repo, "calc.py"), "a") as f:
            f.write("\n\ndef g():\n    return 1\n")
        git(self.repo, "commit", "-q", "-am", "own config")
        out = self.cli("baseline", "--shards", "4")
        self.assertIn("(the repo already configures mutmut ([tool.mutmut]))", out["checks"]["R3"]["note"])

    def test_a_project_dir_without_a_manifest(self):
        git(self.repo, "rm", "-q", "pyproject.toml")
        with open(os.path.join(self.repo, "calc.py"), "a") as f:
            f.write("\n\ndef g():\n    return 1\n")
        git(self.repo, "commit", "-q", "-am", "no manifest")
        self.assertIn("(no pyproject.toml", self.unmeasured())

    def test_no_production_file_under_project_dir_runs_nothing(self):
        out = self.cli("baseline", "--shards", "4", "--project-dir", "app")
        self.assertEqual((out["run"], out["count"], out["checks"]["R3"]["status"]), (False, 0, "pass"))
        self.assertFalse(os.path.exists(self.log))

    def test_five_files_keep_at_most_4_shards(self):
        for k in range(5):
            with open(os.path.join(self.repo, f"m{k}.py"), "w") as f:
                f.write(f"def g{k}():\n    return {k}\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "more files")
        out = self.cli("baseline", "--shards", "4", STUB_JUNIT="none")  # the head commit adds the 5
        self.assertEqual(out["count"], 4)


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
