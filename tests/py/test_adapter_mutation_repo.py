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

    def cli(self, check, base, head, *extra, stack="mini", to="out/report.json"):
        env = {"MECH_TEST_STUB": self.stub, "STUB_LOG": self.log, "STUB_REPORT": os.path.join(FX, "elements.json"),
               "STUB_TO": to}
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


if __name__ == "__main__":
    unittest.main()
