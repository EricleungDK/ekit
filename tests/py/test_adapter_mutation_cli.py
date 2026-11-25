"""R3 through an adapter file's declared mutation tool (#19): `mech-review.py mutants|baseline|plan --stack <name>
--adapter <file>` on fixture git repos, through cli.main in this process. The tool is a stub (MECH_TEST_STUB) that
copies a fixture report (tests/fixtures/mutation-reports) to the declared report path, prints STUB_OUT and exits
STUB_RC (or hangs with STUB_HANG). Each report format is checked through R3's entries (T1); no tool, a tool that cannot
run and a tool that does not run on the stack's target OS are n/a (T3-T5); shards, mutation-budget and partial (T6)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _kit

FX = os.path.join(_kit.ROOT, "tests", "fixtures", "mutation-reports")
MINI = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.toml")

STUB = r'''
import os, shutil, sys, time
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(os.path.realpath(os.getcwd()) + " | " + " ".join(args) + "\n")
if args[:1] == ["--version"]:
    print(os.environ.get("STUB_VERSION", "mut 1.0.0"))
    sys.exit(int(os.environ.get("STUB_VERSION_RC", "0")))
src, dst = os.environ.get("STUB_REPORT"), os.environ.get("STUB_TO")
if os.environ.get("STUB_LINK_TO") and dst:  # the run leaves a link at the report path
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    os.symlink(os.environ["STUB_LINK_TO"], dst)
elif src and dst:
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copy(src, dst)
sys.stdout.write(os.environ.get("STUB_OUT", ""))
sys.stdout.flush()
if os.environ.get("STUB_HANG"):
    time.sleep(30)
sys.exit(int(os.environ.get("STUB_RC", "0")))
'''

BASE_SRC = "fn add(a, b) {\n  a+b\n}\n\nfn pos(n) {\n  n>0\n}\n"
HEAD_SRC = "fn add(a, b) {\n  a + b\n}\n\nfn pos(n) {\n  n > 0\n}\n"
TEST = 'suite("Calc", {\n  test("adds", {\n    assertEquals(3, add(1, 2))\n  })\n})\n'

ELEMENTS = '''
[mutation.tool]
name = "mut"
command = "mut"
args = ["run", "--mutate", "{mutate}", "--timeout", "{timeout_ms}"]
mutate = "{file}:{first}-{last}"
version = ["--version"]
version_pattern = '^mut \\d+\\.\\d+'
report = "out/report.json"
format = "mutation-testing-elements"
os = ["linux", "macos"]
baseline_failed = 'initial test run failed'
'''
PIT = '''
[mutation.tool]
name = "pitest"
command = "mvn"
args = ["-q", "pitest:mutationCoverage", "-DtimeoutConstant={timeout_ms}"]
report = "target/pit-reports/mutations.xml"
format = "pit-xml"
os = ["linux"]
'''
LINES = '''
[mutation.tool]
name = "mut"
command = "mut"
args = ["{mutate}"]
mutate = "{file}"
report = "out/report.txt"
format = "lines"
os = ["linux"]
pattern = '^(?P<file>\\S+):(?P<line>\\d+) (?P<status>[A-Z]+) (?P<desc>.+)$'

[mutation.tool.status]
missed = ["SURVIVED"]
caught = ["KILLED"]
timeout = ["SLOW"]
unviable = ["BROKEN"]
'''


def adapter_text(tool="", extensions='[".mini"]', target_os=None):
    with open(MINI) as f:
        text = f.read().replace('extensions = [".mini"]', f"extensions = {extensions}")
    if target_os:
        text = text.replace('manifests = ["mini.json"]', f'manifests = ["mini.json"]\ntarget-os = "{target_os}"')
    return text + tool


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(self.tmp, "repo")
        self.log = os.path.join(self.tmp, "calls.log")
        open(self.log, "w").close()
        stub = os.path.join(self.tmp, "stub.py")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        self.stub = stub
        # the declared tools' programs on PATH, as setup-command installs them (a bare name resolves there, #19 F1)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for prog in ("mut", "mvn"):
            os.symlink(stub, os.path.join(self.bin, prog))
        self.env = {"MECH_TEST_STUB": stub, "STUB_LOG": self.log, "PATH": self.bin + os.pathsep + os.environ["PATH"]}
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                               "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, files):
        for p, text in files.items():
            full = os.path.join(self.repo, p)
            if text is None:
                os.remove(full)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(text)
        self.git("add", "-A")
        self.git("commit", "-qm", "c", "--allow-empty")
        return self.git("rev-parse", "HEAD")

    def adapter(self, text):
        path = os.path.join(self.tmp, "mini.toml")
        with open(path, "w") as f:
            f.write(text)
        return path

    def pr(self, base=None, head=None):
        self.base = self.commit(base or {"mini.json": "{}", "src/calc.mini": BASE_SRC, "tests/calc.mini": TEST})
        self.head = self.commit(head or {"src/calc.mini": HEAD_SRC})

    def cli(self, check, adapter, *extra, env=None):
        with mock.patch.dict(os.environ, dict(self.env, **(env or {}))):
            r = _kit.run_cli([check, "--repo", self.repo, "--base", self.base, "--head", self.head, "--stack", "mini",
                              "--test-paths", "tests/**", "--adapter", adapter, *extra])
        return r, (json.loads(r.stdout) if r.stdout else None)

    def report(self, name, to):
        return {"STUB_REPORT": os.path.join(FX, name), "STUB_TO": to}

    def calls(self):
        with open(self.log) as f:
            return f.read()


def read(path):
    with open(path) as f:
        return f.read()


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def ents(env):
    return [(e["severity"], e["file"], e["line"], e["problem"]) for e in env["entries"]]


class Formats(Case):
    """T1: each report format's fixture, read through R3's entries: MISSED on changed lines only."""

    def test_elements_report(self):
        self.pr()
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env=self.report("elements.json",
                                                                                          "out/report.json"))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(ents(env), [
            ("fail", "src/calc.mini", 2, "MISSED mutant src/calc.mini:2: ArithmeticOperator `a + b` -> `a - b`"),
            ("fail", "src/calc.mini", 6, "MISSED mutant src/calc.mini:6: EqualityOperator `n > 0` -> `n >= 0`")])
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertEqual(env["checks"]["R3"]["note"],
                         "5/6 tested: 2 missed in the diff, 0 missed outside the diff, 0 unlocated, 1 caught, 1 timeout, "
                         "1 unviable; max-mutants not applied: mut makes its own mutants (no listing before its run): "
                         "every changed line runs, the budget the only stop")
        hints = [e["hint"] for e in env["entries"]]
        self.assertTrue(hints[0].startswith("add an assert that fails for this mutant: ArithmeticOperator"), hints[0])
        self.assertTrue(hints[1].startswith("no test reaches this line"), hints[1])
        self.assertIn("| run --mutate src/calc.mini:2-2,src/calc.mini:6-6 --timeout 120000", self.calls())
        self.assertNotIn(os.path.realpath(self.repo) + " |", self.calls())  # in a worktree, not the caller's checkout
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_elements_report_missed_only_on_changed_lines(self):
        self.pr(head={"src/calc.mini": HEAD_SRC.replace("n > 0", "n>0")})  # only line 2 changes
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env=self.report("elements.json",
                                                                                          "out/report.json"))
        self.assertEqual([e[2] for e in ents(env)], [2])
        self.assertIn("1 missed in the diff, 1 missed outside the diff", env["checks"]["R3"]["note"])

    def test_pit_report(self):
        java = "src/main/java/com/example/Calc.java"
        src = "\n".join(f"// {n}" for n in range(1, 15)) + "\n"
        self.pr(base={"mini.json": "{}", java: src, "tests/calc.mini": TEST},
                head={java: src.replace("// 5\n", "int five;\n").replace("// 9\n", "int nine;\n")})
        r, env = self.cli("mutants", self.adapter(adapter_text(PIT, '[".mini", ".java"]')),
                          env=self.report("mutations.xml", "target/pit-reports/mutations.xml"))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(ents(env), [
            ("fail", java, 5, f"MISSED mutant {java}:5: MathMutator in add: Replaced integer addition with subtraction"),
            ("fail", java, 9, f"MISSED mutant {java}:9: ConditionalsBoundaryMutator in isPositive: changed conditional "
                              "boundary")])
        self.assertTrue(env["checks"]["R3"]["note"].startswith(
            "5/6 tested: 2 missed in the diff, 0 missed outside the diff, 0 unlocated, 1 caught, 1 timeout, 1 unviable"))
        self.assertIn("| -q pitest:mutationCoverage -DtimeoutConstant=120000", self.calls())

    def test_pit_report_a_file_two_tracked_paths_end_with_is_unlocated(self):
        a, b = "src/main/java/com/example/Calc.java", "legacy/com/example/Calc.java"
        src = "\n".join(f"// {n}" for n in range(1, 15)) + "\n"
        self.pr(base={"mini.json": "{}", a: src, b: src, "tests/calc.mini": TEST},
                head={a: src.replace("// 5\n", "int five;\n")})
        r, env = self.cli("mutants", self.adapter(adapter_text(PIT, '[".mini", ".java"]')),
                          env=self.report("mutations.xml", "target/pit-reports/mutations.xml"))
        self.assertEqual((r.returncode, sorted((e[0], e[3]) for e in ents(env))), (0, [
            ("confirm", "R3 partial: 1/6 mutants untested at budget"),
            ("confirm", "R3 unlocated: 2 missed mutant(s) have no location in the pitest report "
                        "(target/pit-reports/mutations.xml): not blocking")]), r.stderr)

    def test_lines_report(self):
        self.pr()
        r, env = self.cli("mutants", self.adapter(adapter_text(LINES)), env=self.report("lines.txt", "out/report.txt"))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(ents(env), [("fail", "src/calc.mini", 2, "MISSED mutant src/calc.mini:2: replace + with -"),
                                     ("fail", "src/calc.mini", 6, "MISSED mutant src/calc.mini:6: replace > with >=")])
        self.assertTrue(env["checks"]["R3"]["note"].startswith(
            "5/5 tested: 2 missed in the diff, 0 missed outside the diff, 0 unlocated, 1 caught, 1 timeout, 1 unviable"))
        self.assertIn("| src/calc.mini", self.calls())

    def test_an_entry_id_is_stable_across_a_line_move(self):
        self.pr()
        _, env = self.cli("mutants", self.adapter(adapter_text(LINES)), env=self.report("lines.txt", "out/report.txt"))
        moved = os.path.join(self.tmp, "moved.txt")
        with open(os.path.join(FX, "lines.txt")) as f:
            text = f.read().replace("calc.mini:2 SURVIVED", "calc.mini:6 SURVIVED", 1)
        with open(moved, "w") as f:
            f.write(text)
        _, env2 = self.cli("mutants", self.adapter(adapter_text(LINES)), env={"STUB_REPORT": moved,
                                                                             "STUB_TO": "out/report.txt"})
        self.assertEqual({e["id"] for e in env["entries"]}, {e["id"] for e in env2["entries"]})


class ParserBacked(Case):
    """#27: a parser-backed adapter file ([parser] in place of the pattern tables) declares the same tool: R3 reads the
    tool's report, not source, so it gives the pattern adapter's entries."""

    def test_a_parser_backed_file_runs_its_declared_tool(self):
        from test_parser_cli import HOME_VAR, parser_toml
        self.pr()
        env = self.report("elements.json", "out/report.json")
        _, pattern = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env=env)
        with mock.patch.dict(os.environ):
            os.environ.pop(HOME_VAR, None)  # load only: R3 runs no parser
            text = parser_toml()
        path = os.path.join(self.tmp, "parser.toml")
        with open(path, "w") as f:
            f.write(text + ELEMENTS)
        r, parsed = self.cli("mutants", path, env=env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual((parsed["entries"], parsed["checks"]["R3"]["note"]),
                         (pattern["entries"], pattern["checks"]["R3"]["note"]))
        self.assertEqual(len(parsed["entries"]), 2)

class NotRun(Case):
    def test_no_tool_is_n_a_named_in_the_summary(self):  # T3
        self.pr()
        r, env = self.cli("mutants", self.adapter(adapter_text()))
        self.assertEqual((r.returncode, env["checks"]["R3"], env["entries"]), (0, {
            "status": "n/a", "note": "stack `mini`: the adapter file declares no mutation tool ([mutation.tool]): R3 "
                                     "not run"}, []), r.stderr)
        self.assertEqual(env["summary"], f"pass {self.head} (0 fail, 0 confirm; ran: none; skipped: R1 R2 R4; n/a: R3)")
        self.assertEqual(self.calls(), "")

    def test_no_tool_baseline_runs_no_shard(self):
        self.pr()
        r, env = self.cli("baseline", self.adapter(adapter_text()))
        self.assertEqual((r.returncode, env["checks"]["R3"]["status"], env["run"], env["count"]), (0, "n/a", False, 0))

    def test_a_tool_that_cannot_run_names_the_adapter_key(self):  # T4
        self.pr()
        no_stub = {"MECH_TEST_STUB": ""}
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS.replace('command = "mut"',
                                                                                'command = "ekit-no-such-mut"'))),
                          env=no_stub)
        self.assertEqual((r.returncode, env["checks"]["R3"]["status"]), (0, "n/a"), r.stderr)
        self.assertEqual(env["checks"]["R3"]["note"],
                         "mut not installed (env): `ekit-no-such-mut` not runnable (mutation.tool.command); install it "
                         "(setup-command) or set mutants-cmd")
        self.assertIn("n/a: R3", env["summary"])
        # a probe that exits non-zero, or prints no version, is the same
        for e in ({"STUB_VERSION_RC": "3"}, {"STUB_VERSION": "something else"}):
            with self.subTest(e):
                _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env=e)
                self.assertTrue(env["checks"]["R3"]["note"].startswith("mut not installed (env): `mut` not runnable "
                                                                       "(mutation.tool.command)"))
        # no version probe: the run itself finds the executable missing
        tool = LINES.replace('command = "mut"', 'command = "ekit-no-such-mut"')
        _, env = self.cli("mutants", self.adapter(adapter_text(tool)), env=no_stub)
        self.assertTrue(env["checks"]["R3"]["note"].startswith("mut not installed (env): `ekit-no-such-mut` not runnable "
                                                               "(mutation.tool.command)"), env["checks"]["R3"])

    def test_mutants_cmd_replaces_the_declared_command(self):
        self.pr()
        _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), "--mutants-cmd", "ekit-no-such-mut-either",
                          env={"MECH_TEST_STUB": ""})
        self.assertIn("`ekit-no-such-mut-either` not runnable", env["checks"]["R3"]["note"])

    def test_a_tool_that_does_not_run_on_the_target_os(self):  # T5
        self.pr()
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS, target_os="windows")))
        self.assertEqual((r.returncode, env["checks"]["R3"]), (0, {
            "status": "n/a", "note": "mut does not run on windows (env): mutation.tool.os lists linux, macos; the "
                                     "stack's target-os is windows"}), r.stderr)
        self.assertEqual(self.calls(), "")

    def test_no_report_is_n_a_and_a_failing_baseline_is_a_fail(self):  # name kept (#22: the verdict is now a fail)
        """#22 review round 2: the tool ran and left no report: R3 did not judge the change, and the tool is there, so
        it is a fail with one entry, never n/a (env) (a toolchain absence) and never a pass."""
        self.pr()
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"STUB_OUT": "boom\n", "STUB_RC": "2"})
        problem = "mut ran and wrote no report (out/report.json): mutants not read: boom"
        self.assertEqual((r.returncode, env["checks"]["R3"]), (1, {"status": "fail", "note": problem}))
        self.assertEqual([(e["class"], *x) for e, x in zip(env["entries"], ents(env))],
                         [("agent-fixable", "fail", "", 0, problem)])
        self.assertEqual([e["check"] for e in env["entries"]], ["R3"])

    def test_no_report_after_a_dependency_fetch_failed_is_a_ci_entry(self):  # #22 final
        """the runner could not fetch the tool or a dependency: still a fail, never a pass, and the entry is CI's (check
        CI, class env, as a job with no result), not the PR's."""
        self.pr()
        for out in ("[INFO] Scanning\n[ERROR] Failed: Could not resolve dependencies for project x\n",
                    "[ERROR] Could not transfer artifact org.pitest:pitest:jar:1.17.4 from/to central\n",
                    "[ERROR] ... Unknown host repo.maven.apache.org\n"):
            with self.subTest(out):
                r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"STUB_OUT": out, "STUB_RC": "1"})
                self.assertEqual((r.returncode, env["checks"]["R3"]["status"]), (1, "fail"))
                self.assertEqual([(e["check"], e["class"], e["severity"]) for e in env["entries"]], [("CI", "env", "fail")])
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)),
                          env={"STUB_OUT": "x\ninitial test run failed\n", "STUB_RC": "1"})
        self.assertEqual((r.returncode, ents(env)), (1, [("fail", "", 0, "baseline tests fail at head: mutants not run")]))

    def test_a_malformed_report_is_n_a_naming_the_file(self):
        self.pr()
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as f:
            f.write('{"files": {"src/calc.mini": {"mutants": [{"status": "Zombie"}]}}}')
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"STUB_REPORT": bad,
                                                                               "STUB_TO": "out/report.json"})
        self.assertEqual((r.returncode, env["checks"]["R3"]["status"]), (0, "n/a"), r.stderr)
        self.assertTrue(env["checks"]["R3"]["note"].startswith(
            "mut report out/report.json is malformed (env): a mutant in `src/calc.mini` has status `Zombie`"),
            env["checks"]["R3"]["note"])

    def test_a_covered_mutant_no_test_completed_is_n_a(self):
        self.pr()
        doc = json.loads(read(os.path.join(FX, "elements.json")))
        doc["files"]["src/calc.mini"]["mutants"][0]["testsCompleted"] = 0
        silent = os.path.join(self.tmp, "silent.json")
        write(silent, json.dumps(doc))
        _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"STUB_REPORT": silent,
                                                                               "STUB_TO": "out/report.json"})
        self.assertEqual(env["checks"]["R3"]["status"], "n/a")
        self.assertIn("completed no test for 1 covered mutant(s) (env)", env["checks"]["R3"]["note"])

    def test_a_committed_report_is_never_read_as_the_runs(self):
        self.pr(head={"src/calc.mini": HEAD_SRC, "out/report.json": read(os.path.join(FX, "elements.json"))})
        _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)))
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertTrue(env["checks"]["R3"]["note"].startswith("mut ran and wrote no report (out/report.json)"))

    def pr_with(self, plant):
        """base, then a head that changes calc.mini and lets plant(repo dir) put things in the checkout."""
        self.base = self.commit({"mini.json": "{}", "src/calc.mini": BASE_SRC, "tests/calc.mini": TEST})
        with open(os.path.join(self.repo, "src", "calc.mini"), "w") as f:
            f.write(HEAD_SRC)
        plant(self.repo)
        self.git("add", "-A")
        self.git("commit", "-qm", "head")
        self.head = self.git("rev-parse", "HEAD")

    def test_a_committed_link_or_file_on_the_report_path_is_cleared_without_following_it(self):  # review F5
        victim = os.path.join(self.tmp, "victim")
        os.makedirs(victim)
        write(os.path.join(victim, "report.json"), "precious")
        plants = {"a link for its dir": lambda r: os.symlink(victim, os.path.join(r, "out")),
                  "a link for itself": lambda r: (os.makedirs(os.path.join(r, "out")),
                                                  os.symlink(os.path.join(victim, "report.json"),
                                                             os.path.join(r, "out", "report.json"))),
                  "a file for its dir": lambda r: write(os.path.join(r, "out"), "x"),
                  "a dir for itself": lambda r: (os.makedirs(os.path.join(r, "out", "report.json")),
                                                 write(os.path.join(r, "out", "report.json", "x"), "x"))}
        for what, plant in plants.items():
            with self.subTest(what):
                self.git("rm", "-rq", "--ignore-unmatch", "out")
                self.pr_with(plant)
                r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env=self.report("elements.json",
                                                                                                  "out/report.json"))
                self.assertEqual((r.returncode, len(env["entries"]), env["checks"]["R3"]["status"]), (1, 2, "fail"),
                                 env["checks"]["R3"])
                self.assertEqual(read(os.path.join(victim, "report.json")), "precious")

    def test_a_report_the_run_leaves_as_a_link_out_of_the_project_dir_is_a_fail(self):  # review F5
        self.pr()
        outside = os.path.join(self.tmp, "outside.json")
        write(outside, read(os.path.join(FX, "elements.json")))
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"STUB_LINK_TO": outside,
                                                                               "STUB_TO": "out/report.json"})
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertEqual([(e["class"], e["severity"], e["problem"]) for e in env["entries"]], [
            ("agent-fixable", "fail", "mut report out/report.json leads out of the project dir after the run: not read")])

    def test_no_production_change_is_skipped_and_runs_nothing(self):
        self.pr(head={"tests/calc.mini": TEST.replace("3, add", "3,  add")})
        _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)))
        self.assertEqual((env["checks"]["R3"]["status"], self.calls()), ("skipped", ""))

    def test_no_manifest_is_n_a_naming_it(self):
        self.pr(base={"src/calc.mini": BASE_SRC, "tests/calc.mini": TEST})
        _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)))
        self.assertEqual(env["checks"]["R3"], {"status": "n/a", "note": "no mini.json in .: set project-dir"})


