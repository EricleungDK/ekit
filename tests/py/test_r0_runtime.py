"""R0 runtime half (#21): `red --r0 DIR` (census, assert density, runner controls) and `mutants --r0 DIR` (the R3
control) on fixture git repos, through cli.main in this process. The stack is `minirun` (tests/fixtures/adapters/
minirun.toml), a made-up language whose runner `mini` and mutation tool `mut` are STUB below, on PATH and as
MECH_TEST_STUB: it really evaluates the mini tests (assertEquals, assertTrue over `fn` lines), so a weak adapter is
measured against a runner that behaves, not against canned output."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import atexit

import _kit
from scripts.mech_review import r0_runtime

FX = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters")
MINIRUN_FX = os.path.join(FX, "minirun.r0")
# R0's runtime half runs only on the stack's target OS: the tests' stacks target the OS they run on (the engine's own
# host_os), so the half runs on every CI runner; TargetOS keeps the case of another OS
HOST = r0_runtime.host_os()


def host_plan(stack):
    """a stack plan whose one entry gives the built-in `stack` this machine's OS (a built-in targets linux)."""
    return (f'[[stack]]\nname = "{stack}"\nfolder = "."\nadapter = "{stack}"\nstatus = "current"\n'
            f'target-os = "{HOST}"\n')


def _hosted(src):
    with open(src) as f:
        text = f.read().replace('extensions = [".mini"]\n', f'extensions = [".mini"]\ntarget-os = "{HOST}"\n', 1)
    d = tempfile.mkdtemp(prefix="ekit-minirun-")
    atexit.register(shutil.rmtree, d, True)
    with open(os.path.join(d, "minirun.toml"), "w") as f:
        f.write(text)
    return os.path.join(d, "minirun.toml")


MINIRUN = _hosted(os.path.join(FX, "minirun.toml"))  # minirun.toml with target-os this machine's OS

# the runner and the tool. `list`: `<path> :: <name>` of each test it would run (STUB_STYLES: the calls that are
# tests, `xtest` skipped and not listed); `test <path> --name <n>`: runs one; `run --mutate F:a-b --report R`: one `+`
# -> `-` mutant per `+` on those lines, killed when a test fails; `--version`: the `version` file beside it, else
# `mini 1.0.0`. Logs each call to STUB_LOG.
STUB = r'''
import json, os, re, sys
args = sys.argv[1:]
if os.environ.get("STUB_LOG"):
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(" ".join(args) + "\n")
if args[:1] == ["--version"]:  # the probe runs with a minimal environment: the version sits in a file beside the stub
    at = os.path.join(os.path.dirname(os.path.realpath(__file__)), "version")
    print(open(at).read().strip() if os.path.exists(at) else "mini 1.0.0")
    sys.exit(0)
STYLES = os.environ.get("STUB_STYLES", "test it xtest").split()
TEST = re.compile(r'^(' + "|".join(STYLES) + r')\("([^"]+)", \{\n(.*?)\n\}\)', re.M | re.S)

def files(ext=".mini"):
    out = []
    for top, dirs, names in os.walk("."):
        dirs[:] = sorted(d for d in dirs if d not in ("out", "node_modules", ".git"))
        out += [os.path.relpath(os.path.join(top, n)).replace(os.sep, "/") for n in sorted(names) if n.endswith(ext)]
    return out

def text(p, swap=None):
    t = open(p).read()
    return swap.get(p, t) if swap else t

def fns(swap=None):
    env = {}
    for p in files():
        if p.startswith("src/"):
            for m in re.finditer(r"^fn (\w+)\(([^)]*)\) \{ (.*) \}$", text(p, swap), re.M):
                env[m.group(1)] = eval("lambda " + m.group(2) + ": " + m.group(3), env)
    return env

def tests(swap=None):
    return [(p, m.group(1), m.group(2), m.group(3)) for p in files() if p.startswith("tests/")
            for m in TEST.finditer(text(p, swap))]

def args_of(call):
    inner, depth, parts, cur = call[call.index("(") + 1:call.rindex(")")], 0, [], ""
    for ch in inner:
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""; continue
        depth += ch in "(" ; depth -= ch in ")"
        cur += ch
    return parts + [cur]

def passes(body, env):
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("assertEquals("):
            a, b = args_of(line)
            if eval(a, dict(env)) != eval(b, dict(env)):
                return False
        elif line.startswith("assertTrue("):
            if not eval(args_of(line)[0], dict(env)):
                return False
        elif line.startswith("check("):
            pass
    return True

for p in files():
    t = open(p).read()
    if t.count("(") != t.count(")"):
        print("build error: unbalanced ( in " + p)
        sys.exit(2)
if args[:1] == ["list"]:
    for p, style, name, body in tests():
        if style != "xtest":
            print(p + " :: " + name)
    sys.exit(0)
if args[:1] == ["test"]:
    path, name = args[1], args[args.index("--name") + 1]
    if name == "poison" and os.environ.get("POISON_DIR"):  # a PR test that forges R0's cache while R4 runs it
        os.makedirs(os.environ["POISON_DIR"], exist_ok=True)
        with open(os.path.join(os.environ["POISON_DIR"], "run-" + os.environ["POISON_FP"] + ".pass"), "w") as f:
            json.dump({"fingerprint": os.environ["POISON_FP"]}, f)
        with open(os.path.join(os.environ["POISON_DIR"], "planted"), "w") as f:
            f.write("x")
    hit = [t for t in tests() if t[0] == path and t[2] == name]
    if not hit:
        print("0 passed, 0 failed")
        sys.exit(0)
    if hit[0][1] == "xtest":
        print("0 passed, 0 failed, 1 skipped")
        sys.exit(0)
    ok = passes(hit[0][3], fns())
    print("1 passed" if ok else "0 passed, 1 failed")
    sys.exit(0 if ok else 1)
if args[:1] == ["run"]:
    spec, report = args[args.index("--mutate") + 1], args[args.index("--report") + 1]
    out = {"schemaVersion": "2", "files": {}}
    n = 0
    for rng in spec.split(","):
        path, _, lines = rng.rpartition(":")
        first, _, last = lines.partition("-")
        src = open(path).read()
        rows = src.splitlines(keepends=True)
        muts = []
        for i in range(int(first), int(last or first) + 1):
            for m in re.finditer(r"\+", rows[i - 1]):
                n += 1
                mutated = "".join(rows[:i - 1]) + rows[i - 1][:m.start()] + "-" + rows[i - 1][m.end():] + "".join(rows[i:])
                env = fns({path: mutated})
                killed = any(st != "xtest" and not passes(body, env) for _, st, _, body in tests())
                muts.append({"id": str(n), "mutatorName": "ArithmeticOperator", "replacement": "-",
                             "location": {"start": {"line": i, "column": m.start() + 1},
                                          "end": {"line": i, "column": m.end() + 1}},
                             "status": "Killed" if killed else "Survived", "coveredBy": ["t"], "testsCompleted": 1})
        out["files"][path] = {"language": "mini", "source": src, "mutants": muts}
    os.makedirs(os.path.dirname(report) or ".", exist_ok=True)
    with open(report, "w") as f:
        json.dump(out, f)
    sys.exit(0)
print("stub: unknown " + " ".join(args))
sys.exit(3)
'''

