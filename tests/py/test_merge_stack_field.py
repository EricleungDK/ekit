"""`merge` checks which stack each result ran for (#62): every `mutants` result names its stack and project dir, and
`merge --stack S [--project-dir D]` counts only this leg's results. A result for another stack or folder, or one with
no stack field or a malformed one, is one CI `fail` entry naming it (its stack and its shard), never counted; #42's
shard checks keep applying to the leg's own results. Through `cli.main([...])` in this process.

The results are real `mutants` envelopes from cli.main, run with a mutation tool that is not installed (R3 n/a)."""
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from test_adapter_cli import MINI, Repo
from test_merge_shards import NO_TOOL, call

PY = {"pyproject.toml": "[project]\nname = 'x'\n", "calc.py": "def add(a, b):\n    return a + b\n",
      "tests/test_calc.py": "import calc\n\n\ndef test_add():\n    assert calc.add(1, 2) == 3\n"}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(os.path.join(self.tmp.name, "r"))
        base = dict(PY, **{f"api/{k}": v for k, v in PY.items()}, **{f"web/{k}": v for k, v in PY.items()},
                    **{"web/mini.json": "{}", "web/src/calc.mini": "fn add(a, b) {\n  a+b\n}\n"})
        self.base = self.repo.commit(base, "base")
        self.head = self.repo.commit({"calc.py": "def add(a, b):\n    return b + a\n",
                                      "api/calc.py": "def add(a, b):\n    return b + a\n",
                                      "web/calc.py": "def add(a, b):\n    return b + a\n",
                                      "web/src/calc.mini": "fn add(a, b) {\n  b+a\n}\n"}, "head")

    def tearDown(self):
        self.tmp.cleanup()

    def mutants(self, shard="0/1", *extra, stack="python"):
        rc, out, err = call(["mutants", "--repo", self.repo.path, "--base", self.base, "--head", self.head,
                             "--stack", stack, "--test-paths", "tests/**", "--test-paths", "*/tests/**",
                             "--mutants-cmd", NO_TOOL, "--shard", shard, *extra])
        self.assertEqual(rc, 0, err)
        return json.loads(out)


class MutantsNamesItsStack(Case):
    def test_a_built_in_stacks_result_names_the_stack_and_the_project_dir(self):
        self.assertEqual(self.mutants("0/2")["stack"], {"stack": "python", "project_dir": "."})
        self.assertEqual(self.mutants("1/2", "--project-dir", "api/")["stack"], {"stack": "python", "project_dir": "api"})

    def test_an_adapter_files_result_names_the_stack_and_the_project_dir(self):
        env = self.mutants("0/1", "--adapter", MINI, "--project-dir", "web", stack="mini")
        self.assertEqual(env["checks"]["R3"]["status"], "n/a")
        self.assertEqual(env["stack"], {"stack": "mini", "project_dir": "web"})


