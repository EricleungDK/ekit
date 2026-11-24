"""T2 (#19): TS with Stryker declared in the shipped adapter file (scripts/mech_review/adapters/ts.toml, [mutation.tool])
gives the built-in ts stack's R3 entries. `mutants --stack ts` runs on the same fixture repo twice, built-in and
`--adapter ts.toml`, through cli.main in this process; the tool is a stub (MECH_TEST_STUB) that replays real Stryker
10.0.0 output (tests/fixtures/stryker). Then the TS mutants suite itself, with TS from the file (MECH_ADAPTER_TS)."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import _kit
from scripts.mech_review import adapter_file

TS_FILE = os.path.join(_kit.ROOT, "scripts", "mech_review", "adapters", "ts.toml")
FX = os.path.join(_kit.ROOT, "tests", "fixtures", "stryker")

STUB = r'''
import os, shutil, sys, time
args = sys.argv[1:]
if args[:1] == ["--input-type=module"]:  # the built-in's instrumenter listing (node): no list, so no cap (as in CI's stub)
    sys.exit(0)
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(os.path.realpath(os.getcwd()) + " | " + " ".join(args) + "\n")
    if args[:1] == ["run"] and os.path.exists("stryker.conf.json"):
        f.write("CONFIG " + open("stryker.conf.json").read() + "\n")
if args[:1] == ["--version"]:
    print("10.0.0")
    sys.exit(0)
if args[:1] != ["run"]:
    sys.exit(0)
if os.environ.get("MUT_REPORT"):
    os.makedirs("reports/mutation", exist_ok=True)
    shutil.copy(os.environ["MUT_REPORT"], "reports/mutation/mutation.json")
if os.environ.get("MUT_STDOUT"):
    sys.stdout.write(open(os.environ["MUT_STDOUT"]).read())
sys.stdout.flush()
if os.environ.get("MUT_HANG"):
    time.sleep(30)
sys.exit(int(os.environ.get("MUT_RC", "0")))
'''

BASE = '''export function add(a: number, b: number): number {
  return a+b;
}

export function isPositive(n: number): boolean {
  return n>0;
}

export function mul(a: number, b: number): number {
  return a * b;
}

export function sub(a: number, b: number): number {
  return a - b;
}
'''
TEST = 'import { it, expect } from "vitest";\nimport { add } from "../src/calc";\n\nit("adds", () => {\n  expect(add(0, 0)).toBe(0);\n});\n'


class Parity(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.log = os.path.join(self.tmp, "calls.log")
        stub = os.path.join(self.tmp, "stub.py")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        bin_dir = os.path.join(self.tmp, "bin")  # `stryker` on PATH, as --mutants-cmd or a global install gives it
        os.makedirs(bin_dir)
        os.symlink(stub, os.path.join(bin_dir, "stryker"))
        self.env = {"MECH_TEST_STUB": stub, "STUB_LOG": self.log, "PATH": bin_dir + os.pathsep + os.environ["PATH"]}

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                               "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout.strip()

    def repo(self, package='{"name":"calc","devDependencies":{"vitest":"5.0.5"}}', extra=None):
        r = tempfile.mkdtemp(dir=self.tmp)
        self.git(r, "init", "-q", "-b", "main")
        files = {"package.json": package, "src/calc.ts": BASE, "tests/calc.test.ts": TEST, ".gitignore": "node_modules/\n"}
        files.update(extra or {})
        for p, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(r, p)) or r, exist_ok=True)
            with open(os.path.join(r, p), "w") as f:
                f.write(text)
        os.makedirs(os.path.join(r, "node_modules", ".bin"))
        for b in ("vitest", "jest"):
            path = os.path.join(r, "node_modules", ".bin", b)
            with open(path, "w") as f:
                f.write("#!/bin/sh\necho 5.0.5\n")
            os.chmod(path, 0o755)
        self.git(r, "add", "-A")
        self.git(r, "commit", "-qm", "base")
        base = self.git(r, "rev-parse", "HEAD")
        shutil.copy(os.path.join(FX, "missed", "head", "src", "calc.ts"), os.path.join(r, "src", "calc.ts"))
        self.git(r, "commit", "-qam", "head")
        return r, base, self.git(r, "rev-parse", "HEAD")

    def both(self, repo, base, head, env, *extra):
        """(built-in envelope, adapter-file envelope, stub calls of each)"""
        out = []
        for adapter in ((), ("--adapter", TS_FILE)):
            open(self.log, "w").close()
            with mock.patch.dict(os.environ, dict(self.env, **env)):
                r = _kit.run_cli(["mutants", "--repo", repo, "--base", base, "--head", head, "--stack", "ts",
                                  "--test-paths", "tests/**", *adapter, *extra])
            self.assertIn(r.returncode, (0, 1), r.stderr)
            with open(self.log) as f:  # the worktree's path changes per run; the built-in's listing is its own
                calls = [re.sub(r"^\S*mech-wt-[^/]+/wt", "WT", ln) for ln in f.read().splitlines()]
            out.append((json.loads(r.stdout), calls))
        return out

    def same(self, env, *extra, **repo):
        r, b, h = self.repo(**repo)
        (built, bcalls), (file, fcalls) = self.both(r, b, h, env, *extra)
        self.assertEqual(file["entries"], built["entries"])
        self.assertEqual(file["checks"]["R3"]["status"], built["checks"]["R3"]["status"])
        self.assertEqual(file["summary"], built["summary"])
        self.assertEqual(fcalls, bcalls)
        return built, file

    def test_missed_mutants_give_the_built_ins_entries_and_stryker_calls(self):
        built, file = self.same({"MUT_REPORT": os.path.join(FX, "missed", "report.json"),
                                 "MUT_STDOUT": os.path.join(FX, "missed", "stdout.txt")})
        self.assertEqual(len(built["entries"]), 5)
        self.assertTrue(file["checks"]["R3"]["note"].startswith("5/5 tested: 5 missed in the diff"))

    def test_jest_and_a_repo_config_give_the_built_ins_entries(self):
        env = {"MUT_REPORT": os.path.join(FX, "missed", "report.json")}
        self.same(env, package='{"name":"calc","devDependencies":{"jest":"30.5.2"}}')
        _, file = self.same(env, extra={"stryker.conf.json": '{"testRunner":"vitest","checkers":[]}'})
        self.assertIn("(repo config stryker.conf.json)", file["checks"]["R3"]["note"])

    def test_zero_baseline_fail_and_budget_give_the_built_ins_entries(self):
        self.same({"MUT_REPORT": os.path.join(FX, "zero", "report.json")})
        self.same({"MUT_STDOUT": os.path.join(FX, "baseline-fail", "stdout.txt"), "MUT_RC": "1"})
        built, file = self.same({"MUT_HANG": "1"}, "--mutation-budget", "0.02")
        self.assertEqual(file["checks"]["R3"]["status"], "partial")

    def test_a_committed_reports_link_is_never_followed_through_the_file(self):  # review F5
        # the built-in ts's own pre-delete is mutants.py's, left as on main (a follow-up: an edit there makes every
        # later R3 regenerate all of mutants.py); through the file, the link is removed, never followed
        r, b, _ = self.repo()
        victim = os.path.join(self.tmp, "victim")
        os.makedirs(os.path.join(victim, "mutation"))
        with open(os.path.join(victim, "mutation", "mutation.json"), "w") as f:
            f.write("precious")
        os.symlink(victim, os.path.join(r, "reports"))
        self.git(r, "add", "-A")
        self.git(r, "commit", "-qm", "link")
        h = self.git(r, "rev-parse", "HEAD")
        open(self.log, "w").close()
        with mock.patch.dict(os.environ, dict(self.env, MUT_REPORT=os.path.join(FX, "missed", "report.json"))):
            out = _kit.run_cli(["mutants", "--repo", r, "--base", b, "--head", h, "--stack", "ts", "--test-paths",
                                "tests/**", "--adapter", TS_FILE])
        file = json.loads(out.stdout)
        self.assertEqual((out.returncode, len(file["entries"])), (1, 5), out.stderr)
        with open(os.path.join(victim, "mutation", "mutation.json")) as f:
            self.assertEqual(f.read(), "precious")

    def test_the_file_declares_stryker(self):
        tool = adapter_file.load(TS_FILE).mutation_tool
        self.assertEqual((tool["name"], tool["command"], tool["report"], tool["format"], tool["os"]),
                         ("stryker", "stryker", "reports/mutation/mutation.json",
                          "mutation-testing-elements", ["linux", "macos", "windows"]))


class Suite(unittest.TestCase):
    """the TS mutants suite (tests/mech-ts-mutants.test.sh) passes with TS from the file, its assertions unchanged; a
    copy of the file that reads another report path fails it, so the pass is the file's."""

    def run_suite(self, path):
        return subprocess.run(["bash", os.path.join(_kit.ROOT, "tests", "mech-ts-mutants.test.sh")],
                              env=dict(os.environ, MECH_ADAPTER_TS=path), capture_output=True, text=True)

    def test_the_suite_passes_through_the_file(self):
        r = self.run_suite(TS_FILE)
        self.assertEqual(r.returncode, 0, "\n".join(ln for ln in r.stdout.splitlines() if "FAIL" in ln) + r.stderr[-2000:])

    def test_the_hook_reaches_r3(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        moved = os.path.join(tmp.name, "ts.toml")
        with open(TS_FILE) as f:
            text = f.read()
        with open(moved, "w") as f:
            f.write(text.replace('report = "reports/mutation/mutation.json"', 'report = "reports/elsewhere.json"'))
        r = self.run_suite(moved)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL ts MISSED mutants: exit 1", r.stdout)


if __name__ == "__main__":
    unittest.main()
