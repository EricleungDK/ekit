"""R0's editing rules compare every plan entry, not the first one per folder (#24, review round 3). A head entry is
compared with its twin: the base entry with the same folder (normalised) and the same `adapter`; of two such, the one
with the same status; of two with none the same, each. A head entry with no twin in a folder the base has entries for
is compared with each of them: a person decides when its target OS differs, a limit is looser or its mutation tool
differs against any. A folder new to the plan compares with the defaults (linux, the default limits, no tool), so a
setup PR or a drift repair needs no person. Each call goes through r0.editing in this process."""
import os
import unittest

import _kit  # noqa: F401 - the repo root on sys.path
from scripts.mech_review import r0 as r0_mod
from test_stack_plan import Repo

PLAN = ".ekit/stack-plan.toml"
MINI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "adapters", "mini.toml")


def entry(name, folder, adapter, status, tos=None):
    return (f'[[stack]]\nname = "{name}"\nfolder = "{folder}"\nadapter = "{adapter}"\nstatus = "{status}"\n'
            + (f'target-os = "{tos}"\n' if tos else "") + "\n")


def mini(limits=""):
    with open(MINI, encoding="utf-8") as f:
        return f.read() + (f"\n[limits]\n{limits}" if limits else "")


class Twins(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)

    def problems(self, base, head):
        mb = self.repo.commit(base)
        h = self.repo.commit(head)
        return [e["problem"] for e in r0_mod.editing(self.repo.path, mb, h)]

    def test_a_decoy_entry_placed_first_hides_no_target_os_change(self):
        base = {PLAN: entry("calc", ".", "python", "current")}
        head = {PLAN: entry("decoy", ".", "python", "planned") + entry("calc", ".", "python", "current", "windows")}
        got = self.problems(base, head)
        self.assertEqual(len(got), 1, got)
        self.assertIn("stack in folder `.` target-os linux -> windows in .ekit/stack-plan.toml", got[0])

    def test_a_migration_in_progress_compares_each_leg_with_its_twin(self):
        ad = ".ekit/adapters/mini.toml"
        base = {ad: mini("max-mutants = 60\n"),
                PLAN: entry("old", ".", "python", "retiring") + entry("new", ".", ad, "current")}
        head = {ad: mini("max-mutants = 5\n")}
        got = self.problems(base, head)
        self.assertEqual(len(got), 1, got)
        self.assertIn("`limits.max-mutants` 60 -> 5 for the stack in folder `.` (.ekit/adapters/mini.toml)", got[0])

    def test_a_looser_limit_through_a_second_leg_needs_a_person(self):
        ad = ".ekit/adapters/mini.toml"
        base = {PLAN: entry("calc", ".", "python", "current")}
        head = {ad: mini("max-mutants = 10\n"),
                PLAN: entry("calc", ".", "python", "current") + entry("calc2", ".", ad, "current")}
        got = self.problems(base, head)
        self.assertEqual(len(got), 1, got)
        self.assertIn("`limits.max-mutants` 40 -> 10 for the stack in folder `.` (.ekit/adapters/mini.toml)", got[0])

    def test_a_second_leg_with_another_target_os_or_tool_needs_a_person(self):
        ad = ".ekit/adapters/mini.toml"
        base = {PLAN: entry("calc", ".", "python", "current")}
        head = {ad: mini(), PLAN: entry("calc", ".", "python", "current") + entry("calc2", ".", ad, "current", "macos")}
        got = self.problems(base, head)
        self.assertEqual(len(got), 1, got)
        self.assertIn("stack in folder `.` target-os linux -> macos", got[0])

    def test_two_base_twins_the_one_with_the_same_status_judges(self):
        base = {PLAN: entry("a", ".", "python", "retiring", "windows") + entry("b", ".", "python", "current")}
        self.assertEqual(self.problems(base, {PLAN: entry("b", ".", "python", "current")}), [])
        got = self.problems(base, {PLAN: entry("b", ".", "python", "current", "macos")})
        self.assertEqual(len(got), 1, got)
        self.assertIn("target-os linux -> macos", got[0])

    def test_two_base_twins_and_no_status_match_compare_with_each(self):
        base = {PLAN: entry("a", ".", "python", "retiring", "windows") + entry("b", ".", "python", "planned")}
        got = self.problems(base, {PLAN: entry("c", ".", "python", "current")})
        self.assertEqual(len(got), 1, got)
        self.assertIn("target-os windows -> linux", got[0])

    def test_a_folder_new_to_the_plan_needs_no_person(self):
        base = {PLAN: entry("calc", ".", "python", "current")}
        head = {PLAN: entry("calc", ".", "python", "current") + entry("web", "web", "ts", "planned")}
        self.assertEqual(self.problems(base, head), [])

    def test_a_migration_that_keeps_the_target_os_limits_and_tool_needs_no_person(self):
        ad = ".ekit/adapters/mini.toml"
        base = {PLAN: entry("calc", ".", "python", "current")}
        head = {ad: mini(), PLAN: entry("calc", ".", "python", "retiring") + entry("calc2", ".", ad, "current")}
        self.assertEqual(self.problems(base, head), [])


if __name__ == "__main__":
    unittest.main()
