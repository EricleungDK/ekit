"""What a MISSED entry tells the agent to do, for each stack's tool, with the tool replaced by its recorded output."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import _kit
from scripts.mech_review import mutants
from scripts.mech_review.gitio import Review, merge_base
from scripts.mech_review.stack import ADAPTERS

FIXTURES = os.path.join(_kit.ROOT, "tests", "fixtures")
REACH = "no test reaches this line: add a test that calls it and asserts the result." + mutants.HOW


def assert_hint(desc):
    return f"add an assert that fails for this mutant: {desc}." + mutants.HOW


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        self.git("init", "-q")

    def git(self, *args):
        subprocess.run(["git", "-C", self.repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                       capture_output=True)

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def r3(self, stack, runner):
        base, head, mb = merge_base(self.repo, "HEAD~1", "HEAD")
        rv = Review(self.repo, mb, head, ADAPTERS[stack](), ["tests/**"], ".")
        with contextlib.redirect_stderr(io.StringIO()):  # the tool's log tail, printed for the job log
            return mutants.run(rv, None, 5, None, None, runner)


class TestRust(Repo):
    def test_a_missed_mutant_asks_for_an_assert_and_says_how(self):
        self.write("Cargo.toml", '[package]\nname = "x"\nversion = "0.1.0"\n')
        self.write("src/lib.rs", "pub fn add(a: i32, b: i32) -> i32 { a + b }\n")
        self.write("tests/a.rs", "#[test]\nfn adds() {\n    assert_eq!(x::add(1, 2), 3);\n}\n")
        self.commit("base")
        self.write("src/lib.rs", "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n")
        self.commit("head")

        def cargo_mutants(argv, cwd, timeout):
            if "--version" in argv:
                return 0, "cargo-mutants 27.1.0"
            out = argv[argv.index("--output") + 1]  # what the real tool leaves behind for a run with MISSED mutants
            shutil.copytree(os.path.join(FIXTURES, "mutants", "missed"), os.path.join(out, "mutants.out"))
            return 2, ""

        check, entries = self.r3("rust", cargo_mutants)
        self.assertEqual(check["status"], "fail")
        missed = {e["problem"]: e["hint"] for e in entries}
        self.assertEqual(missed["MISSED mutant src/lib.rs:2:11: replace + with - in add"],
                         assert_hint("replace + with - in add"))
        for e in entries:  # each names its own mutant, as its problem does
            self.assertEqual(e["hint"], assert_hint(e["problem"].split(": ", 1)[1]), e["problem"])


class TestTypeScript(Repo):
    def test_survived_asks_for_an_assert_and_no_coverage_for_a_test_that_reaches_the_line(self):
        self.write("package.json", '{"name":"calc","version":"0.0.1","type":"module","devDependencies":{"vitest":"5.0.5"}}\n')
        self.write("src/calc.ts", "export function add(a: number, b: number): number {\n  return a+b;\n}\n\n"
                                  "export function isPositive(n: number): boolean {\n  return n>0;\n}\n")
        self.write("tests/calc.test.ts", 'import { it, expect } from "vitest";\nimport { add } from "../src/calc";\n\n'
                                         'it("adds", () => {\n  expect(add(0, 0)).toBe(0);\n});\n')
        self.commit("base")
        self.write("src/calc.ts", "export function add(a: number, b: number): number {\n  return a + b;\n}\n\n"
                                  "export function isPositive(n: number): boolean {\n  return n > 0;\n}\n")
        self.commit("head")
        self.write("node_modules/.bin/vitest", "")  # installed, as the workflow's install step leaves it

        def stryker(argv, cwd, timeout):
            if "--version" in argv:
                return 0, "10.0.0"
            os.makedirs(os.path.join(cwd, "reports", "mutation"))
            shutil.copy(os.path.join(FIXTURES, "stryker", "missed", "report.json"),
                        os.path.join(cwd, "reports", "mutation", "mutation.json"))
            with open(os.path.join(FIXTURES, "stryker", "missed", "stdout.txt")) as f:
                return 0, f.read()

        check, entries = self.r3("ts", stryker)
        self.assertEqual(check["status"], "fail", check)
        with open(os.path.join(FIXTURES, "stryker", "missed", "report.json")) as f:
            statuses = [m["status"] for m in json.load(f)["files"]["src/calc.ts"]["mutants"]]
        self.assertEqual(sorted(statuses), ["NoCoverage"] * 4 + ["Survived"])
        by_line = {}
        for e in entries:
            by_line.setdefault(e["line"], set()).add(e["hint"])
        self.assertEqual(by_line[6], {REACH})  # the four NoCoverage mutants of isPositive
        (survived,) = [e for e in entries if e["line"] == 2]
        self.assertEqual(survived["hint"], assert_hint(survived["problem"].split(": ", 1)[1]))
        self.assertEqual(len(entries), 5)


class TestPartial(unittest.TestCase):
    def test_the_partial_hint_names_no_stacks_tool_since_every_stack_gets_it(self):
        self.assertEqual(mutants.partial_entry({"tested": 7, "total": 15})["hint"],
                         "read checks.R3.timing (wall, phase seconds, slowest mutants): shrink the diff first, then narrow "
                         "the tests the mutation tool runs, then raise mutation-budget")


if __name__ == "__main__":
    unittest.main()