class MergeCountsOnlyItsLeg(Case):
    def save(self, name, env):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w") as f:
            json.dump(env, f)
        return path

    def merge(self, n, *envelopes, stack="python", project_dir=None):
        argv = ["merge", "--repo", self.repo.path, "--base", self.base, "--head", self.head, "--stack", stack,
                "--shards", str(n)] + (["--project-dir", project_dir] if project_dir is not None else [])
        for k, env in enumerate(envelopes):
            argv += ["--envelope", f"{k}={self.save(f'e{k}.json', env)}"]
        rc, out, err = call(argv)
        env = json.loads(out)
        return rc, env, [e for e in env["entries"] if e["check"] == "CI"]

    def test_a_result_for_another_stack_is_one_ci_fail_entry_naming_its_stack_and_shard(self):
        rc, env, ci = self.merge(2, self.mutants("0/2"), self.mutants("1/2", stack="rust"))
        self.assertEqual(rc, 1)
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertEqual([(e["severity"], e["problem"]) for e in ci],
                         [("fail", "mutants shard 1/2 produced no result: result is for stack rust in ., not python")])

    def test_a_result_for_another_folder_of_the_stack_is_one_ci_fail_entry_when_the_leg_names_its_folder(self):
        rc, env, ci = self.merge(2, self.mutants("0/2", "--project-dir", "api"),
                                 self.mutants("1/2", "--project-dir", "web"), project_dir="api")
        self.assertEqual(rc, 1)
        self.assertEqual([(e["severity"], e["problem"]) for e in ci],
                         [("fail", "mutants shard 1/2 produced no result: result is for stack python in web, "
                                   "not python in api")])

    def test_the_legs_own_folder_merges_clean(self):
        rc, env, ci = self.merge(2, self.mutants("0/2", "--project-dir", "api"),
                                 self.mutants("1/2", "--project-dir", "api"), project_dir="api")
        self.assertEqual((rc, ci, env["checks"]["R3"]["status"]), (0, [], "n/a"))

    def test_with_no_project_dir_given_the_stack_alone_is_compared(self):
        rc, env, ci = self.merge(2, self.mutants("0/2", "--project-dir", "api"), self.mutants("1/2", "--project-dir", "web"))
        self.assertEqual((rc, ci), (0, []))

    def test_the_shard_checks_apply_to_the_legs_results_only(self):
        # shard 0/2 of python and shard 0/2 of rust: not one shard given twice, but one result of another stack
        rc, env, ci = self.merge(2, self.mutants("0/2"), self.mutants("0/2", stack="rust"))
        self.assertEqual(rc, 1)
        self.assertEqual([e["problem"] for e in ci],
                         ["mutants shard 1/2 produced no result: result is for stack rust in ., not python"])

    def test_a_shard_given_twice_within_the_leg_is_still_the_shards_mismatch_entry(self):
        s0 = self.mutants("0/2")
        rc, env, ci = self.merge(2, s0, s0, project_dir=".")
        self.assertEqual(rc, 1)
        self.assertEqual([e["problem"] for e in ci],
                         ["mutants shards do not match: shard 0/2 given 2 times (--envelope 0, 1); shard 1/2 missing"])

    def test_a_result_with_no_stack_field_beside_ones_that_carry_it_is_named_and_not_counted(self):
        s1 = self.mutants("1/2")
        del s1["stack"]
        rc, env, ci = self.merge(2, self.mutants("0/2"), s1)
        self.assertEqual(rc, 1)
        self.assertEqual([(e["severity"], e["problem"]) for e in ci],
                         [("fail", "mutants shard 1/2 produced no result: result has no stack field")])

    def test_a_malformed_stack_field_is_named_and_not_counted_never_a_crash(self):
        for bad in ({"stack": 1, "project_dir": "."}, {"stack": "python"}, {"stack": "python", "project_dir": None},
                    "python", ["python", "."], None, {"stack": "", "project_dir": ""}, {"stack": "python", "project_dir": ""},
                    {"stack": "", "project_dir": "."}):
            s1 = dict(self.mutants("1/2"), stack=bad)
            rc, env, ci = self.merge(2, self.mutants("0/2"), s1)
            self.assertEqual(rc, 1, bad)
            self.assertEqual([e["problem"] for e in ci],
                             ["mutants shard 1/2 produced no result: result has a malformed stack field "
                              + json.dumps(bad)], bad)

    def test_results_none_of_which_has_a_stack_field_are_each_named_and_not_counted(self):
        s0, s1 = self.mutants("0/2"), self.mutants("1/2")
        del s0["stack"], s1["stack"]
        rc, env, ci = self.merge(2, s0, s1)
        self.assertEqual(rc, 1)
        self.assertEqual(sorted(e["problem"] for e in ci),  # entries sort by id
                         ["mutants shard 0/2 produced no result: result has no stack field",
                          "mutants shard 1/2 produced no result: result has no stack field"])

    def test_a_lone_result_of_another_stack_with_its_stack_field_dropped_is_not_counted(self):
        s0 = self.mutants("0/1", stack="rust")
        del s0["stack"]
        rc, env, ci = self.merge(1, s0)
        self.assertEqual((rc, env["checks"]["R3"]["status"]), (1, "fail"))
        self.assertEqual([e["problem"] for e in ci], ["mutants shard 0/1 produced no result: result has no stack field"])


if __name__ == "__main__":
    unittest.main()
