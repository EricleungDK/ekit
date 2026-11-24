"""R0 runtime half (#21): what reaches the run and the fingerprint from the command line, through cli.main in this
process: the target OS (the plan entry's first), the adapter file and its fixtures (given, beside it, or the repo's own
in a project dir), the test and mutation commands, the agent prefix, and the help text. Written from mutmut's survivors
on the changed lines (#76): each test fails when its value is dropped or replaced."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import _kit
from test_r3_cap import LISTED, STUB as CARGO_STUB, git
from test_r0_runtime import HOST, MINIRUN, MINIRUN_FX, TESTS, SRC, Case, adapter_text, host_plan

OTHER = "linux" if HOST != "linux" else "macos"


def norm(text):
    return re.sub(r"\s+", " ", text)


class Help(Case):
    def test_the_r0_options_of_the_main_command(self):
        r = _kit.run_cli(["--help"])
        out = norm(r.stdout)
        self.assertIn("--fixtures DIR all, and red or mutants with --r0: R0's fixture dir (default: the built-in "
                      "stack's, or the adapter file's)", out)
        self.assertIn("--r0 DIR red, all, mutants (#21): run R0's runtime half (red, all: census, assert density, "
                      "runner controls; mutants, shard 0: the R3 control) unless DIR holds a pass for its fingerprint; "
                      "a pass is written there", out)

    def test_the_fingerprint_options_of_r0(self):
        r = _kit.run_cli(["r0", "--help"])
        out = norm(r.stdout)
        self.assertIn("--fingerprint {run,r3} print the fingerprint of the runtime half's part (#21: run, as red --r0 "
                      "computes it; r3, as mutants --r0 does) and its cache key, {part, fingerprint, key, probes}; "
                      "nothing is proved", out)
        self.assertIn("--test-cmd CMD --fingerprint run: the test command red is given", out)
        self.assertIn("--mutants-cmd CMD --fingerprint r3: the mutation tool mutants is given", out)
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", "python",
                          "--fingerprint", "both"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("argument --fingerprint: invalid choice: 'both'", r.stderr)


class Fingerprint(Case):
    def fp(self, *extra, repo=None, base=None, rc=0):
        r = _kit.run_cli(["r0", "--repo", repo or self.repo, "--base", base or self.base, "--head", base or self.base,
                          *extra])
        self.assertEqual(r.returncode, rc, r.stderr + r.stdout)
        return json.loads(r.stdout)["fingerprint"] if rc == 0 else r

    def mini(self, part="run", *extra):
        return self.fp("--stack", "minirun", "--adapter", MINIRUN, "--fixtures", MINIRUN_FX, "--fingerprint", part, *extra)

    def test_the_test_and_mutation_commands_are_in_it(self):
        self.assertNotEqual(self.mini("run"), self.mini("run", "--test-cmd", "mini test --verbose"))
        self.assertNotEqual(self.mini("r3"), self.mini("r3", "--mutants-cmd", "mut --fast"))

    def test_the_accepted_list_at_the_base_is_in_it(self):
        before = self.mini()
        self.base = self.commit({".ekit/r0-accepted.json": '{"assert-density": {"minirun": ["tests/calc.mini::adds"]}}'})
        self.assertNotEqual(self.mini(), before)

    def test_the_plan_entrys_target_os_is_in_it(self):
        py = {"pyproject.toml": "[project]\nname = 'x'\nversion = '0'\n"}
        a = self.commit(dict(py, **{".ekit/stack-plan.toml": host_plan("python")}))
        b = self.commit({".ekit/stack-plan.toml": host_plan("python").replace(HOST, OTHER)})
        self.assertNotEqual(self.fp("--stack", "python", "--fingerprint", "run", base=a),
                            self.fp("--stack", "python", "--fingerprint", "run", base=b))

    def test_an_adapter_file_for_another_stack_is_a_usage_error(self):
        r = self.fp("--stack", "other", "--adapter", MINIRUN, "--fingerprint", "run", rc=2)
        self.assertEqual(r.stderr.strip(), f"mech-review: adapter file {MINIRUN} describes stack `minirun`, not `other`")

    def test_a_git_error_is_named_and_exit_2(self):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", "no-such-ref", "--head", self.base, "--stack", "minirun",
                          "--adapter", MINIRUN, "--fingerprint", "run"])
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertTrue(r.stderr.startswith("mech-review: "), r.stderr)


class TargetOS(Case):
    def red(self, stack, *extra):
        r = _kit.run_cli(["red", "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", stack,
                          "--test-paths", "tests/**", "--r0", self.cache, *extra])
        self.assertIn(r.returncode, (0, 1), r.stderr + r.stdout)
        return json.loads(r.stdout)["checks"]["R0"]

    def test_a_plan_entrys_target_os_moves_a_built_in(self):
        self.base = self.commit({".ekit/stack-plan.toml": host_plan("python").replace(HOST, OTHER)})
        c = self.red("python")
        self.assertEqual(c["status"], "n/a", c)
        self.assertIn(f"the stack runs on {OTHER} (target-os), this machine is {HOST}", c["note"])

    def test_a_built_in_with_no_plan_targets_linux(self):
        c = self.red("python")
        if HOST == "linux":
            self.assertIn("fingerprint", c, c)
        else:
            self.assertIn(f"the stack runs on linux (target-os), this machine is {HOST}", c["note"])

    def test_a_base_plan_that_does_not_read_and_the_pr_that_fixes_it(self):
        self.base = self.commit({".ekit/stack-plan.toml": "[[stack]]\nname = \n"})
        head = self.commit({".ekit/stack-plan.toml": host_plan("python").replace(HOST, OTHER)})
        r = _kit.run_cli(["red", "--repo", self.repo, "--base", self.base, "--head", head, "--stack", "python",
                          "--test-paths", "tests/**", "--r0", self.cache])
        c = json.loads(r.stdout)["checks"]["R0"]
        self.assertIn(f"the stack runs on {OTHER} (target-os)", c["note"])  # the PR's own plan judges it


class AdapterFiles(Case):
    def test_an_adapter_file_finds_its_fixtures_beside_it(self):
        d = os.path.join(self.tmp, "beside")
        os.makedirs(d)
        shutil.copy(MINIRUN, os.path.join(d, "minirun.toml"))
        shutil.copytree(MINIRUN_FX, os.path.join(d, "minirun.r0"))
        r = _kit.run_cli(["red", "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", "minirun",
                          "--adapter", os.path.join(d, "minirun.toml"), "--test-paths", "tests/**", "--r0", self.cache])
        c = json.loads(r.stdout)["checks"]["R0"]
        self.assertEqual((c["status"], c["census"]["fixtures"]["listed"]), ("pass", 3), c)

    def test_a_failed_case_names_the_adapter_file(self):
        bad = self.adapter(adapter_text(lambda t: t.replace("passed = '(\\d+) passed'", "passed = '(\\d+) ok'")))
        r, env = self.red(bad)
        self.assertEqual([e["file"] for e in env["entries"] if e["check"] == "R0"], [bad])


class RepoAdapterInAProjectDir(Case):
    """the plan's entry for a stack in folder sub names its adapter file sub/minirun.toml, fixtures beside it."""

    def setUp(self):
        super().setUp()
        files = {"sub/minirun.toml": adapter_text(), "sub/mini.json": "{}\n", "sub/src/calc.mini": SRC,
                 "sub/tests/calc.mini": TESTS,
                 ".ekit/stack-plan.toml": '[[stack]]\nname = "minirun"\nfolder = "sub"\nadapter = "sub/minirun.toml"\n'
                                          f'status = "current"\ntarget-os = "{HOST}"\n'}
        for top, _, names in os.walk(MINIRUN_FX):
            for n in names:
                full = os.path.join(top, n)
                with open(full) as f:
                    files["sub/minirun.r0/" + os.path.relpath(full, MINIRUN_FX).replace(os.sep, "/")] = f.read()
        self.base = self.commit(files)

    def cli(self, check, head=None, *extra):
        r = _kit.run_cli([check, "--repo", self.repo, "--base", self.base, "--head", head or self.base,
                          "--stack", "minirun", "--project-dir", "sub", "--test-paths", "sub/tests/**", *extra])
        self.assertIn(r.returncode, (0, 1), r.stderr + r.stdout)
        return json.loads(r.stdout)

    def test_red_proves_the_entrys_file_and_its_key_matches_the_fingerprint(self):
        env = self.cli("red", None, "--r0", self.cache)
        c = env["checks"]["R0"]
        self.assertEqual((c["status"], c["census"]["repo"]), ("pass", {"found": 2, "listed": 2, "misses": []}), c)
        got = self.cli("r0", None, "--fingerprint", "run")
        self.assertEqual(got["fingerprint"], c["fingerprint"])

    def test_the_adapter_file_at_the_base_is_in_the_fingerprint(self):
        before = self.cli("r0", None, "--fingerprint", "run")["fingerprint"]
        self.base = self.commit({"sub/minirun.toml": adapter_text() + "\n# a comment\n"})
        self.assertNotEqual(self.cli("r0", None, "--fingerprint", "run")["fingerprint"], before)

    def test_red_passes_the_test_command_and_the_agent_prefix_on(self):
        head = self.commit({"sub/src/calc.mini": "fn add(a, b) { a + b + 0 }\n",
                            "sub/tests/more.mini": 'test("more", {\n  assertEquals(2, add(1, 1))\n})\n'})
        env = self.cli("red", head, "--r0", self.cache, "--test-cmd", "mini test --verbose", "--head-branch", "feat/x",
                       "--agent-prefix", "feat/")
        self.assertNotEqual(env["checks"]["R1"]["status"], "skipped", env["checks"]["R1"])  # feat/ is an agent prefix
        self.assertTrue(any(x.startswith("test --verbose ") for x in self.calls()), self.calls())

    def test_mutants_runs_the_r3_control_for_the_repo_file(self):
        head = self.commit({"sub/src/calc.mini": "fn add(a, b) { a + b + 0 }\n"})
        env = self.cli("mutants", head, "--r0", self.cache)
        c = env["checks"]["R0"]
        self.assertEqual((c["part"], c["status"]), ("r3", "pass"), c)



