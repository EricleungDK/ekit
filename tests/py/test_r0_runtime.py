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

import _kit

FX = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters")
MINIRUN = os.path.join(FX, "minirun.toml")
MINIRUN_FX = os.path.join(FX, "minirun.r0")

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
        self.assertEqual(c["note"], f"runtime half (run): fingerprint {fp[:12]} passed before (cache): not re-run; no "
                                    "test file changed")
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
        other = "macos" if not __import__("sys").platform == "darwin" else "linux"
        text = adapter_text(lambda t: t.replace('extensions = [".mini"]', f'extensions = [".mini"]\ntarget-os = "{other}"'))
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