SRC = "fn add(a, b) { a + b }\n"
TESTS = 'test("adds", {\n  assertEquals(3, add(1, 2))\n})\n\ntest("sums", {\n  assertTrue(add(1, 1) == 2)\n})\n'


def adapter_text(edit=None):
    with open(MINIRUN) as f:
        text = f.read()
    return edit(text) if edit else text


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(self.tmp, "repo")
        self.cache = os.path.join(self.tmp, "r0-cache")
        self.log = os.path.join(self.tmp, "calls.log")
        stub = os.path.join(self.tmp, "stub.py")
        with open(stub, "w") as f:
            f.write("#!/usr/bin/env python3\n" + STUB)
        os.chmod(stub, 0o755)
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        for prog in ("mini", "mut"):
            os.symlink(stub, os.path.join(bin_dir, prog))
        env = mock.patch.dict(os.environ, {"MECH_TEST_STUB": stub, "STUB_LOG": self.log,
                                           "PATH": bin_dir + os.pathsep + os.environ["PATH"]})
        env.start()
        self.addCleanup(env.stop)
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        self.base = self.commit({"mini.json": "{}\n", "src/calc.mini": SRC, "tests/calc.mini": TESTS})

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                               "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, files):
        for p, text in files.items():
            full = os.path.join(self.repo, p)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(text)
        self.git("add", "-A")
        self.git("commit", "-qm", "c", "--allow-empty")
        return self.git("rev-parse", "HEAD")

    def adapter(self, text=None, name="minirun.toml"):
        """the adapter file: minirun's own (beside its fixtures), or text written to the temp dir."""
        if text is None:
            return MINIRUN
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def red(self, adapter=None, head=None, *extra):
        r = _kit.run_cli(["red", "--repo", self.repo, "--base", self.base, "--head", head or self.base,
                          "--stack", "minirun", "--adapter", adapter or MINIRUN, "--fixtures", MINIRUN_FX,
                          "--test-paths", "tests/**", "--r0", self.cache, *extra])
        self.assertIn(r.returncode, (0, 1), r.stderr + r.stdout)
        return r, json.loads(r.stdout)

    def mutants(self, adapter=None, head=None, *extra):
        r = _kit.run_cli(["mutants", "--repo", self.repo, "--base", self.base, "--head", head or self.base,
                          "--stack", "minirun", "--adapter", adapter or MINIRUN, "--fixtures", MINIRUN_FX,
                          "--test-paths", "tests/**", "--r0", self.cache, *extra])
        self.assertIn(r.returncode, (0, 1), r.stderr + r.stdout)
        return r, json.loads(r.stdout)

    def cases(self, check):
        return {c["case"]: c["status"] for c in check["cases"]}


