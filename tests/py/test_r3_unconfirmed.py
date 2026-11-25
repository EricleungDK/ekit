"""#79: a mutant mutmut reports surviving whose whole-suite retry did not run is an unconfirmed survivor: one R3 confirm
entry per mutant, named by file, line and mutation, out of the tested count. The partial entry names its cause.

The engine's command line in this process (`_kit.run_cli`), the R3 runner the scripted mutmut of test_mutmut_run on a
clock of its own: each command takes its cost in seconds, and one that needs more than the budget it is given ends as
`timeout` once that budget is spent, as the default runner reads a run it stopped. The repo is DiffOfSub's: its diff
changes `sub` (lines 6 and 7), whose two mutants are SUB1 (`c = a - b -> c = a + b`) and SUB2 (`return c -> return
None`)."""
import json
import os
import types
import unittest
from unittest import mock

import _kit
from scripts.mech_review import mutants
from test_mutmut_run import EDITS, SUB1, SUB2, DiffOfSub, FakeMutmut, git

PARTIAL_ID = "R3-d101585d"  # the partial entry's id before #79 (docs/mech-review-ci.md: stable across heads and counts)
M1, M2 = "c = a - b -> c = a + b", "return c -> return None"
# the MISSED ids of M1 and M2 in calc.py, as before #79: an unconfirmed survivor of the same mutation has the same id
M1_ID, M2_ID = "R3-5e6e619d", "R3-3e4ebc79"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


class Timed(FakeMutmut):
    """FakeMutmut whose commands take time: costs {"list": mutmut's listing, "run": its run of the mutants, "suite":
    one whole-suite run}; the rest take none. A mutmut run cut by its budget has run the first of its mutants."""

    def __init__(self, statuses, clock, costs, **kw):
        super().__init__(statuses, edits=EDITS, **kw)
        self.clock, self.costs = clock, costs

    def cost(self, argv):
        if argv[0] == "python3":
            return self.costs["suite"]
        if argv[1] == "run":
            return self.costs["list" if argv[2:] == [mutants.LIST_ONLY] else "run"]
        return 0

    def __call__(self, argv, cwd, timeout):
        need = self.cost(argv)
        if timeout is not None and need > timeout:
            self.clock.now += timeout
            if argv[0] == "python3":
                return "timeout", ""
            self.timeout_run = len(self.runs) + 1  # FakeMutmut's own budget end: the first mutant ran
            return super().__call__(argv, cwd, timeout)
        self.clock.now += need
        return super().__call__(argv, cwd, timeout)


def mutation(e):
    """(file, line, mutation) an R3 entry names: what a test has to kill."""
    return e["file"], e["line"], e["problem"].split(": ", 1)[1]


class Cli(DiffOfSub):
    def mutants_cli(self, fake, budget_min, *extra):
        clock = fake.clock
        with mock.patch.object(mutants, "default_runner", lambda: fake), \
                mock.patch.object(mutants, "time", types.SimpleNamespace(monotonic=clock.monotonic)):
            r = _kit.run_cli(["mutants", "--repo", self.repo, "--base", "HEAD~1", "--head", "HEAD", "--stack", "python",
                              "--test-paths", "tests/**", "--mutation-budget", str(budget_min), *extra])
        self.assertIn(r.returncode, (0, 1), r.stderr)
        env = json.loads(r.stdout)
        return env, r.returncode

    def fake(self, statuses, list_s=1, run_s=1, suite_s=1, **kw):
        return Timed(statuses, Clock(), {"list": list_s, "run": run_s, "suite": suite_s}, **kw)

    @staticmethod
    def unconfirmed(env):
        return [e for e in env["entries"] if e.get("unconfirmed") is True]

    @staticmethod
    def partial(env):
        return [e for e in env["entries"] if e["id"] == PARTIAL_ID]


