"""`merge` checks which shard each result came from (#42): a shard given twice, a shard index missing for --shards, or
shards that disagree on head, base or cap give one CI entry, through `cli.main(["merge", ...])`.

The shard results are real `mutants` envelopes from cli.main, run with a mutation tool that is not installed (R3 n/a):
each carries the shard it ran as and its cap, which is what merge checks."""
import contextlib
import io
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import cli
from test_adapter_cli import Repo

NO_TOOL = "no-such-mutation-tool-42"


def call(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = cli.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


class MergeShards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(os.path.join(self.tmp.name, "r"))
        self.base = self.repo.commit({"pyproject.toml": "[project]\nname = 'x'\n", "calc.py": "def add(a, b):\n    return a + b\n",
                                      "tests/test_calc.py": "import calc\n\n\ndef test_add():\n    assert calc.add(1, 2) == 3\n"},
                                     "base")
        self.head = self.repo.commit({"calc.py": "def add(a, b):\n    return b + a\n"}, "head")

    def tearDown(self):
        self.tmp.cleanup()

    def shard(self, name, shard, cap=40, base=None):
        """the `mutants` envelope of one shard, saved to a file: its path"""
        rc, out, err = call(["mutants", "--repo", self.repo.path, "--base", base or self.base, "--head", self.head,
                             "--stack", "python", "--test-paths", "tests/**", "--mutants-cmd", NO_TOOL,
                             "--shard", shard, "--max-mutants", str(cap)])
        self.assertEqual(rc, 0, err)
        path = os.path.join(self.tmp.name, name)
        with open(path, "w") as f:
            f.write(out)
        return path

    def merge(self, n, *envelopes):
        argv = ["merge", "--repo", self.repo.path, "--base", self.base, "--head", self.head, "--stack", "python",
                "--shards", str(n)]
        for k, path in enumerate(envelopes):
            argv += ["--envelope", f"{k}={path}"]
        rc, out, err = call(argv)
        env = json.loads(out)
        return rc, env, [e for e in env["entries"] if e["check"] == "CI"]

    def test_two_good_shards_merge_with_no_ci_entry(self):
        rc, env, ci = self.merge(2, self.shard("s0", "0/2"), self.shard("s1", "1/2"))
        self.assertEqual((rc, ci), (0, []))

    def test_the_same_shard_given_twice_is_one_ci_entry(self):
        s0 = self.shard("s0", "0/2")
        rc, env, ci = self.merge(2, s0, s0)
        self.assertEqual(rc, 1)
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertEqual([(e["class"], e["severity"], e["problem"]) for e in ci],
                         [("env", "fail", "mutants shards do not match: shard 0/2 given 2 times (--envelope 0, 1); "
                                          "shard 1/2 missing")])

    def test_a_shard_index_missing_for_the_declared_count_is_one_ci_entry(self):
        rc, env, ci = self.merge(3, self.shard("s0", "0/2"), self.shard("s1", "1/2"), self.shard("s2", "1/2"))
        self.assertEqual(rc, 1)
        self.assertEqual([e["problem"] for e in ci],
                         ["mutants shards do not match: shard 0/2 ran as one of 2 shards, not 3; shard 1/2 ran as one "
                          "of 2 shards, not 3; shard 1/2 given 2 times (--envelope 1, 2); shard 0/3 missing; "
                          "shard 1/3 missing; shard 2/3 missing"])

    def test_shards_that_disagree_on_the_cap_are_one_ci_entry(self):
        rc, env, ci = self.merge(2, self.shard("s0", "0/2", cap=5), self.shard("s1", "1/2", cap=7))
        self.assertEqual(rc, 1)
        self.assertEqual([e["problem"] for e in ci], ["mutants shards do not match: shards ran with different caps "
                                                      "(max-mutants 5, 7)"])

    def test_shards_that_disagree_on_the_base_are_one_ci_entry(self):
        # shard 1 ran against another base (the PR's base moved between the jobs' runs)
        s1 = self.shard("s1", "1/2")
        with open(s1) as f:
            env = json.load(f)
        env["base"] = "c" * 40
        with open(s1, "w") as f:
            json.dump(env, f)
        rc, env, ci = self.merge(2, self.shard("s0", "0/2"), s1)
        self.assertEqual(rc, 1)
        self.assertEqual([e["problem"] for e in ci],
                         [f"mutants shards do not match: shard 1/2 ran on base {'c' * 40}, not {self.base}"])

    def test_a_shard_for_another_head_is_one_ci_entry(self):
        s1 = self.shard("s1", "1/2")
        with open(s1) as f:
            env = json.load(f)
        env["head"] = "d" * 40
        with open(s1, "w") as f:
            json.dump(env, f)
        rc, env, ci = self.merge(2, self.shard("s0", "0/2"), s1)
        self.assertEqual(rc, 1)
        self.assertEqual([e["problem"] for e in ci],
                         [f"mutants shard 1/2 produced no result: result is for an older head, not {self.head}"])


if __name__ == "__main__":
    unittest.main()
