"""R3 through the repo's own adapter file (#19 with #17/#18): plan, baseline, mutants and merge on a stack the repo
defines (.ekit/adapters/<name>.toml, or a plan entry's file), read at the PR's base, run its [mutation.tool]; a repo file
named like a built-in drives R3 when it declares a tool. Through cli.main in this process; the tool is the stub of
test_adapter_mutation_cli."""
import json
import os
import tempfile
import unittest
from unittest import mock

import _kit
from test_adapter_mutation_cli import BASE_SRC, ELEMENTS, FX, HEAD_SRC, STUB, TEST
from test_stack_plan import PLAN, Repo, mini, plan


class RepoTool(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = os.path.join(tmp.name, "calls.log")
        open(self.log, "w").close()
        self.stub = os.path.join(tmp.name, "stub.py")
        with open(self.stub, "w") as f:
            f.write(STUB)
        os.chmod(self.stub, 0o755)
        self.tmp = tmp.name
        self.bin = os.path.join(tmp.name, "bin")  # the tool on PATH, as setup-command installs it
        os.makedirs(self.bin)
        os.symlink(self.stub, os.path.join(self.bin, "mut"))

    def cli(self, check, base, head, *extra, stack="mini", to="out/report.json"):
        env = {"MECH_TEST_STUB": self.stub, "STUB_LOG": self.log, "STUB_REPORT": os.path.join(FX, "elements.json"),
               "STUB_TO": to, "PATH": self.bin + os.pathsep + os.environ["PATH"]}
        with mock.patch.dict(os.environ, env):
            r = _kit.run_cli([check, "--repo", self.repo.path, "--base", base, "--head", head, "--stack", stack,
                              "--test-paths", "tests/**", *extra])
        return r, (json.loads(r.stdout) if r.stdout else None)

    def pr(self, files, head=None):
        base = self.repo.commit(files)
        return base, self.repo.commit(head or {"src/calc.mini": HEAD_SRC})

    def named(self):
        return self.pr({"mini.json": "{}", "src/calc.mini": BASE_SRC, "tests/calc.mini": TEST,
                        ".ekit/adapters/mini.toml": mini() + ELEMENTS})

    def test_mutants_on_a_repo_stack_runs_its_declared_tool(self):
        base, head = self.named()
        r, env = self.cli("mutants", base, head)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual([(e["line"], e["problem"]) for e in env["entries"]], [
            (2, "MISSED mutant src/calc.mini:2: ArithmeticOperator `a + b` -> `a - b`"),
            (6, "MISSED mutant src/calc.mini:6: EqualityOperator `n > 0` -> `n >= 0`")])
        self.assertNotIn("notes", env)

    def test_the_base_files_tool_judges_not_the_prs(self):
        base, _ = self.named()
        head = self.repo.commit({"src/calc.mini": HEAD_SRC, ".ekit/adapters/mini.toml": mini()})  # the PR drops the tool
        r, env = self.cli("mutants", base, head)
        self.assertEqual((r.returncode, len(env["entries"])), (1, 2), r.stderr)

    def test_plan_and_baseline_read_the_files_production_files(self):
        base, head = self.named()
        r, env = self.cli("plan", base, head)
        self.assertEqual((r.returncode, env), (0, {"run": True}), r.stderr)
        r, env = self.cli("baseline", base, head)
        self.assertEqual((r.returncode, env["run"], env["count"], env["checks"]["R3"]),
                         (0, True, 1, {"status": "skipped", "note": "1 changed production file(s) in 1 shard(s)"}))
        docs = self.repo.commit({"README.md": "docs\n"})
        r, env = self.cli("plan", head, docs)
        self.assertEqual((r.returncode, env), (0, {"run": False}), r.stderr)

    def test_a_plan_entrys_file_drives_r3_in_its_folder(self):
        base, head = self.pr({"lib/mini.json": "{}", "lib/src/calc.mini": BASE_SRC, "build/m.toml": mini() + ELEMENTS,
                              PLAN: plan(("lib", "lib", "build/m.toml", "current"))},
                             {"lib/src/calc.mini": HEAD_SRC})
        r, env = self.cli("mutants", base, head, "--project-dir", "lib")
        self.assertEqual([e["file"] for e in env["entries"]], ["lib/src/calc.mini"] * 2, r.stderr)

    def test_an_override_with_a_tool_drives_r3_and_one_without_keeps_the_built_in(self):
        ts = mini().replace('name = "mini"', 'name = "ts"').replace('manifests = ["mini.json"]',
                                                                       'manifests = ["package.json"]')
        files = {"package.json": "{}", "src/calc.mini": BASE_SRC, "tests/calc.mini": TEST}
        base, head = self.pr(dict(files, **{".ekit/adapters/ts.toml": ts + ELEMENTS}))
        r, env = self.cli("mutants", base, head, stack="ts")
        self.assertEqual((r.returncode, len(env["entries"])), (1, 2), r.stderr)  # .mini files: the file's, not ts's
        base, head = self.pr(dict(files, **{".ekit/adapters/ts.toml": ts}))
        r, env = self.cli("mutants", base, head, stack="ts")
        self.assertEqual((r.returncode, env["checks"]["R3"]["status"]), (0, "skipped"), r.stderr)  # the built-in's

    def test_merge_combines_a_repo_stacks_baseline_and_shard(self):
        base, head = self.named()
        _, b = self.cli("baseline", base, head)
        _, m = self.cli("mutants", base, head, "--shard", "0/1")
        paths = {}
        for k, doc in (("baseline", b), ("shard", m)):
            paths[k] = os.path.join(self.tmp, k + ".json")
            with open(paths[k], "w") as f:
                json.dump(doc, f)
        r = _kit.run_cli(["merge", "--repo", self.tmp, "--base", b["base"], "--head", b["head"], "--stack", "mini",
                          "--shards", "1", "--baseline", paths["baseline"], "--envelope", "0=" + paths["shard"]])
        env = json.loads(r.stdout)
        self.assertEqual((r.returncode, env["checks"]["R3"]["status"], [e["id"] for e in env["entries"]]),
                         (1, "fail", [e["id"] for e in m["entries"]]), r.stderr)


    def test_a_pr_cannot_supply_the_program_that_judges_it(self):  # review F1 (the reviewer's probe p5)
        fake = "#!/bin/sh\nmkdir -p out; echo '{\"files\": {}}' > out/report.json\n"
        base = self.repo.commit({"mini.json": "{}", "src/calc.mini": BASE_SRC, "tests/calc.mini": TEST,
                                 ".ekit/adapters/mini.toml": mini() + ELEMENTS.replace('command = "mut"',
                                                                                       'command = "tools/mut"')})
        head = self.repo.commit({"src/calc.mini": HEAD_SRC, "tools/mut": fake})
        r, env = self.cli("mutants", base, head)
        self.assertEqual((r.returncode, env), (2, None))
        self.assertIn("mutation.tool.command: `tools/mut` is a path in the project dir", r.stderr)
        with open(self.log) as f:
            self.assertEqual(f.read(), "")

    def test_the_plan_entrys_target_os_decides_whether_the_tool_runs(self):  # review F4 (probe p3)
        base, head = self.pr({"lib/mini.json": "{}", "lib/src/calc.mini": BASE_SRC, "build/m.toml": mini() + ELEMENTS,
                              PLAN: plan(("lib", "lib", "build/m.toml", "current", "windows"))},
                             {"lib/src/calc.mini": HEAD_SRC})
        r, env = self.cli("mutants", base, head, "--project-dir", "lib")
        self.assertEqual((r.returncode, env["checks"]["R3"]), (0, {
            "status": "n/a", "note": "mut does not run on windows (env): mutation.tool.os lists linux, macos; the "
                                     "stack's target-os is windows"}), r.stderr)
        r, env = self.cli("baseline", base, head, "--project-dir", "lib")
        self.assertEqual(env["checks"]["R3"]["status"], "skipped")  # git only: the shards say n/a


class ToolEditsNeedAPerson(unittest.TestCase):
    """review F6: R0's editing rules give the needs-human entry for a PR that changes [mutation.tool] (adds, removes or
    edits it): after the merge every later PR's R3 runs the new tool, or none."""

    def problems(self, base_tool, head_tool, plan_file=True):
        from scripts.mech_review import r0 as r0_mod
        repo = Repo(self)
        where = "build/m.toml" if plan_file else ".ekit/adapters/mini.toml"
        extra = {PLAN: plan(("lib", "lib", where, "current"))} if plan_file else {}
        mb = repo.commit(dict(extra, **{"lib/mini.json": "{}", where: mini() + base_tool}))
        head = repo.commit({where: mini() + head_tool})
        return [e["problem"] for e in r0_mod.editing(repo.path, mb, head, [] if plan_file else [where])]

    def test_each_change_of_the_tool_is_named(self):
        narrow = ELEMENTS.replace('os = ["linux", "macos"]', 'os = ["macos"]')
        other = ELEMENTS.replace('command = "mut"', 'command = "mut2"')
        for base_tool, head_tool in ((ELEMENTS, ""), ("", ELEMENTS), (ELEMENTS, narrow), (ELEMENTS, other)):
            with self.subTest(head_tool[:40]):
                self.assertEqual(self.problems(base_tool, head_tool), [
                    "a person decides: [mutation.tool] of the stack in folder `lib` changed (build/m.toml)"])
                self.assertEqual(self.problems(base_tool, head_tool, plan_file=False), [
                    "a person decides: adapter file .ekit/adapters/mini.toml: [mutation.tool] changed"])

    def test_an_unchanged_tool_needs_no_one(self):
        self.assertEqual(self.problems(ELEMENTS, ELEMENTS), [])
        self.assertEqual(self.problems(ELEMENTS, ELEMENTS.replace("os = ", "# the OSes\nos = ")), [])


if __name__ == "__main__":
    unittest.main()