class RunPart(Case):
    """the run part on a sound adapter: every case passes, with numbers and the probes in the report."""

    def test_a_sound_adapter_passes_with_numbers(self):
        r, env = self.red()
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual((c["half"], c["part"], c["ran"]), ("runtime", "run", True))
        self.assertEqual(self.cases(c), {"census-repo": "pass", "census-fixtures": "pass", "control-pass": "pass",
                                         "control-fail": "pass", "control-skipped": "pass", "control-build": "pass",
                                         "control-no-such-test": "pass", "skip-idiom": "pass"})
        self.assertEqual(c["census"], {"repo": {"found": 2, "listed": 2, "misses": []},
                                       "fixtures": {"found": 3, "listed": 3, "misses": []}})
        self.assertEqual(c["density"], {"tests": 2, "no_assert": [], "accepted": [], "limit": 10, "percent": 0.0})
        self.assertRegex(c["note"], r"^runtime half \(run\): fingerprint [0-9a-f]{12} \(ran\); census: 2/2 listed tests "
                                    r"found; fixtures census: 3/3; assert density: 0 of 2 tests with no recognised "
                                    r"assert, 0% \(limit 10%\); controls: 5 of 5 read right$")
        self.assertEqual(c["probes"], ["mini --version: mini 1.0.0"])
        self.assertEqual(env["entries"], [])
        self.assertEqual(r.returncode, 0)


class Weaknesses(Case):
    """C1: a fixture adapter for each weakness makes R0 fail and names the cause, in one adapter-fix entry."""

    def failed(self, env, case):
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual([k for k, v in self.cases(c).items() if v == "fail"], [case] if isinstance(case, str) else case)
        es = [e for e in env["entries"] if e["check"] == "R0"]
        self.assertEqual([(e["class"], e["severity"]) for e in es], [("adapter-fix", "fail")], es)
        self.assertTrue(es[0]["problem"].startswith("R0 runtime half (run) failed for the `minirun` adapter: "),
                        es[0]["problem"])
        return es[0]["problem"]

    def test_an_adapter_that_misses_a_test(self):
        text = adapter_text(lambda t: t.replace('cases = ["test", "it", "xtest"]', 'cases = ["test", "xtest"]'))
        r, env = self.red(self.adapter(text))
        problem = self.failed(env, "census-fixtures")
        self.assertIn("census `census-fixtures`: 2/3 found; missed: `tests/ctl.mini :: also passes`", problem)
        self.assertEqual(env["checks"]["R0"]["census"]["fixtures"],
                         {"found": 2, "listed": 3, "misses": ["tests/ctl.mini :: also passes"]})

    def test_an_adapter_that_misses_a_skip_idiom(self):
        text = adapter_text(lambda t: t.replace('cases = ["test", "it", "xtest"]\nskip = ["xtest"]',
                                                'cases = ["test", "it", "xtest"]\nskip = []'))
        r, env = self.red(self.adapter(text))
        problem = self.failed(env, "skip-idiom")
        self.assertIn("skip idiom: `skipped` runs as skipped (none), but the adapter sees no skip marker on it: it "
                      "misses this skip idiom", problem)

    def test_broken_outcome_patterns(self):
        text = adapter_text(lambda t: t.replace("passed = '(\\d+) passed'", "passed = '(\\d+) ok'"))
        r, env = self.red(self.adapter(text))
        problem = self.failed(env, ["control-pass"])
        self.assertIn("control `pass` read error: 1 passed (want pass)", problem)

    def test_low_assert_density_is_a_needs_human_fail_naming_the_tests(self):
        text = adapter_text(lambda t: t.replace('[[asserts.call]]\nnames = ["assertTrue"]\nkind = "other"\n', ""))
        r, env = self.red(self.adapter(text))
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual(c["density"]["no_assert"], ["tests/calc.mini::sums"])
        es = [e for e in env["entries"] if e["check"] == "R0"]
        self.assertEqual([(e["class"], e["file"]) for e in es], [("needs-human", ".ekit/r0-accepted.json")], es)
        self.assertEqual(es[0]["problem"], "R0 assert density for the `minirun` adapter: 1 of 2 tests (50%) have no "
                                           "assert the adapter recognises, over the 10% limit: `tests/calc.mini::sums`")
        self.assertIn("1 of 2 tests with no recognised assert, 50% (limit 10%): `tests/calc.mini::sums`", c["note"])
        self.assertEqual(r.returncode, 1)

    def test_a_person_accepts_the_list_at_the_base(self):
        text = adapter_text(lambda t: t.replace('[[asserts.call]]\nnames = ["assertTrue"]\nkind = "other"\n', ""))
        self.base = self.commit({".ekit/r0-accepted.json": json.dumps(
            {"assert-density": {"minirun": ["tests/calc.mini::sums"]}})})
        r, env = self.red(self.adapter(text))
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual(c["density"]["accepted"], ["tests/calc.mini::sums"])
        self.assertIn("1 of 2 tests with no recognised assert (1 accepted), 0% (limit 10%)", c["note"])

    def test_an_acceptance_the_pr_itself_adds_does_not_count(self):
        text = adapter_text(lambda t: t.replace('[[asserts.call]]\nnames = ["assertTrue"]\nkind = "other"\n', ""))
        head = self.commit({".ekit/r0-accepted.json": json.dumps(
            {"assert-density": {"minirun": ["tests/calc.mini::sums"]}})})
        r, env = self.red(self.adapter(text), head)
        self.assertEqual(env["checks"]["R0"]["density"]["accepted"], [])
        self.assertEqual(env["checks"]["R0"]["status"], "fail")

    def test_broken_r3_wiring(self):
        text = adapter_text(lambda t: t.replace('format = "mutation-testing-elements"', 'format = "pit-xml"'))
        head = self.commit({"src/calc.mini": "fn add(a, b) { a + b + 0 }\n"})
        r, env = self.mutants(self.adapter(text), head)
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual((c["part"], self.cases(c)), ("r3", {"r3-weak": "fail", "r3-strong": "fail"}))
        es = [e for e in env["entries"] if e["check"] == "R0"]
        self.assertEqual([e["class"] for e in es], ["adapter-fix"], es)
        self.assertIn("R0 runtime half (r3) failed for the `minirun` adapter: R3 control `r3-weak` gave R3 n/a, 0 "
                      "MISSED: mut report out/report.json is malformed (env)", es[0]["problem"])
        self.assertEqual(env["checks"]["R3"]["status"], "n/a")  # blocked: a broken R3 proof is never read as a pass
        self.assertTrue(env["checks"]["R3"]["note"].startswith("blocked: R0 failed"), env["checks"]["R3"])


