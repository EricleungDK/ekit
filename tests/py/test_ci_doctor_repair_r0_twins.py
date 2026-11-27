"""R0's editing rules compare every plan entry, not the first one per folder (#24, review round 3). A head entry is
compared with its twin: the base entry with the same folder (normalised) and the same `adapter`; of two such, the one
with the same status; of two with none the same, each. A head entry with no twin in a folder the base has entries for
is compared with each of them: a person decides when its target OS differs, a limit is looser or its mutation tool
differs against any. A folder new to the plan compares with the defaults (linux, the default limits, no tool), so a
setup PR or a drift repair that keeps the defaults needs no person. A folder with several entries names each entry in its
findings. Each call goes through r0.editing, or cli.main for r0 on the repo's adapter file, in this process."""
import json
import os
import unittest

import _kit  # noqa: F401 - the repo root on sys.path
from scripts.mech_review import r0 as r0_mod
from test_stack_plan import Repo

PLAN = ".ekit/stack-plan.toml"
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "adapters")
MINI = os.path.join(FIXTURES, "mini.toml")
AD = ".ekit/adapters/mini.toml"


def entry(name, folder, adapter, status, tos=None):
    return (f'[[stack]]\nname = "{name}"\nfolder = "{folder}"\nadapter = "{adapter}"\nstatus = "{status}"\n'
            + (f'target-os = "{tos}"\n' if tos else "") + "\n")


def mini(limits="", tos=None):
    with open(MINI, encoding="utf-8") as f:
        text = f.read()
    if tos:
        text = text.replace('name = "mini"\n', f'name = "mini"\ntarget-os = "{tos}"\n')
    return text + (f"\n[limits]\n{limits}" if limits else "")


def minirun():
    with open(os.path.join(FIXTURES, "minirun.toml"), encoding="utf-8") as f:
        return f.read()


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
        self.assertIn("stack `calc` in folder `.` target-os linux -> windows in .ekit/stack-plan.toml", got[0])

    def test_a_migration_in_progress_compares_each_leg_with_its_twin(self):
        ad = ".ekit/adapters/mini.toml"
        base = {ad: mini("max-mutants = 60\n"),
                PLAN: entry("old", ".", "python", "retiring") + entry("new", ".", ad, "current")}
        head = {ad: mini("max-mutants = 5\n")}
        got = self.problems(base, head)
        self.assertEqual(len(got), 1, got)
        self.assertIn("`limits.max-mutants` 60 -> 5 for the stack `new` in folder `.` (.ekit/adapters/mini.toml)", got[0])

    def test_a_looser_limit_through_a_second_leg_needs_a_person(self):
        ad = ".ekit/adapters/mini.toml"
        base = {PLAN: entry("calc", ".", "python", "current")}
        head = {ad: mini("max-mutants = 10\n"),
                PLAN: entry("calc", ".", "python", "current") + entry("calc2", ".", ad, "current")}
        got = self.problems(base, head)
        self.assertEqual(len(got), 1, got)
        self.assertIn("`limits.max-mutants` 40 -> 10 for the stack `calc2` in folder `.` (.ekit/adapters/mini.toml)", got[0])

    def test_a_second_leg_with_another_target_os_or_tool_needs_a_person(self):
        ad = ".ekit/adapters/mini.toml"
        base = {PLAN: entry("calc", ".", "python", "current")}
        head = {ad: mini(), PLAN: entry("calc", ".", "python", "current") + entry("calc2", ".", ad, "current", "macos")}
        got = self.problems(base, head)
        self.assertEqual(len(got), 1, got)
        self.assertIn("stack `calc2` in folder `.` target-os linux -> macos", got[0])
        run = ".ekit/adapters/minirun.toml"
        got = self.problems(base, {run: minirun(), PLAN: entry("calc", ".", "python", "current")
                                   + entry("calc2", ".", run, "current")})
        self.assertEqual(len(got), 1, got)
        self.assertIn("[mutation.tool] of the stack `calc2` in folder `.` changed (.ekit/adapters/minirun.toml)", got[0])

    def test_with_no_twin_each_base_entry_of_the_folder_judges_not_the_defaults(self):
        """review F3 M3: the base's windows entry, not linux by default, is what a new leg is held to"""
        got = self.problems({PLAN: entry("c", ".", "python", "current", "windows")},
                            {AD: mini(), PLAN: entry("c", ".", "python", "current", "windows")
                             + entry("n", ".", AD, "current")})
        self.assertEqual(len(got), 1, got)
        self.assertIn("stack `n` in folder `.` target-os windows -> linux", got[0])

    def test_with_no_twin_every_base_entry_judges_in_either_order(self):
        """review F3 M14, M15: the windows entry first or last"""
        a, b = entry("a", ".", "python", "current"), entry("b", ".", "ts", "current", "windows")
        for order in ((a, b), (b, a)):
            with self.subTest(first=order[0][:30]):
                got = self.problems({PLAN: "".join(order)}, {AD: mini(), PLAN: "".join(order) + entry("n", ".", AD, "current")})
                self.assertEqual(len(got), 1, got)
                self.assertIn("stack `n` in folder `.` target-os windows -> linux", got[0])

    def test_twins_with_no_status_match_compare_with_the_twins_only(self):
        """review F3 M6: of two python twins neither `current`, each judges; the ts entry is no twin of a python one"""
        base = {PLAN: entry("a", ".", "python", "retiring") + entry("b", ".", "python", "planned")
                + entry("c", ".", "ts", "current", "macos")}
        self.assertEqual(self.problems(base, {PLAN: entry("a", ".", "python", "current")
                                              + entry("c", ".", "ts", "current", "macos")}), [])

    def test_twins_with_no_status_match_each_judge_the_last_too(self):
        """review F3 M7: the windows twin is the second"""
        got = self.problems({PLAN: entry("a", ".", "python", "retiring") + entry("b", ".", "python", "planned", "windows")},
                            {PLAN: entry("x", ".", "python", "current")})
        self.assertEqual(len(got), 1, got)
        self.assertIn("target-os windows -> linux", got[0])

    def test_two_entries_moved_to_windows_are_two_findings(self):
        """review F3 M11: one finding per entry, none doubled"""
        base = {PLAN: entry("a", ".", "python", "current") + entry("b", ".", "ts", "current")}
        got = self.problems(base, {PLAN: entry("a", ".", "python", "current", "windows")
                                   + entry("b", ".", "ts", "current", "windows")})
        self.assertEqual(len(got), 1, got)
        items = got[0].split("a person decides: ", 1)[1].split("; ")
        self.assertEqual(items, ["stack `a` in folder `.` target-os linux -> windows in .ekit/stack-plan.toml",
                                 "stack `b` in folder `.` target-os linux -> windows in .ekit/stack-plan.toml"])

    def test_an_adapter_path_spelled_another_way_is_the_same_twin(self):
        """review F4: `./.ekit/adapters/mini.toml` is the base's `.ekit/adapters/mini.toml`"""
        base = {AD: mini(), PLAN: entry("a", ".", "python", "retiring", "windows") + entry("m", ".", AD, "current")}
        self.assertEqual(self.problems(base, {PLAN: entry("a", ".", "python", "retiring", "windows")
                                              + entry("m", ".", "./" + AD, "current")}), [])

    def test_two_base_twins_the_one_with_the_same_status_judges(self):
        # (both kept: dropping `a` would be a removal, judged by test_ci_doctor_repair_r0_departed)
        keep = entry("a", ".", "python", "retiring", "windows")
        base = {PLAN: keep + entry("b", ".", "python", "current")}
        self.assertEqual(self.problems(base, {PLAN: keep + entry("b", ".", "python", "current")}), [])
        got = self.problems(base, {PLAN: keep + entry("b", ".", "python", "current", "macos")})
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


