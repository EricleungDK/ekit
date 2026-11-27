"""R0's editing rules judge a removal like an edit (#24, the owner's decision on F2): a base plan entry that leaves a
folder where head entries stay is compared with each of them, by the twin rule's three comparisons (target OS, a
looser limit, the mutation tool); any difference is a person's call. A base entry is kept when a head entry takes it
as its twin (same folder and `adapter`, a path normalised). A removal that leaves the folder with no entry is the drift
check's business, and one whose remaining entries agree on all three needs no person: so the migration flow (retiring
+ current, then the retiring entry removed) needs a person only when the two differ. Every call goes through cli.main
(`r0 --stack python`) in this process."""
import json
import os
import unittest

import _kit
from test_stack_plan import Repo

PLAN = ".ekit/stack-plan.toml"
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "adapters")
AD, RUN = ".ekit/adapters/mini.toml", ".ekit/adapters/minirun.toml"


def entry(name, folder, adapter, status, tos=None):
    return (f'[[stack]]\nname = "{name}"\nfolder = "{folder}"\nadapter = "{adapter}"\nstatus = "{status}"\n'
            + (f'target-os = "{tos}"\n' if tos else "") + "\n")


def fixture(name, limits=""):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read() + (f"\n[limits]\n{limits}" if limits else "")


class Departed(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)

    def people(self, base, head):
        mb, h = self.repo.commit(base), self.repo.commit(head)
        r = _kit.run_cli(["r0", "--repo", self.repo.path, "--base", mb, "--head", h, "--stack", "python"])
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return [e["problem"] for e in json.loads(r.stdout)["entries"] if e["class"] == "needs-human"]

    def one(self, base, head, want):
        got = self.people(base, head)
        self.assertEqual(len(got), 1, got)
        self.assertIn(want, got[0])

    def test_a_removal_that_moves_the_runner_needs_a_person(self):
        """F2: two python entries for `.`, the linux one dropped: windows runs after the merge"""
        self.one({PLAN: entry("a", ".", "python", "current") + entry("b", ".", "python", "retiring", "windows")},
                 {PLAN: entry("b", ".", "python", "retiring", "windows")},
                 "stack `a` leaves folder `.`: stack `b` target-os linux -> windows in .ekit/stack-plan.toml")

    def test_a_departed_entry_is_compared_with_every_entry_left(self):
        """the windows entry is the second one left, beside a ts entry on linux"""
        self.one({PLAN: entry("a", ".", "python", "current") + entry("b", ".", "python", "retiring", "windows")
                  + entry("c", ".", "ts", "current")},
                 {PLAN: entry("c", ".", "ts", "current") + entry("b", ".", "python", "retiring", "windows")},
                 "stack `a` leaves folder `.`: stack `b` target-os linux -> windows")

    def test_every_departed_entry_is_compared(self):
        """two entries leave; the second one, on windows, is the one that differs from what is left"""
        self.one({PLAN: entry("x", ".", "python", "current") + entry("y", ".", "ts", "current", "windows")
                  + entry("k", ".", "rust", "current")},
                 {PLAN: entry("k", ".", "rust", "current")},
                 "stack `y` leaves folder `.`: stack `k` target-os windows -> linux")

    def test_a_target_os_its_adapter_file_sets_counts(self):
        """the entry left runs on windows by its adapter file's `target-os`, not the plan's"""
        windows = fixture("mini.toml").replace('name = "mini"\n', 'name = "mini"\ntarget-os = "windows"\n')
        self.one({AD: windows, PLAN: entry("old", ".", "python", "retiring") + entry("new", ".", AD, "current")},
                 {PLAN: entry("new", ".", AD, "current")},
                 "stack `old` leaves folder `.`: stack `new` target-os linux -> windows")

    def test_a_removal_that_leaves_a_looser_limit_needs_a_person(self):
        self.one({AD: fixture("mini.toml", "max-mutants = 10\n"),
                  PLAN: entry("old", ".", "python", "retiring") + entry("new", ".", AD, "current")},
                 {PLAN: entry("new", ".", AD, "current")},
                 "`limits.max-mutants` 40 -> 10 for the stack `new` in folder `.` in place of `old` "
                 "(.ekit/adapters/mini.toml)")

    def test_a_removal_that_leaves_another_mutation_tool_needs_a_person(self):
        self.one({AD: fixture("mini.toml"), RUN: fixture("minirun.toml"),
                  PLAN: entry("old", ".", RUN, "retiring") + entry("new", ".", AD, "current")},
                 {PLAN: entry("new", ".", AD, "current")},
                 "[mutation.tool] of the stack `new` in folder `.`, in place of `old`, changed (.ekit/adapters/mini.toml)")

    def test_the_agreeing_migration_needs_no_person(self):
        """retiring python, current mini (linux, the default limits, no tool), then the retiring one removed"""
        self.assertEqual(self.people({AD: fixture("mini.toml"),
                                      PLAN: entry("old", ".", "python", "retiring") + entry("new", ".", AD, "current")},
                                     {PLAN: entry("new", ".", AD, "current")}), [])

    def test_a_respelled_path_is_kept_not_departed(self):
        """`./.ekit/adapters/mini.toml` at head is the base's entry: nothing left, so nothing compared with python"""
        base = {AD: fixture("mini.toml", "max-mutants = 60\n"),
                PLAN: entry("m", ".", AD, "current") + entry("p", ".", "python", "current")}
        self.assertEqual(self.people(base, {PLAN: entry("m", ".", "./" + AD, "current")
                                            + entry("p", ".", "python", "current")}), [])

    def test_removing_a_folders_only_entry_is_the_drift_checks(self):
        self.assertEqual(self.people({PLAN: entry("a", ".", "python", "current", "windows")
                                      + entry("w", "web", "ts", "current")},
                                     {PLAN: entry("w", "web", "ts", "current")}), [])


if __name__ == "__main__":
    unittest.main()