class R3Control(Case):
    def test_weak_gives_a_missed_mutant_strong_none(self):
        head = self.commit({"src/calc.mini": "fn add(a, b) { a + b + 0 }\n"})
        r, env = self.mutants(None, head)
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual(self.cases(c), {"r3-weak": "pass", "r3-strong": "pass"})
        got = {x["case"]: x["got"] for x in c["cases"]}
        self.assertTrue(got["r3-weak"].startswith("R3 fail, 1 MISSED"), got)
        self.assertTrue(got["r3-strong"].startswith("R3 pass, 0 MISSED"), got)
        self.assertEqual(c["probes"], ["mut --version: mini 1.0.0"])

    def test_only_with_r0_dir_and_shard_0(self):
        head = self.commit({"src/calc.mini": "fn add(a, b) { a + b + 0 }\n"})
        r, env = self.mutants(None, head, "--shard", "1/2")
        self.assertNotIn("R0", env["checks"])


class Fingerprint(Case):
    """C3: a changed toolchain version line re-runs the part; an unchanged fingerprint skips it."""

    def ran(self, env):
        return env["checks"]["R0"]["ran"]

    def test_unchanged_fingerprint_skips_changed_version_reruns(self):
        r, env = self.red()
        self.assertTrue(self.ran(env))
        fp = env["checks"]["R0"]["fingerprint"]
        self.assertTrue(os.path.isfile(os.path.join(self.cache, f"run-{fp}.pass")))
        open(self.log, "w").close()
        r, env = self.red()
        c = env["checks"]["R0"]
        self.assertEqual((c["status"], c["ran"], c["fingerprint"]), ("pass", False, fp), c)
        self.assertEqual(c["note"], f"runtime half (run): fingerprint {fp[:12]} passed before (cache): runner controls "
                                    "and censuses not re-run; no test file changed; assert density: 0 of 2 tests with "
                                    "no recognised assert, 0% (limit 10%)")
        self.assertEqual([x for x in self.calls() if not x.startswith("--version")], [])  # nothing but the probe ran
        with open(os.path.join(self.tmp, "version"), "w") as f:
            f.write("mini 1.1.0\n")
        r, env = self.red()
        c = env["checks"]["R0"]
        self.assertTrue(c["ran"])
        self.assertNotEqual(c["fingerprint"], fp)
        self.assertEqual(c["probes"], ["mini --version: mini 1.1.0"])

    def test_a_failed_part_is_never_remembered(self):
        text = adapter_text(lambda t: t.replace("passed = '(\\d+) passed'", "passed = '(\\d+) ok'"))
        r, env = self.red(self.adapter(text))
        self.assertEqual(env["checks"]["R0"]["status"], "fail")
        self.assertFalse(os.path.isdir(self.cache) and os.listdir(self.cache))
        r, env = self.red(self.adapter(text))
        self.assertTrue(env["checks"]["R0"]["ran"])

    def test_a_pass_file_for_another_fingerprint_is_no_hit(self):
        r, env = self.red()
        fp = env["checks"]["R0"]["fingerprint"]
        with open(os.path.join(self.cache, f"run-{fp}.pass"), "w") as f:
            json.dump({"fingerprint": "0" * 64}, f)
        r, env = self.red()
        self.assertTrue(env["checks"]["R0"]["ran"])

    def test_the_adapter_and_the_fixtures_are_in_the_fingerprint(self):
        r, env = self.red()
        fp = env["checks"]["R0"]["fingerprint"]
        r, env = self.red(self.adapter(adapter_text() + "\n# a comment\n"))
        self.assertNotEqual(env["checks"]["R0"]["fingerprint"], fp)
        fixtures = os.path.join(self.tmp, "fx")
        shutil.copytree(MINIRUN_FX, fixtures)
        with open(os.path.join(fixtures, "runtime", "project", "tests", "ctl.mini.r0"), "a") as f:
            f.write("\n")
        r = _kit.run_cli(["red", "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", "minirun",
                          "--adapter", MINIRUN, "--fixtures", fixtures, "--r0", self.cache])
        self.assertNotEqual(json.loads(r.stdout)["checks"]["R0"]["fingerprint"], fp)

    def test_on_a_hit_the_census_of_the_changed_test_files_still_runs(self):
        self.red()
        head = self.commit({"tests/more.mini": 'spec("new style", {\n  assertEquals(2, add(1, 1))\n})\n'})
        with mock.patch.dict(os.environ, {"STUB_STYLES": "test it xtest spec"}):
            r, env = self.red(None, head)
        c = env["checks"]["R0"]
        self.assertEqual((c["status"], c["ran"]), ("fail", False), c)
        self.assertEqual(c["census"], {"pr": {"found": 0, "listed": 1, "misses": ["tests/more.mini :: new style"]}})
        es = [e for e in env["entries"] if e["check"] == "R0"]
        self.assertEqual([e["class"] for e in es], ["adapter-fix"], es)
        self.assertIn("census `census-pr`: 0/1 found; missed: `tests/more.mini :: new style`", es[0]["problem"])
        self.assertEqual(env["checks"]["R4"]["status"], "n/a")  # blocked
        self.assertEqual(r.returncode, 1)


