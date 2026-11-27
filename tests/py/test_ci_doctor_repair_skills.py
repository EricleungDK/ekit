"""Skill text for ci-doctor's repair mode (#24) is behaviour for agents: each test pins one outcome. An `adapter-fix`
entry never goes to the PR's agent; ci-doctor repairs it on a branch and PR of its own, cut from the base; repair
rounds are no fix rounds of the coding branch (no commit there, no `mech:` line); a repair that loosens a limit,
changes a target OS or ignores a folder stops for a person; one out of budget ends with a report and no PR."""
import os
import re
import unittest

import _kit


def read(skill, name="SKILL.md"):
    with open(os.path.join(_kit.ROOT, "skills", skill, name), encoding="utf-8") as f:
        return f.read()


def flat(text):
    return re.sub(r"\s+", " ", text)


def section(text, heading):
    m = re.search(r"^(#{2,3}) " + re.escape(heading) + r".*$", text, re.M)
    if not m:
        raise AssertionError(f"no heading {heading!r}")
    rest = text[m.end():]
    end = re.search(r"^#{2,%d} " % len(m.group(1)), rest, re.M)
    return rest[: end.start()] if end else rest


class CiDoctorRoutes(unittest.TestCase):
    def test_repair_mode_is_built_and_linked(self):
        s = flat(read("ci-doctor"))
        self.assertNotIn("not built yet", s)
        self.assertIn("[repair.md](repair.md)", s)
        self.assertRegex(s, r"`repair`[^.]*follow \[repair\.md\]\(repair\.md\)")

    def test_an_adapter_fix_entry_triggers_the_skill(self):
        description = read("ci-doctor").split("---")[1]
        self.assertIn("`adapter-fix` entry", description)

    def test_an_adapter_fix_entry_from_a_pr_goes_straight_to_repair(self):
        self.assertRegex(flat(section(read("ci-doctor"), "1. Diagnose")),
                         r"`adapter-fix` entry[^.]*: follow \[repair\.md\]\(repair\.md\)")


class Repair(unittest.TestCase):
    def setUp(self):
        self.text = read("ci-doctor", "repair.md")
        self.s = flat(self.text)

    def test_every_source_of_the_class_has_its_edit(self):
        table = section(self.text, "1. Read the entry")
        for source in ("`static:", "`runtime:run:", "`runtime:r3:", "`D`", "parser", "does not read"):
            self.assertIn(source, table, source)

    def test_the_repair_is_on_a_branch_cut_from_the_base_with_no_mech_line(self):
        s = flat(section(self.text, "2. Branch"))
        self.assertIn("from the PR's base branch", s)
        self.assertIn("never the PR's branch", s)
        self.assertIn("no `mech:` body line", s)
        self.assertIn("`adapter-fix: <entry id>`", s)

    def test_a_drift_repair_covers_with_a_planned_entry_or_ignores(self):
        s = flat(section(self.text, "3. Edit"))
        self.assertIn("`planned`", s)
        self.assertIn("`ignore`", s)
        self.assertIn("setup.md", s)

    def test_the_proof_is_full_and_the_pr_is_re_run_on_it(self):
        s = flat(section(self.text, "4. Prove it"))
        for part in ("Static half", "Census of the repo's own tests", "Runtime half", "The cheat list", "drift", "merge",
                     "Budget: 5 rounds"):
            self.assertIn(part, s, part)

    def test_a_limit_the_doc_names_replaces_no_proof_round(self):
        """the budget evals' runs stopped on a format limit the CI doc names, before any round: the rounds still run,
        and the report names each case that still fails (setup.md says the same for setup mode)"""
        self.assertIn("A limit the CI doc names replaces no round", flat(section(self.text, "4. Prove it")))
        s = flat(section(read("ci-doctor", "setup.md"), "4. Prove it with R0"))
        self.assertIn("A limit covers an uncaught cheat alone, never a failing R0 case or a census miss, and it replaces "
                      "no round", s)
        self.assertIn("the report names each case that still fails as `r0` or `r2` gave it", s)

    def test_a_person_decides_a_loosened_limit_a_target_os_or_an_ignore(self):
        s = flat(section(self.text, "4. Prove it"))
        for part in ("`needs-human`", "a loosened limit", "a changed target OS", "a folder added to `ignore`",
                     "stop before the PR", "Needs-you block", "`Decide:`", "commit it too"):
            self.assertIn(part, s, part)

    def test_out_of_budget_ends_with_a_report_and_no_pr(self):
        s = flat(section(self.text, "4. Prove it"))
        self.assertIn("Budget spent", s)
        self.assertIn("Commit nothing in the repo, open no PR", s)
        self.assertIn("in a scratch clone (never a branch of the repo)", s)
        self.assertIn("Every stage passes → commit the edit on the repair branch", s)
        self.assertIn("/mech-waive", s)

    def test_the_pr_body_says_how_ci_judges_it(self):
        s = flat(section(self.text, "5. Open the adapter-fix PR"))
        self.assertIn("proves the base branch's copy", s)
        self.assertIn("judged by its own plan", s)
        self.assertIn("/mech-waive", s)
        self.assertIn("close and reopen", s)
        self.assertIn("it needs the owner's `/mech-waive <id> <reason>` on that R0 entry", s)
        self.assertIn("this deviates from #24's", s)