class ProgramOutsideTheCheckout(Case):
    """review F1: the declared program is resolved on PATH (absolute entries only) or taken as an absolute path, and
    never run from the reviewed checkout."""

    def test_a_program_a_path_entry_finds_in_the_checkout_is_a_fail_a_person_fixes(self):
        self.pr()
        inside = os.path.join(self.repo, "tooling")  # untracked, in the caller's checkout: the PR's own tree
        os.makedirs(inside)
        os.symlink(self.stub, os.path.join(inside, "mut"))
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)),
                          env={"PATH": inside + os.pathsep + self.env["PATH"]})
        self.assertEqual(r.returncode, 1, r.stderr)
        real = os.path.realpath(os.path.join(inside, "mut"))
        self.assertEqual([(e["class"], e["severity"], e["problem"]) for e in env["entries"]], [
            ("needs-human", "fail", f"the mutation tool `mut` resolves to {os.path.join(inside, 'mut')} ({real}), in "
                                    "the reviewed checkout: mutants not run")])
        self.assertEqual(self.calls(), "")

    def test_an_absolute_command_in_the_checkout_is_the_same_fail(self):
        self.pr()
        prog = os.path.join(self.repo, "tooling", "mut")
        os.makedirs(os.path.dirname(prog))
        os.symlink(self.stub, prog)
        tool = ELEMENTS.replace('command = "mut"', f'command = "{prog}"')
        r, env = self.cli("mutants", self.adapter(adapter_text(tool)))
        self.assertEqual((r.returncode, [e["class"] for e in env["entries"]]), (1, ["needs-human"]), r.stderr)

    def test_a_relative_path_entry_never_finds_the_prs_program(self):
        self.pr(head={"src/calc.mini": HEAD_SRC, "mut": "#!/bin/sh\nexit 0\n"})
        os.chmod(os.path.join(self.repo, "mut"), 0o755)
        self.git("add", "-A")
        self.git("commit", "-qm", "exec")
        self.head = self.git("rev-parse", "HEAD")
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"PATH": "." + os.pathsep + "/usr/bin"})
        self.assertEqual(env["checks"]["R3"], {"status": "n/a", "note": "mut not installed (env): `mut` not runnable "
                                               "(mutation.tool.command); install it (setup-command) or set mutants-cmd"})
        self.assertEqual(self.calls(), "")

    def test_a_launcher_is_not_run_whatever_the_name_it_is_found_by(self):  # review round 2, R2-1
        self.pr()
        env_prog = os.path.realpath(shutil.which("env"))
        os.remove(os.path.join(self.bin, "mut"))
        os.symlink(env_prog, os.path.join(self.bin, "mut"))  # `mut` on PATH is env in disguise
        for extra in ((), ("--mutants-cmd", "python3 tools/mut")):
            with self.subTest(extra):
                r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), *extra)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertEqual([(e["class"], e["severity"]) for e in env["entries"]], [("needs-human", "fail")])
                self.assertIn("is an interpreter, shell or launcher: mutants not run", env["entries"][0]["problem"])
                self.assertEqual(self.calls(), "")

    def test_a_lookup_that_answers_a_relative_path_is_not_found(self):  # review round 2, R2-2 (Windows `.\\mut.exe`)
        self.pr()
        with mock.patch("scripts.mech_review.mutation_tool.shutil.which", return_value=".\\mut.exe"):
            _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)))
        self.assertEqual(env["checks"]["R3"]["note"], "mut not installed (env): `mut` not runnable "
                                                      "(mutation.tool.command); install it (setup-command) or set "
                                                      "mutants-cmd")
        self.assertEqual(self.calls(), "")

    def test_a_relative_mutants_cmd_is_not_run_from_the_checkout(self):
        self.pr()
        _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), "--mutants-cmd", "bin/mut")
        self.assertEqual(env["checks"]["R3"]["status"], "n/a")
        self.assertIn("`bin/mut` not runnable", env["checks"]["R3"]["note"])
        self.assertEqual(self.calls(), "")