class UsageErrors(Case):
    def usage(self, *argv):
        r = _kit.run_cli([argv[0], "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", "minirun",
                          "--adapter", MINIRUN, *argv[1:]])
        self.assertEqual(r.returncode, 2, r.stdout)
        return r.stderr.strip().splitlines()[-1]

    def test_fixtures_without_r0_on_red_or_mutants_is_a_usage_error(self):
        want = "mech-review.py: error: --fixtures applies to all and r0, and to red and mutants with --r0 (R0's fixture dir)"
        self.assertEqual(self.usage("red", "--fixtures", MINIRUN_FX), want)
        self.assertEqual(self.usage("r2", "--fixtures", MINIRUN_FX, "--r0", self.cache), want)

    def test_r0_on_another_subcommand_is_a_usage_error(self):
        self.assertEqual(self.usage("r2", "--r0", self.cache),
                         "mech-review.py: error: --r0 applies to red, all and mutants (R0's runtime half)")


class BuiltinMutants(unittest.TestCase):
    """main's engine.run for a built-in's R3 (#21 moved the call into a with block): the mutation command, the
    per-mutant timeout and the project dir reach the tool. cargo-mutants is test_r3_cap's stub, in process."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, "crate", "src"))
        with open(os.path.join(self.repo, "crate", "Cargo.toml"), "w") as f:
            f.write('[package]\nname = "x"\nversion = "0.1.0"\n')
        lib = os.path.join(self.repo, "crate", "src", "lib.rs")
        with open(lib, "w") as f:
            f.write("pub fn add(a: i32, b: i32) -> i32 { a + b }\n")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        with open(lib, "a") as f:
            f.write("// head\n")
        git(self.repo, "commit", "-q", "-am", "head")
        self.log, stub, listing = (os.path.join(tmp.name, n) for n in ("calls.log", "stub.py", "list.json"))
        with open(stub, "w") as f:
            f.write(CARGO_STUB.replace('args[:2] == ["mutants", "--version"]', '"--version" in args'))
        with open(listing, "w") as f:
            json.dump(LISTED, f)
        env = mock.patch.dict(os.environ, {"MECH_TEST_STUB": stub, "STUB_LOG": self.log, "STUB_LIST": listing})
        env.start()
        self.addCleanup(env.stop)

    def test_the_command_timeout_and_project_dir_reach_the_tool(self):
        r = _kit.run_cli(["mutants", "--repo", self.repo, "--base", "HEAD~1", "--head", "HEAD", "--stack", "rust",
                          "--project-dir", "crate", "--mutants-cmd", "cargo mutants --no-shuffle",
                          "--mutant-timeout", "7"])
        self.assertIn(r.returncode, (0, 1), r.stderr)
        with open(self.log) as f:
            runs = [a for a in map(json.loads, f) if "--output" in a]
        self.assertEqual(len(runs), 1, runs)
        argv = runs[0]
        self.assertIn("--no-shuffle", argv)
        self.assertEqual(argv[argv.index("--timeout") + 1], "7")
        self.assertNotEqual(json.loads(r.stdout)["checks"]["R3"]["status"], "n/a", r.stdout)  # the crate dir was found


del Case