class TargetOS(Case):
    def test_the_part_runs_only_on_the_stacks_target_os(self):
        other = "linux" if HOST != "linux" else "macos"
        text = adapter_text(lambda t: t.replace(f'target-os = "{HOST}"', f'target-os = "{other}"'))
        r, env = self.red(self.adapter(text))
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "n/a", c)
        self.assertIn(f"the stack runs on {other} (target-os)", c["note"])
        self.assertEqual([x for x in self.calls() if x.startswith(("test", "list"))], [])


class NoFlag(Case):
    def test_without_r0_red_reports_no_r0(self):
        r = _kit.run_cli(["red", "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", "minirun",
                          "--adapter", MINIRUN])
        self.assertNotIn("R0", json.loads(r.stdout)["checks"])


if __name__ == "__main__":
    unittest.main()


class AcceptedListEdits(Case):
    """accepting assert-less tests is a person's call: a PR that adds names to the accepted list is one needs-human
    entry of R0's editing rules (the guard's `r0`); removing names needs no one."""

    def r0(self, head):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", self.base, "--head", head, "--stack", "python"])
        return json.loads(r.stdout)

    def test_a_pr_that_accepts_a_name_needs_a_person(self):
        head = self.commit({".ekit/r0-accepted.json": json.dumps(
            {"assert-density": {"minirun": ["tests/calc.mini::sums"]}})})
        env = self.r0(head)
        es = [e for e in env["entries"] if e["class"] == "needs-human"]
        self.assertEqual([e["problem"] for e in es], [
            "a person decides: `assert-density.minirun` accepts `tests/calc.mini::sums` in .ekit/r0-accepted.json"])
        self.assertEqual(es[0]["file"], ".ekit/r0-accepted.json")

    def test_removing_a_name_needs_no_one(self):
        self.base = self.commit({".ekit/r0-accepted.json": json.dumps(
            {"assert-density": {"minirun": ["tests/calc.mini::sums"]}})})
        head = self.commit({".ekit/r0-accepted.json": json.dumps({"assert-density": {"minirun": []}})})
        self.assertEqual([e for e in self.r0(head)["entries"] if e["class"] == "needs-human"], [])

    def test_a_list_that_does_not_read_at_head_is_named(self):
        head = self.commit({".ekit/r0-accepted.json": "[" * 100})
        es = [e for e in self.r0(head)["entries"] if e["class"] == "needs-human"]
        self.assertEqual([e["problem"] for e in es], [
            "a person decides: .ekit/r0-accepted.json changed and does not read (want {\"assert-density\": {\"<stack>\": "
            "[\"<path>::<test>\", ...]}}): nested too deep (more than 64 levels)"])