class ReviewNits(Case):
    def test_mutate_join_applies_only_when_mutate_is_used(self):  # review F7
        tool = ELEMENTS.replace('args = ["run", "--mutate", "{mutate}", "--timeout", "{timeout_ms}"]',
                                'args = ["run"]').replace('mutate = "{file}:{first}-{last}"\n', "")
        self.pr(base={"mini.json": "{}", "src/a,b.mini": BASE_SRC, "tests/calc.mini": TEST},
                head={"src/a,b.mini": HEAD_SRC})
        _, env = self.cli("mutants", self.adapter(adapter_text(tool)), env=self.report("elements.json",
                                                                                      "out/report.json"))
        self.assertNotIn("mutate_join", env["checks"]["R3"]["note"])
        self.assertIn("| run\n", self.calls())

    def test_a_silent_mutant_in_another_shards_file_leaves_this_shard_alone(self):  # review F8
        self.pr(base={"mini.json": "{}", "src/calc.mini": BASE_SRC, "src/more.mini": BASE_SRC, "tests/calc.mini": TEST},
                head={"src/calc.mini": HEAD_SRC, "src/more.mini": HEAD_SRC})
        doc = json.loads(read(os.path.join(FX, "elements.json")))
        doc["files"]["src/calc.mini"]["mutants"][0]["testsCompleted"] = 0  # calc.mini is shard 0's
        p = os.path.join(self.tmp, "silent.json")
        write(p, json.dumps(doc))
        tool = self.adapter(adapter_text(ELEMENTS))
        _, one = self.cli("mutants", tool, "--shard", "1/2", env={"STUB_REPORT": p, "STUB_TO": "out/report.json"})
        self.assertEqual(one["checks"]["R3"]["status"], "pass", one["checks"]["R3"])
        _, zero = self.cli("mutants", tool, "--shard", "0/2", env={"STUB_REPORT": p, "STUB_TO": "out/report.json"})
        self.assertEqual(zero["checks"]["R3"]["status"], "n/a")

    def test_two_shards_merge_to_the_one_shard_result(self):  # review F10
        self.pr(base={"mini.json": "{}", "src/calc.mini": BASE_SRC, "src/more.mini": BASE_SRC, "src/other.mini": BASE_SRC,
                      "tests/calc.mini": TEST}, head={"src/calc.mini": HEAD_SRC, "src/more.mini": HEAD_SRC})
        doc = json.loads(read(os.path.join(FX, "elements.json")))
        f = doc["files"]["src/calc.mini"]
        doc["files"].update({"src/more.mini": f, "src/other.mini": f, "../x.mini": f})  # unchanged, outside the crate
        p = os.path.join(self.tmp, "r.json")
        write(p, json.dumps(doc))
        tool = self.adapter(adapter_text(ELEMENTS))
        got = {}
        for shard in ("0/1", "0/2", "1/2"):
            _, got[shard] = self.cli("mutants", tool, "--shard", shard, env={"STUB_REPORT": p, "STUB_TO": "out/report.json"})
            path = os.path.join(self.tmp, shard.replace("/", "-") + ".json")
            write(path, json.dumps(got[shard]))
        self.assertEqual([(got[s]["checks"]["R3"]["tested"], got[s]["checks"]["R3"]["total"]) for s in got],
                         [(20, 24), (15, 18), (5, 6)])
        r = _kit.run_cli(["merge", "--repo", self.tmp, "--base", got["0/1"]["base"], "--head", got["0/1"]["head"],
                          "--stack", "mini", "--shards", "2", "--envelope", "0=" + os.path.join(self.tmp, "0-2.json"),
                          "--envelope", "1=" + os.path.join(self.tmp, "1-2.json")])
        merged = json.loads(r.stdout)
        self.assertEqual((merged["checks"]["R3"]["status"], merged["checks"]["R3"]["tested"],
                          merged["checks"]["R3"]["total"]), ("fail", 20, 24), r.stderr)
        self.assertEqual(sorted(e["id"] for e in merged["entries"]), sorted(e["id"] for e in got["0/1"]["entries"]))