class TestUnconfirmedSurvivors(Cli):
    def test_no_budget_left_for_the_retry_names_each_survivor(self):
        # 60 s: the listing and mutmut's run take all of it, so no whole-suite retry is reached
        fake = self.fake({SUB1: "survived", SUB2: "no tests"}, list_s=30, run_s=30, suite_fails_on=["c = a + b"])
        env, rc = self.mutants_cli(fake, 1)
        self.assertEqual((rc, fake.suite_runs), (0, []))
        r3 = env["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"], r3["total"]), ("partial", 0, 2))
        got = self.unconfirmed(env)
        self.assertEqual([mutation(e) for e in got], [("calc.py", 6, M1), ("calc.py", 7, M2)])
        self.assertEqual([(e["check"], e["class"], e["severity"], e["problem"]) for e in got],
                         [("R3", "agent-fixable", "confirm", f"R3 unconfirmed survivor calc.py:6: {M1}"),
                          ("R3", "agent-fixable", "confirm", f"R3 unconfirmed survivor calc.py:7: {M2}")])
        self.assertEqual([e for e in env["entries"] if e["severity"] == "fail"], [])

    def test_a_retry_the_budget_cuts_short_is_an_unconfirmed_survivor(self):
        # 60 s: 40 for mutmut, 15 for the clean suite run, then 5 left for a retry that takes 15
        fake = self.fake({SUB1: "survived", SUB2: "killed"}, list_s=20, run_s=20, suite_s=15)
        env, rc = self.mutants_cli(fake, 1)
        self.assertEqual((rc, len(fake.suite_runs), fake.applied), (0, 1, [SUB1]))  # the clean run only ends
        self.assertEqual((env["checks"]["R3"]["status"], env["checks"]["R3"]["tested"]), ("partial", 1))
        self.assertEqual([mutation(e) for e in self.unconfirmed(env)], [("calc.py", 6, M1)])

    def test_a_mutmut_run_the_budget_ends_names_its_survivors_and_counts_the_mutants_it_never_ran(self):
        statuses = {SUB1: "survived", SUB2: "survived"}
        ample, _ = self.mutants_cli(self.fake(statuses, list_s=20, run_s=100), 10)
        self.assertEqual([(e["id"], e["severity"], mutation(e)) for e in ample["entries"]],
                         [(M1_ID, "fail", ("calc.py", 6, M1)), (M2_ID, "fail", ("calc.py", 7, M2))])
        # 1 minute: mutmut's run is stopped after the first mutant; the second never ran, so it is not named
        short, _ = self.mutants_cli(self.fake(statuses, list_s=20, run_s=100), 1)
        self.assertEqual([(e["id"], mutation(e)) for e in self.unconfirmed(short)], [(M1_ID, ("calc.py", 6, M1))])
        self.assertEqual([e["problem"] for e in self.partial(short)],
                         ["R3 partial: 2/2 mutants untested: budget hit; 1 unconfirmed survivor"])

    def test_survivors_of_a_mutmut_run_the_budget_ends_are_unconfirmed_survivors(self):
        # mutmut's run needs 100 s of the 40 left: it is stopped after the first mutant, which survived
        fake = self.fake({SUB1: "survived", SUB2: "survived"}, list_s=20, run_s=100)
        env, rc = self.mutants_cli(fake, 1)
        self.assertEqual((rc, fake.suite_runs), (0, []))
        r3 = env["checks"]["R3"]
        self.assertEqual((r3["status"], r3["tested"]), ("partial", 0))
        self.assertEqual([mutation(e) for e in self.unconfirmed(env)], [("calc.py", 6, M1)])

    def test_control_every_survivor_confirmed_or_caught_leaves_no_unconfirmed_entry(self):
        fake = self.fake({SUB1: "survived", SUB2: "survived"}, suite_fails_on=["c = a + b"])
        env, rc = self.mutants_cli(fake, 10)
        self.assertEqual((rc, env["checks"]["R3"]["status"], env["checks"]["R3"]["tested"]), (1, "fail", 2))
        self.assertEqual(self.unconfirmed(env), [])
        self.assertEqual([mutation(e) for e in env["entries"]], [("calc.py", 7, M2)])
        caught = self.fake({SUB1: "survived", SUB2: "killed"}, suite_fails_on=["c = a + b"])
        env, rc = self.mutants_cli(caught, 10)
        self.assertEqual((rc, env["checks"]["R3"]["status"], env["entries"]), (0, "pass", []))

    def test_the_same_mutants_are_reported_whatever_the_budget(self):
        statuses = {SUB1: "survived", SUB2: "no tests"}
        ample, _ = self.mutants_cli(self.fake(statuses, list_s=30, run_s=30), 10)
        short, _ = self.mutants_cli(self.fake(statuses, list_s=30, run_s=30), 1)
        confirmed = [mutation(e) for e in ample["entries"] if e["severity"] == "fail"]
        unconfirmed = [mutation(e) for e in self.unconfirmed(short)]
        self.assertEqual((len(confirmed), self.unconfirmed(ample)), (2, []))
        self.assertEqual(sorted(confirmed), sorted(unconfirmed))

    def test_an_unconfirmed_survivor_has_the_id_a_missed_one_of_its_mutation_has(self):
        # a fast machine confirms both survivors MISSED, a slow one leaves them unconfirmed: a waiver carries over
        statuses = {SUB1: "survived", SUB2: "no tests"}
        fast, _ = self.mutants_cli(self.fake(statuses, list_s=30, run_s=30), 10)
        slow, _ = self.mutants_cli(self.fake(statuses, list_s=30, run_s=30), 1)
        self.assertEqual([(e["id"], e["severity"], mutation(e)) for e in fast["entries"]],
                         [(M1_ID, "fail", ("calc.py", 6, M1)), (M2_ID, "fail", ("calc.py", 7, M2))])
        self.assertEqual([(e["id"], mutation(e)) for e in self.unconfirmed(slow)],
                         [(M1_ID, ("calc.py", 6, M1)), (M2_ID, ("calc.py", 7, M2))])

    def test_the_id_is_stable_across_heads_for_the_same_mutation(self):
        statuses = {SUB1: "survived", SUB2: "no tests"}
        first, _ = self.mutants_cli(self.fake(statuses, list_s=30, run_s=30), 1)
        with open(os.path.join(self.repo, "calc.py")) as f:
            head = f.read()
        with open(os.path.join(self.repo, "calc.py"), "w") as f:
            f.write("# calc\n" + head)  # every line of `sub` moves down one
        git(self.repo, "commit", "-q", "--amend", "-am", "head")
        second, _ = self.mutants_cli(self.fake(statuses, list_s=30, run_s=30), 1)
        self.assertEqual([e["line"] for e in self.unconfirmed(second)], [7, 8])
        self.assertEqual([e["id"] for e in self.unconfirmed(first)], [e["id"] for e in self.unconfirmed(second)])