class Probes(Case):
    """the version probes keep #19's program rules: never a program in the reviewed checkout, never a launcher an
    adapter file names; a refused one is named, not run."""

    def probes(self, test_cmd):
        text = adapter_text(lambda t: t.replace('test = "mini test"', f'test = "{test_cmd}"'))
        r, env = self.red(self.adapter(text))
        return env["checks"]["R0"]["probes"]

    def test_a_path_in_the_project_dir_is_not_run(self):
        self.assertEqual(self.probes("tools/mini test"), ["tools/mini --version: not probed (a path in the project "
                                                          "dir, which the PR under review can change)",
                                                          "mini --version: mini 1.0.0"])  # [run.list]'s program

    def test_a_launcher_is_not_run(self):
        self.assertEqual(self.probes("python3 -m mini test"),
                         ["python3 --version: not probed (an interpreter, shell or launcher)",
                          "mini --version: mini 1.0.0"])

    def test_a_program_in_the_checkout_is_not_run(self):
        os.makedirs(os.path.join(self.repo, "bin"))
        prog = os.path.join(self.repo, "bin", "mini")
        os.symlink(os.path.join(self.tmp, "stub.py"), prog)
        with mock.patch.dict(os.environ, {"PATH": os.path.join(self.repo, "bin") + os.pathsep + os.environ["PATH"]}):
            got = self.probes("mini test")
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].startswith("mini --version: not probed (in the reviewed checkout: "), got)
        self.assertEqual([x for x in self.calls() if x.startswith("--version")], [])


class FingerprintCommand(Case):
    """`r0 --fingerprint run|r3` prints the part's fingerprint and the cache key the workflow restores, the same one
    `red --r0` and `mutants --r0` compute."""

    def fp(self, part, *extra):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", "minirun",
                          "--adapter", MINIRUN, "--fixtures", MINIRUN_FX, "--fingerprint", part, *extra])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout)

    def test_the_run_part_key_matches_red(self):
        got = self.fp("run")
        r, env = self.red()
        fp = env["checks"]["R0"]["fingerprint"]
        self.assertEqual(got, {"part": "run", "fingerprint": fp, "key": f"ekit-r0-run-{fp}",
                               "probes": ["mini --version: mini 1.0.0"]})

    def test_the_r3_part_key_matches_mutants(self):
        got = self.fp("r3")
        head = self.commit({"src/calc.mini": "fn add(a, b) { a + b + 0 }\n"})
        r, env = self.mutants(None, head)
        self.assertEqual(got["key"], "ekit-r0-r3-" + env["checks"]["R0"]["fingerprint"])

    def test_the_version_line_is_the_one_that_says_version(self):
        with open(os.path.join(self.tmp, "version"), "w") as f:
            f.write("Name: mini\nVersion: 2.0.1\n")
        r, env = self.red()
        self.assertEqual(env["checks"]["R0"]["probes"], ["mini --version: Version: 2.0.1"])


class RepoCensus(Case):
    """the census on the repo at head: a test style the adapter does not know, which the runner lists, is named."""

    def setUp(self):
        super().setUp()
        self.base = self.commit({"tests/spec.mini": 'spec("in a new style", {\n  assertEquals(2, add(1, 1))\n})\n'})
        styles = mock.patch.dict(os.environ, {"STUB_STYLES": "test it xtest spec"})
        styles.start()
        self.addCleanup(styles.stop)

    def test_a_listed_test_the_scanner_misses_fails_r0(self):
        r, env = self.red()
        c = env["checks"]["R0"]
        self.assertEqual(c["census"]["repo"], {"found": 2, "listed": 3, "misses": ["tests/spec.mini :: in a new style"]})
        self.assertEqual([k for k, v in self.cases(c).items() if v == "fail"], ["census-repo"])
        self.assertIn("census: 2/3 listed tests found (missed: `tests/spec.mini :: in a new style`)", c["note"])

    def test_the_census_limit_comes_from_the_adapters_limits(self):
        text = adapter_text(lambda t: t.replace("[commands]", "[limits]\ncensus = 50\n\n[commands]"))
        r, env = self.red(self.adapter(text))
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual(c["census"]["repo"]["misses"], ["tests/spec.mini :: in a new style"])