class ShardsBudgetPartial(Case):
    """T6: shards deal the changed production files round robin, the budget stops a run, partial is never a pass."""

    def two_files(self):
        self.pr(base={"mini.json": "{}", "src/calc.mini": BASE_SRC, "src/more.mini": BASE_SRC, "tests/calc.mini": TEST},
                head={"src/calc.mini": HEAD_SRC, "src/more.mini": HEAD_SRC})

    def test_each_shard_mutates_its_own_files(self):
        self.two_files()
        tool = self.adapter(adapter_text(ELEMENTS))
        _, env = self.cli("mutants", tool, "--shard", "1/2", env=self.report("elements.json", "out/report.json"))
        self.assertEqual(env["shard"], {"k": 1, "n": 2, "max_mutants": 40})
        self.assertIn("| run --mutate src/more.mini:2-2,src/more.mini:6-6 ", self.calls())
        self.assertNotIn("src/calc.mini:2-2", self.calls())
        self.assertEqual(env["entries"], [])  # the report's mutants are in calc.mini: another shard's file
        _, env = self.cli("baseline", tool, "--shards", "4")
        self.assertEqual((env["run"], env["count"], env["checks"]["R3"]["note"]),
                         (True, 2, "2 changed production file(s) in 2 shard(s)"))
        r = _kit.run_cli(["plan", "--repo", self.repo, "--base", self.base, "--head", self.head, "--stack", "mini",
                          "--test-paths", "tests/**", "--adapter", tool])
        self.assertEqual((r.returncode, json.loads(r.stdout)), (0, {"run": True}), r.stderr)

    def test_a_shard_with_no_file_passes_with_no_run(self):
        self.pr()
        _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), "--shard", "1/2")
        self.assertEqual(env["checks"]["R3"], {"status": "pass", "tested": 0, "total": 0, "note": "0 mutants in the diff "
                                               "(no changed production file in this shard)"})
        self.assertEqual(self.calls(), "")

    def test_budget_hit_before_the_report_is_partial_with_one_confirm(self):
        self.pr()
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), "--mutation-budget", "0.02",
                          env={"STUB_HANG": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((env["checks"]["R3"]["status"], env["checks"]["R3"]["tested"], env["checks"]["R3"]["total"]),
                         ("partial", None, None))
        self.assertTrue(env["checks"]["R3"]["note"].startswith("budget hit before mut wrote its report: ? mutants, "
                                                               "none read"), env["checks"]["R3"]["note"])
        self.assertEqual([(e[0], e[3]) for e in ents(env)],
                         [("confirm", "R3 partial: total unknown (? tested): untested mutants unknown at budget")])
        self.assertIn("partial: R3", env["summary"])

    def test_budget_hit_after_the_report_keeps_its_missed(self):
        self.pr()
        _, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), "--mutation-budget", "0.02",
                          env=dict(self.report("elements.json", "out/report.json"), STUB_HANG="1"))
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertIn("; budget hit after mut wrote its report", env["checks"]["R3"]["note"])

    def test_pending_mutants_with_nothing_missed_are_partial(self):
        self.pr()
        doc = json.loads(read(os.path.join(FX, "elements.json")))
        for m in doc["files"]["src/calc.mini"]["mutants"]:
            if m["status"] in ("Survived", "NoCoverage"):
                m["status"] = "Killed"
        p = os.path.join(self.tmp, "killed.json")
        write(p, json.dumps(doc))
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"STUB_REPORT": p,
                                                                               "STUB_TO": "out/report.json"})
        self.assertEqual((r.returncode, env["checks"]["R3"]["status"], env["checks"]["R3"]["tested"],
                          env["checks"]["R3"]["total"]), (0, "partial", 5, 6))
        self.assertEqual([e[3] for e in ents(env)], ["R3 partial: 1/6 mutants untested at budget"])

    def test_the_mutant_timeout_reaches_the_tool(self):
        self.pr()
        self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), "--mutant-timeout", "7")
        self.assertIn("--timeout 7000", self.calls())


if __name__ == "__main__":
    unittest.main()