class BuiltinBesideAFileEntry(unittest.TestCase):
    """review F1: a head entry with no adapter file (a built-in) compared with a base entry whose adapter file sets the
    target OS: the finding names the plan, never `None`, and r0 on the repo's adapter file prints its JSON"""

    def setUp(self):
        self.repo = Repo(self)
        self.base = self.repo.commit({AD: mini(tos="windows"), PLAN: entry("m", ".", AD, "current")})

    def r0(self, head):
        r = _kit.run_cli(["r0", "--repo", self.repo.path, "--base", self.base, "--head", head, "--stack", "mini"])
        return r, (json.loads(r.stdout) if r.stdout else None)

    def check(self, plan, who):
        r, env = self.r0(self.repo.commit({PLAN: plan}))
        self.assertIsNotNone(env, r.stderr)
        people = [e for e in env["entries"] if e["class"] == "needs-human"]
        self.assertEqual(len(people), 1, env["entries"])
        self.assertEqual(people[0]["file"], PLAN)
        self.assertIn(f"stack {who}in folder `.` target-os windows -> linux in .ekit/stack-plan.toml",
                      people[0]["problem"])
        self.assertNotIn("None", people[0]["problem"])

    def test_a_built_in_entry_added_beside_it(self):
        self.check(entry("m", ".", AD, "current") + entry("p", ".", "python", "current"), "`p` ")

    def test_its_adapter_file_replaced_by_a_built_in(self):
        self.check(entry("m", ".", "python", "current"), "")

    def test_a_crash_in_r0_on_the_repos_adapter_file_is_no_exit_1(self):
        """review F1: cli._r0_repo never exits 1 with no result (the guard job keeps an exit-1 result)"""
        from unittest import mock
        with mock.patch("scripts.mech_review.engine.r0", side_effect=TypeError("boom")):
            r, env = self.r0(self.repo.commit({PLAN: entry("m", ".", AD, "current")}))
        self.assertEqual((r.returncode, env), (2, None))
        self.assertIn("mech-review: r0 crashed: TypeError: boom", r.stderr)


if __name__ == "__main__":
    unittest.main()