class SetupPrCheck(unittest.TestCase):
    """the owner's setup-gap decision (#24 round 3): a setup PR for a repo with no built-in stack reads `no result`,
    red with nothing to waive; the owner merges on the proof report and makes the check required after the merge"""

    def test_the_setup_pr_body_says_its_check_reads_no_result(self):
        s = flat(section(read("ci-doctor", "setup.md"), "8. Open the setup PR"))
        self.assertIn("`no result`, red with nothing to waive", s)
        self.assertIn("the owner merges on the proof report below, then makes the mech-review check required", s)

    def test_the_required_check_waits_for_the_first_manifest_in_an_empty_repo(self):
        self.assertIn("required (an empty repo: after the first manifest lands)",
                      flat(section(read("ci-doctor", "setup.md"), "8. Open the setup PR")))

    def test_the_setup_checks_the_repos_own_build_runs_the_mutation_tool(self):
        s = flat(section(read("ci-doctor", "setup.md"), "3. Draft the adapter"))
        self.assertIn("it cannot see whether the repo's own build runs the declared mutation tool", s)
        self.assertIn("add that wiring to the setup PR, or leave `[mutation.tool]` out so that R3 reads `n/a`", s)
        self.assertIn("the mutation tool's wiring in the repo's build, or that `[mutation.tool]` is left out",
                      flat(section(read("ci-doctor", "setup.md"), "8. Open the setup PR")))

    def test_an_expected_no_result_is_no_reason_to_set_up_again(self):
        s = flat(section(read("ci-doctor"), "1. Diagnose"))
        self.assertIn("A setup PR's own `no result` (its base resolves no stack), and that of a repo whose plan has "
                      "only `planned` entries, are expected", s)

    def test_skill_step_5_tells_the_two_checks_apart(self):
        s = flat(section(read("ci-doctor"), "5. Open the PR"))
        self.assertIn("A repo with a built-in stack: red `needs-human` by design", s)
        self.assertIn("A setup PR (setup.md) whose base resolves no stack (no built-in project there): `no result`", s)
        self.assertIn("One whose base resolves a built-in stack beside the new one: the check runs", s)

    def test_the_setup_pr_body_names_both_cases_and_the_new_stacks_entry(self):
        """review F5, F6: the check runs where the base resolves a built-in stack, and a folder new to the plan with
        a mutation tool or a non-linux target OS is a needs-human entry there"""
        s = flat(section(read("ci-doctor", "setup.md"), "8. Open the setup PR"))
        self.assertIn("The base resolves no stack (no built-in project there): `no result`", s)
        self.assertIn("The base resolves one (a built-in project beside the new one): the check runs and reads red "
                      "`needs-human` for `.github/**`, and also for the new stack when its adapter declares a "
                      "`[mutation.tool]` or its target OS is not linux", s)
        self.assertIn("a built-in keeps them and needs no person", flat(read("ci-doctor", "repair.md")))

    def test_the_setup_evals_grade_the_same(self):
        for case in ("ci-doctor-setup-java", "ci-doctor-setup-java-no-ci", "ci-doctor-setup-planned"):
            with open(os.path.join(_kit.ROOT, "evals", case, "graders", "criteria.md"), encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn("goes red `needs-human` by design", text, case)
            self.assertIn("reads `no result`", text, case)


class TriageLabel(unittest.TestCase):
    def setUp(self):
        self.text = read("failure-triage", "mech.md")

    def test_adapter_fix_is_a_label_of_its_own(self):
        self.assertIn("`sandbox/env`, `flaky`, `real bug`, `adapter-fix`, `Needs-you`", flat(self.text))
        row = next(line for line in self.text.splitlines() if line.startswith("| `adapter-fix`"))
        self.assertEqual(row.split("|")[2].strip(), "adapter-fix")
        self.assertIn("No edit by the PR's agent", row)
        self.assertIn("ci-doctor", row)
        self.assertIn("repair mode", row)
        self.assertIn("emergency exit", row)

    def test_every_source_of_the_class_is_named(self):
        row = next(line for line in self.text.splitlines() if line.startswith("| `adapter-fix`"))
        for source in ("`R0` static", "`R0` runtime", "`D`", "parser", "plan does not read"):
            self.assertIn(source, row, source)

    def test_an_entry_r0_blocks_waits_for_the_repaired_adapter(self):
        s = flat(section(self.text, "Gate"))
        self.assertIn("`blocked: R0` on an `agent-fixable` entry → not yet red", s)
        self.assertIn("No fix round", s)
        self.assertIn("A `needs-human` one stays the person's", s)

    def test_a_held_entry_gets_no_fix_plan_until_the_repaired_adapter_reads_it(self):
        """#24: an entry R0 blocks is not worked on until the adapter-fix lands, so its plan is the hold alone: no
        `Fix:` lines and no conditional fix for later (the triage eval's next-action-held criterion grades the same)"""
        s = flat(section(self.text, "Gate"))
        self.assertIn("its plan is the hold alone", s)
        self.assertIn("no `Fix:` lines", s)
        self.assertIn("triaged from that run", s)
        self.assertIn("Each `agent-fixable` fail that Gate 3 does not hold: open its fix plan", flat(self.text))

    def test_a_held_entry_rejoins_once_r0_is_waived_or_the_repair_stops(self):
        s = flat(section(self.text, "Gate"))
        self.assertIn("once a person waives the R0 entry, or the repair stops out of budget", s)
        self.assertIn("an `agent-fixable` one is a fix round of the PR's agent", s)
        self.assertIn("otherwise it joins the Needs-you block with the R0 entry", s)

    def test_a_held_entry_opens_the_answer_with_its_own_token(self):
        s = flat(section(self.text, "Open the answer"))
        self.assertIn("`<id> → held: blocked by <R0 id>`", s)
        self.assertIn("The class-map tokens are read by the finish report", s)  # `held` is listed under Open there
        self.assertNotIn("Budget: 5 rounds by default", flat(read("ci-doctor", "repair.md")))

    def test_an_adapter_fix_entry_takes_no_fix_round(self):
        s = flat(section(self.text, "Rounds"))
        self.assertIn("`adapter-fix` entry", s)
        self.assertIn("no fix round", s)


class RoundsHold(unittest.TestCase):
    def test_orchestrate_starts_the_repair_and_never_hands_the_entry_over(self):
        s = flat(read("orchestrate-agent"))
        self.assertIn("`adapter-fix` entry never goes to the engineer", s)
        self.assertIn("ci-doctor's repair mode", s)
        self.assertIn("repair rounds are no rounds of the unit", s)
        self.assertIn("entries marked `blocked: R0` wait for that run too", s)
        self.assertIn("once a person waives the R0 entry, or the repair stops out of budget, they rejoin", s)
        self.assertIn("an entry marked `blocked: R0` is held, not sent, and opens as `<id> → held: blocked by <R0 id>` "
                      "(step 4)", s)

    def test_finish_counts_no_round_for_an_adapter_fix_entry(self):
        self.assertIn("an `adapter-fix` entry counts no fix round", flat(read("finish")))


if __name__ == "__main__":
    unittest.main()