class ReviewRound1(Case):
    """review round 1 of #21: B1 a PR test cannot forge the cache; B2 density runs on a hit; B3 no listing is n/a; S1
    an empty listing while the scanner finds tests is a fail."""

    def fp(self, head):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", self.base, "--head", head, "--stack", "minirun",
                          "--adapter", MINIRUN, "--fixtures", MINIRUN_FX, "--fingerprint", "run"])
        return json.loads(r.stdout)["fingerprint"]

    def test_b1_a_pass_file_a_pr_test_writes_is_no_hit_and_does_not_survive(self):
        head = self.commit({"tests/poison.mini": 'test("poison", {\n  assertEquals(2, add(1, 1))\n})\n'})
        fp = self.fp(head)
        with mock.patch.dict(os.environ, {"POISON_DIR": self.cache, "POISON_FP": fp}):
            r, env = self.red(None, head)
        c = env["checks"]["R0"]
        self.assertTrue(any("--name poison" in x for x in self.calls()), self.calls())  # R4 ran the forging test
        self.assertEqual((c["ran"], c["fingerprint"]), (True, fp), c)  # read before any PR code ran: no hit
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual(os.listdir(self.cache), [f"run-{fp}.pass"])  # only the verdict this run decided
        with open(os.path.join(self.cache, f"run-{fp}.pass")) as f:
            self.assertEqual(json.load(f)["probes"], ["mini --version: mini 1.0.0"])  # the engine's own file

    def test_b1_a_failed_run_leaves_no_file_a_pr_test_wrote(self):
        text = adapter_text(lambda t: t.replace("passed = '(\\d+) passed'", "passed = '(\\d+) ok'"))
        head = self.commit({"tests/poison.mini": 'test("poison", {\n  assertEquals(2, add(1, 1))\n})\n'})
        with mock.patch.dict(os.environ, {"POISON_DIR": self.cache, "POISON_FP": "f" * 64}):
            r, env = self.red(self.adapter(text), head)
        self.assertEqual(env["checks"]["R0"]["status"], "fail")
        self.assertEqual(os.listdir(self.cache) if os.path.isdir(self.cache) else [], [])

    def test_b2_a_hit_still_measures_assert_density(self):
        self.red()
        bare = 'test("a", {\n  check(add(1, 1))\n})\n\ntest("b", {\n  check(add(1, 2))\n})\n'
        head = self.commit({"tests/bare.mini": bare})
        r, env = self.red(None, head)
        c = env["checks"]["R0"]
        self.assertEqual((c["ran"], c["status"]), (False, "fail"), c)
        self.assertEqual(c["density"]["no_assert"], ["tests/bare.mini::a", "tests/bare.mini::b"])
        self.assertEqual([e["class"] for e in env["entries"] if e["check"] == "R0"], ["needs-human"])

    def test_b3_an_adapter_with_no_listing_is_na_not_a_fail(self):
        text = adapter_text(lambda t: re.sub(r"\[run\.list\]\n(?:[^\n]+\n)+\n", "", t))
        self.assertNotIn("[run.list]", text)
        r, env = self.red(self.adapter(text))
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "n/a", c)
        self.assertEqual({k: v for k, v in self.cases(c).items() if k.startswith("census")},
                         {"census-repo": "n/a", "census-fixtures": "n/a"})
        self.assertEqual([e for e in env["entries"] if e["check"] == "R0"], [])
        self.assertNotIn("R4", [k for k, v in env["checks"].items() if v["status"] == "n/a"])  # blocks nothing

    def test_s1_an_empty_listing_while_the_scanner_finds_tests_fails(self):
        with mock.patch.dict(os.environ, {"STUB_STYLES": "nothing"}):
            r, env = self.red()
        c = env["checks"]["R0"]
        got = {x["case"]: x for x in c["cases"]}
        self.assertEqual(got["census-repo"]["status"], "fail", got["census-repo"])
        self.assertIn("the runner listed no test, the adapter finds 2", got["census-repo"]["got"])

    def test_b3_jest_lists_files_not_tests_n_a(self):
        repo = os.path.join(self.tmp, "jest")
        os.makedirs(os.path.join(repo, "tests"))
        with open(os.path.join(repo, "package.json"), "w") as f:
            f.write('{"name": "j", "devDependencies": {"jest": "29.7.0"}}\n')
        os.makedirs(os.path.join(repo, ".ekit"))
        with open(os.path.join(repo, ".ekit", "stack-plan.toml"), "w") as f:
            f.write(host_plan("ts"))
        with open(os.path.join(repo, "tests", "a.test.js"), "w") as f:
            f.write('test("adds", () => {\n  expect(1 + 1).toBe(2);\n});\n')
        g = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(g[:3] + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-qm", "b"], check=True)
        with mock.patch.dict(os.environ):
            os.environ.pop("MECH_TEST_STUB")  # the real runners: none installed here, so env (n/a)
            r = _kit.run_cli(["red", "--repo", repo, "--base", "HEAD", "--head", "HEAD", "--stack", "ts",
                              "--test-paths", "tests/**", "--r0", self.cache])
        env = json.loads(r.stdout)
        got = {x["case"]: x for x in env["checks"]["R0"]["cases"]}
        self.assertEqual((got["census-repo"]["status"], got["census-repo"]["got"]),
                         ("n/a", "jest lists test files, not tests (`--listTests`): no census"))
        self.assertEqual([e for e in env["entries"] if e["check"] == "R0" and e["class"] == "adapter-fix"], [])

    def test_s3_two_stacks_of_one_repo_never_share_a_key(self):
        head = self.commit({"sub/mini.json": "{}\n", "sub/tests/calc.mini": TESTS})
        keys = set()
        for pd in (".", "sub"):
            r = _kit.run_cli(["r0", "--repo", self.repo, "--base", self.base, "--head", head, "--stack", "minirun",
                              "--adapter", MINIRUN, "--fixtures", MINIRUN_FX, "--project-dir", pd, "--fingerprint", "run"])
            keys.add(json.loads(r.stdout)["key"])
        self.assertEqual(len(keys), 2)

    def test_n3_the_census_of_the_changed_files_keeps_the_census_limit(self):
        text = adapter_text(lambda t: t.replace("[commands]", "[limits]\ncensus = 50\n\n[commands]"))
        adapter = self.adapter(text)
        self.red(adapter)
        head = self.commit({"tests/more.mini": 'spec("new style", {\n  assertEquals(2, add(1, 1))\n})\n\n'
                                               'test("old style", {\n  assertEquals(2, add(1, 1))\n})\n'})
        with mock.patch.dict(os.environ, {"STUB_STYLES": "test it xtest spec"}):
            r, env = self.red(adapter, head)
        c = env["checks"]["R0"]
        self.assertEqual((c["ran"], c["status"]), (False, "pass"), c)
        self.assertEqual(c["census"]["pr"], {"found": 1, "listed": 2, "misses": ["tests/more.mini :: new style"]})


class R3ControlRoots(Case):
    """review N-d: the R3 control refuses what R3 refuses: a tool that resolves on PATH into the reviewed checkout is
    not run in the control's throwaway repo either."""

    def test_a_tool_in_the_reviewed_checkout_is_refused_by_the_control_too(self):
        inside = os.path.join(self.repo, "tools")
        os.makedirs(inside)
        os.symlink(os.path.join(self.tmp, "stub.py"), os.path.join(inside, "mut"))
        head = self.commit({"src/calc.mini": "fn add(a, b) { a + b + 0 }\n"})
        open(self.log, "w").close()
        with mock.patch.dict(os.environ, {"PATH": inside + os.pathsep + os.environ["PATH"]}):
            r, env = self.mutants(None, head)
        got = {x["case"]: x for x in env["checks"]["R0"]["cases"]}
        self.assertIn("in the reviewed checkout", got["r3-weak"]["got"], got)
        self.assertEqual([x for x in self.calls() if x.startswith("run ")], [])  # the tool never ran


JEST_STUB = r'''
import os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
print("Tests:       1 passed, 1 total")
'''


class JestControls(unittest.TestCase):
    """review N-c: a jest repo's runner controls run jest on the ts fixture's jest variant (runtime-jest/), never
    vitest on the vitest project (which read n/a for ever)."""

    def test_a_jest_checkout_runs_the_jest_fixture(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo, log, stub = (os.path.join(tmp.name, n) for n in ("repo", "calls.log", "stub.py"))
        os.makedirs(os.path.join(repo, "tests"))
        with open(stub, "w") as f:
            f.write(JEST_STUB)
        with open(os.path.join(repo, "package.json"), "w") as f:
            f.write('{"name": "j", "devDependencies": {"jest": "29.7.0"}}\n')
        os.makedirs(os.path.join(repo, ".ekit"))
        with open(os.path.join(repo, ".ekit", "stack-plan.toml"), "w") as f:
            f.write(host_plan("ts"))
        with open(os.path.join(repo, "tests", "a.test.js"), "w") as f:
            f.write('test("adds", () => {\n  expect(1 + 1).toBe(2);\n});\n')
        g = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(g[:3] + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-qm", "b"], check=True)
        with mock.patch.dict(os.environ, {"MECH_TEST_STUB": stub, "STUB_LOG": log}):
            _kit.run_cli(["red", "--repo", repo, "--base", "HEAD", "--head", "HEAD", "--stack", "ts",
                          "--test-paths", "tests/**", "--r0", os.path.join(tmp.name, "c")])
        with open(log) as f:
            calls = f.read().splitlines()
        self.assertIn("tests/ctl.test.js -t ^Controls passes$", calls)

    def test_a_file_whose_listing_is_another_runners_says_so(self):
        from scripts.mech_review import adapter_file
        ts = adapter_file.load(os.path.join(_kit.ROOT, "scripts", "mech_review", "adapters", "ts.toml"))
        self.assertIsNone(ts.list_argv("node_modules/.bin/jest"))
        self.assertEqual(ts.no_listing("node_modules/.bin/jest"),
                         "the adapter file's [run.list] lists the `vitest` runner's tests, this checkout runs `jest`: "
                         "no census")