class TestPartialCause(Cli):
    @staticmethod
    def save(out, name, env):
        with open(os.path.join(out, name + ".json"), "w") as f:
            json.dump(env, f)

    def test_unconfirmed_survivors_and_the_budget_are_named_with_the_budget_hint(self):
        fake = self.fake({SUB1: "survived", SUB2: "no tests"}, list_s=30, run_s=30)
        env, _ = self.mutants_cli(fake, 1)
        (p,) = self.partial(env)
        self.assertEqual(p["problem"], "R3 partial: 2/2 mutants untested: budget hit; 2 unconfirmed survivors")
        self.assertIn("raise mutation-budget", p["hint"])
        self.assertIn("unconfirmed survivor", p["hint"])

    def test_the_cap_alone_names_the_cap_and_no_budget_hint(self):
        fake = self.fake({SUB1: "killed", SUB2: "killed"})
        env, rc = self.mutants_cli(fake, 10, "--max-mutants", "1")
        self.assertEqual((rc, env["checks"]["R3"]["status"]), (0, "partial"))
        (p,) = self.partial(env)
        self.assertEqual(p["problem"], "R3 partial: 1/2 mutants untested: past the cap")
        self.assertNotIn("mutation-budget", p["hint"])
        self.assertIn("max-mutants", p["hint"])

    def test_the_budget_alone_names_the_budget(self):
        # mutmut's run is stopped after the first mutant, which was caught
        fake = self.fake({SUB1: "killed", SUB2: "killed"}, list_s=20, run_s=100)
        env, _ = self.mutants_cli(fake, 1)
        (p,) = self.partial(env)
        self.assertEqual(p["problem"], "R3 partial: 1/2 mutants untested: budget hit")
        self.assertIn("raise mutation-budget", p["hint"])

    def test_the_merged_partial_entry_names_every_shards_cause(self):
        out = os.path.join(self.repo, ".git", "out")
        os.makedirs(out)
        short = self.fake({SUB1: "survived", SUB2: "no tests"}, list_s=30, run_s=30)
        self.save(out, "0", self.mutants_cli(short, 1, "--shard", "0/2", "--max-mutants", "1")[0])
        ample = self.fake({SUB1: "killed", SUB2: "killed"})
        self.save(out, "1", self.mutants_cli(ample, 10, "--shard", "1/2", "--max-mutants", "1")[0])
        r = _kit.run_cli(["merge", "--repo", self.repo, "--base", "HEAD~1", "--head", "HEAD", "--stack", "python",
                          "--shards", "2", "--envelope", f"0={out}/0.json", "--envelope", f"1={out}/1.json"])
        self.assertEqual(r.returncode, 0, r.stderr)
        merged = json.loads(r.stdout)
        (p,) = self.partial(merged)
        self.assertEqual(p["problem"],
                         "R3 partial: 2/2 mutants untested: past the cap; budget hit; 1 unconfirmed survivor")
        # the cap of 1 keeps the first mutant (the fake writes no mutmut copies to rank by: one class, by number)
        self.assertEqual([mutation(e) for e in self.unconfirmed(merged)], [("calc.py", 6, M1)])


if __name__ == "__main__":
    unittest.main()
