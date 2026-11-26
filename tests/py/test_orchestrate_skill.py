"""orchestrate-agent skill text is behaviour for agents: each test pins one Done-when outcome of #35 #36 #37 #38 #45."""
import os
import re
import unittest

import _kit

SKILL_DIR = os.path.join(_kit.ROOT, "skills", "orchestrate-agent")


def read(name):
    with open(os.path.join(SKILL_DIR, name), encoding="utf-8") as f:
        return f.read()


def section(text, heading):
    """The text under a `## <heading>` or `### <heading>` line, up to the next heading of the same or higher level."""
    m = re.search(r"^(#{2,3}) " + re.escape(heading) + r".*$", text, re.M)
    if not m:
        raise AssertionError(f"no heading {heading!r}")
    level = len(m.group(1))
    rest = text[m.end():]
    end = re.search(r"^#{2,%d} " % level, rest, re.M)
    return rest[: end.start()] if end else rest


def flat(text):
    return re.sub(r"\s+", " ", text)


class TestPlanTimeGates(unittest.TestCase):
    """#36: protected-path edits and worktree limits surface at plan time."""

    def test_checklist_lists_each_protected_path_edit_as_needs_you_row_with_exact_lines(self):
        s = flat(section(read("SKILL.md"), "3. Acceptance checklist"))
        self.assertIn("protected path", s)
        self.assertIn("Needs-you row", s)
        self.assertIn("exact lines", s)
        self.assertIn("before dispatch", s)

    def test_protected_path_rule_is_its_own_bullet(self):
        s = section(read("SKILL.md"), "3. Acceptance checklist")
        self.assertRegex(s, r"(?m)^- [^\n]*protected path[^\n]*Needs-you row")

    def test_brief_has_agent_enter_its_worktree_before_its_first_write(self):
        self.assertIn("enter it before your first write", flat(read("brief-template.md")).lower())

    def test_worktree_entry_names_the_path_and_no_cd_fallback(self):
        # EnterWorktree without `path` makes a new worktree; `cd` does not get Write/Edit past the hook
        for name in ("brief-template.md", "taster-brief-template.md"):
            t = flat(read(name))
            self.assertIn("EnterWorktree with `path: <", t, name)
            self.assertNotIn("else `cd", t, name)

    def test_coordinate_verifies_foreign_head_in_scratch_worktree_and_own_checkout_stays(self):
        s = flat(section(read("SKILL.md"), "5. Coordinate")).lower()
        self.assertIn("scratch worktree", s)
        self.assertIn("build the commit in your own worktree and push it", s)
        self.assertIn("your own checkout stays on its branch", s)

    def test_scratch_worktrees_live_under_claude_worktrees_and_are_entered_by_path(self):
        # a copy outside .claude/worktrees/ is outside the write hook's allowed roots
        for t in (flat(section(read("SKILL.md"), "5. Coordinate")), flat(read("review-brief-template.md"))):
            self.assertIn("<repo>/.claude/worktrees/<", t)
            self.assertIn("EnterWorktree with `path:", t)
            self.assertNotIn("git worktree add <tmp>", t)

    def test_taster_brief_names_its_worktree_and_how_to_enter_it(self):
        t = flat(read("taster-brief-template.md"))
        self.assertIn("Worktree: <absolute path of the implementer's worktree>", t)
        self.assertIn("enter it before your first write", t.lower())

    def test_taster_works_in_the_idle_implementers_worktree(self):
        s = flat(section(read("SKILL.md"), "Taste"))
        self.assertIn("the implementer's worktree", s)
        self.assertIn("idle", s)
        self.assertIn("`git pull --ff-only` or re-checks HEAD before its taste fix", s)


class TestReviewAndTasterBriefs(unittest.TestCase):
    """#37: review and taste dispatches fill a template; the reviewer's rules live with its brief."""

    def test_review_brief_carries_range_spec_and_mech_proof(self):
        t = flat(read("review-brief-template.md"))
        for field in ("Range: <base>..<head>", "Spec: <", "Mech proved: <", "Claims: <"):
            self.assertIn(field, t)

    def test_review_brief_holds_no_dispatch_parameters(self):
        self.assertNotIn("Model:", read("review-brief-template.md"))

    def test_review_rule_three_covers_any_removed_code(self):
        self.assertIn("any code the range removes", flat(read("review-brief-template.md")))

    def test_review_brief_carries_the_standing_rules(self):
        t = flat(read("review-brief-template.md"))
        for rule in (
            "malformed and degenerate input on every validator",
            "sample equivalence claims by applying the mutant",
            "compare behaviour and timing",
            "CONFIRM or REJECT each changed expected value against a quoted spec sentence",
            "reproduce in a scratch copy",
            "reproduced or plausible",
        ):
            self.assertIn(rule, t)

    def test_review_evidence_rule_runs_ekit_hooks_and_task_verify_against_a_temp_store(self):
        # #121: a reviewer's SessionStart run in a scratch worktree wrote into the main checkout's declared.json
        rule5 = flat(read("review-brief-template.md").split("5. Evidence:", 1)[1].split("Report:", 1)[0])
        self.assertIn("Run every ekit hook and every task-verify call with `EKIT_STATE` set to a temp dir", rule5)
        self.assertIn('EKIT_STATE="$(mktemp -d)"', rule5)
        self.assertIn("keyed by the git common dir", rule5)

    def test_review_evidence_rule_reuses_one_temp_store_and_names_both_live_stores(self):
        # review of #121: an inline EKIT_STATE per call gave each call a fresh store (F4: `check` exit 4, not 1);
        # the common-dir key is task-verify's only, the finish gate keeps a shared state dir (F5)
        rule5 = flat(read("review-brief-template.md").split("5. Evidence:", 1)[1].split("Report:", 1)[0])
        self.assertIn('a temp dir, made once per reproduction and reused by each call (`export EKIT_STATE="$(mktemp -d)"` first)', rule5)
        self.assertNotIn('EKIT_STATE="$(mktemp -d)" <py>', rule5)
        self.assertIn("task-verify into the main checkout's git dir", rule5)
        self.assertIn("the finish gate into the shared state dir", rule5)

    def test_taster_brief_carries_its_fields(self):
        t = flat(read("taster-brief-template.md"))
        for field in ("Read list:", "Criteria:", "Install:", "Runner:", "`can-fail` baseline:", "Commit scope:"):
            self.assertIn(field, t)

    def test_taster_brief_is_black_box(self):
        t = flat(read("taster-brief-template.md"))
        self.assertIn("no source, diff, or implementer reasoning", t)

    def test_taster_runs_mech_review_on_its_commit_before_the_report(self):
        # #118: a taster committed scenarios that failed 4 mech entries; its commit's summary shows 0 fail first
        t = flat(read("taster-brief-template.md"))
        self.assertIn("Mech check:", t)
        self.assertIn("scripts/mech-review.py all", t)
        self.assertIn("--head HEAD", t)
        self.assertIn("its `summary` shows 0 fail", t)
        self.assertLess(t.index("Mech check:"), t.index("Report:"))

    def test_taster_mech_range_is_its_own_commits_only(self):
        # review of #118 (F1): from the can-fail baseline the range takes in the implementer's tests, and the
        # taster, who commits only scenarios, could never reach 0 fail
        t = flat(read("taster-brief-template.md"))
        self.assertIn("--base <the HEAD sha of the Worktree line>", t)
        self.assertNotIn("--base <the can-fail baseline ref>", t)
        self.assertIn("An entry in a file you did not change goes into your report, not your diff.", t)

    def test_taster_report_carries_the_mech_summary_with_0_fail(self):
        report = flat(read("taster-brief-template.md")).split("Report:", 1)[1]
        self.assertIn("the mech-review `summary` line of your commit, with 0 fail", report)

    def test_review_relay_and_taste_dispatch_fill_the_templates(self):
        skill = read("SKILL.md")
        self.assertIn("[review-brief-template.md](review-brief-template.md)", section(skill, "Review relay"))
        self.assertIn("[taster-brief-template.md](taster-brief-template.md)", section(skill, "Taste"))

    def test_skill_links_the_templates_without_relisting_their_fields(self):
        s = flat(read("SKILL.md"))
        self.assertNotIn("(range, spec, the mech JSON", s)
        self.assertNotIn("(black box: its worktree", s)

    def test_reviewer_rules_are_not_in_agents_md(self):
        """Guard: passes on base too; keeps the reviewer's rules out of AGENTS.md."""
        with open(os.path.join(_kit.ROOT, "AGENTS.md"), encoding="utf-8") as f:
            agents = f.read()
        self.assertNotIn("equivalence claims", agents)
        self.assertNotIn("degenerate input", agents)


class TestRoundsPerSource(unittest.TestCase):
    """#45: rounds count per finding source; the repeat stop stays."""

    def step4(self):
        return flat(section(read("SKILL.md"), "4. Divide and dispatch"))

    def test_skill_counts_three_rounds_per_source(self):
        s = self.step4()
        self.assertRegex(s, r"3 rounds per (finding )?source")
        for source in ("review", "taste", "CI"):
            self.assertIn(source, s)
        self.assertNotIn("Count rounds per unit", s)
        self.assertNotIn("Each taste-fix cycle counts toward the same 3 rounds as review-fix", flat(read("SKILL.md")))

    def test_first_ci_failure_after_clean_review_and_taste_gets_a_round_without_a_stop(self):
        self.assertIn("a first CI failure after a clean review and taste gets a CI round, no stop", self.step4())

    def test_same_id_or_finding_failing_three_times_still_escalates(self):
        self.assertIn("the same mech `id` or the same finding fails a 3rd time: stop and escalate", self.step4())

    def test_a_review_finding_has_a_key_for_counting(self):
        # a review finding has no id: file plus a short title, kept the same across rounds
        for t in (self.step4(), flat(read("brief-template.md"))):
            self.assertIn("file plus a short title", t)

    def test_brief_says_the_three_strike_stop_counts_per_id(self):
        self.assertIn("(the 3-strike stop counts per id)", flat(read("brief-template.md")))

    def test_brief_counts_rounds_per_source(self):
        t = flat(read("brief-template.md"))
        self.assertIn("per source (review, taste, CI)", t)


class TestLocalTools(unittest.TestCase):
    """#35 #38: local R3 before review; status from one script call."""

    def test_brief_verify_runs_r3_local_before_the_review_request(self):
        # owner, 2026-11-24: a local R3 is ~20-30 min; run it once, before the final review request
        t = flat(read("brief-template.md"))
        self.assertIn("scripts/r3-local.py", t)
        self.assertIn("once per unit, when the orchestrator says the review is clean, not after each fix round", t)
        self.assertIn("a MISSED on a changed line is fixed with a killing test in a new commit, and that commit is your final review request", t)
        self.assertNotIn("before the review request, R3", t)
        self.assertIn("after review passes and the R3 run of task 4", t)

    def test_local_r3_uses_ci_budget_with_shards_in_parallel(self):
        t = flat(read("brief-template.md"))
        self.assertIn("shards in parallel", t)
        self.assertIn("<mutation budget, minutes>", t)

    def test_r3_local_call_names_stack_test_paths_and_budget(self):
        # r3-local's --test-paths default is only tests/**; --stack is required
        t = flat(read("brief-template.md"))
        for arg in ("--stack <stack>", "--test-paths <glob>", "--mutation-budget <mutation budget, minutes>"):
            self.assertIn(arg, t)

    def test_r3_local_runs_on_a_commit_and_on_posix(self):
        t = flat(read("brief-template.md"))
        self.assertIn("commit first: it tests the head commit", t)
        self.assertIn("POSIX only (WSL on Windows)", t)

    def test_changelog_says_the_orchestrator_runs_mech_summary(self):
        with open(os.path.join(_kit.ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            log = f.read()
        self.assertNotIn("CI runs `scripts/mech-summary.py`", log)

    def test_status_question_answered_with_orch_status(self):
        s = flat(section(read("SKILL.md"), "5. Coordinate"))
        self.assertIn("scripts/orch-status.py <worktree>", s)


class TestUnconfirmedSurvivor(unittest.TestCase):
    """#79: an R3 unconfirmed survivor is a missed mutant until a test kills it, in the finish report and the relay."""
    RULE = "an `R3 unconfirmed survivor` entry is a missed mutant until a test kills it"

    def test_the_review_relay_hands_it_back_as_a_missed_mutant(self):
        s = flat(section(read("SKILL.md"), "Review relay"))
        self.assertIn(self.RULE, s)
        self.assertIn("`fail` entries go back verbatim, and so do R3's unconfirmed survivors: " + self.RULE
                      + ", never confirmed or rejected", s)

    def test_finish_reads_it_as_a_missed_mutant_not_as_debt(self):
        with open(os.path.join(_kit.ROOT, "skills", "finish", "mech.md"), encoding="utf-8") as f:
            t = flat(f.read())
        self.assertIn(self.RULE[0].upper() + self.RULE[1:], t)
        self.assertIn("not done while one is open", t)

    def test_the_brief_fixes_one_before_review(self):
        self.assertIn("final review request; an unconfirmed survivor is fixed the same way (`r3-local.py` exits 1 on "
                      "either)", flat(read("brief-template.md")))


class TestCiMonitor(unittest.TestCase):
    """Retro of the #34-#46 run: a harness that forbids polling CI wakes the PR's session through its CI monitor; the
    owner approves that monitor once, at plan time, for every PR the run opens."""

    def test_checklist_asks_the_owner_once_for_every_prs_ci_monitor(self):
        s = section(read("SKILL.md"), "3. Acceptance checklist")
        self.assertRegex(s, r"(?m)^- CI monitor: [^\n]*Needs-you row[^\n]*every PR the run opens")

    def test_brief_turns_the_monitor_on_after_opening_its_pr_instead_of_watching(self):
        t = flat(read("brief-template.md"))
        self.assertIn("turn on its CI monitor (Auto-fix)", t)
        self.assertNotIn("gh pr checks <n> --watch", t)


class TestAgentsMdPreReviewChecks(unittest.TestCase):
    """Retro of the #34-#46 run: R3 and a new Python were first seen in CI; AGENTS.md names both local runs."""

    def agents(self):
        with open(os.path.join(_kit.ROOT, "AGENTS.md"), encoding="utf-8") as f:
            return flat(f.read())

    def test_names_r3_local_with_ekits_own_caller_inputs(self):
        """#84: one command carries the caller inputs (test_ci_local checks them against the workflow), not a recipe."""
        t = self.agents()
        self.assertIn("`python3 scripts/ci-local.py --base origin/main`", t)
        self.assertNotIn("scripts/r3-local.py --base", t)
        self.assertNotIn("--mutation-budget 20", t)

    def test_r3_local_runs_once_before_the_final_review_request(self):
        t = self.agents()
        self.assertIn("Once per change under `scripts/`, before the final review request (not after each fix round)", t)
        self.assertNotIn("Before a review request on a change under `scripts/`", t)

    def test_names_a_run_under_the_newest_python(self):
        """#84: ci-local's suite step runs it (uv run --no-project); the bare recipe could write a uv.lock in the
        repo."""
        t = self.agents()
        self.assertIn("the unittest suite on CI's Python 3.14", t)
        self.assertNotIn("uv run --python 3.14", t)


if __name__ == "__main__":
    unittest.main()


class TestVerifiedCommit(unittest.TestCase):
    """#81: the review relay checks that the mech result's head is the worktree's head and the pushed tip."""

    def relay(self):
        return flat(section(read("SKILL.md"), "Review relay"))

    def test_relay_runs_verified_commit_before_the_review(self):
        s = self.relay()
        call = "`<py> -I <kit>/scripts/verified-commit.py --allow-behind --expect <head> <result> <worktree>`"
        self.assertIn(call, s)
        self.assertLess(s.index(call), s.index("Then run the code review"))

    def test_relay_expects_the_head_the_review_request_names(self):
        self.assertIn("`<head>` is the head SHA the agent's review request names", self.relay())

    def test_relay_runs_verified_commit_before_a_push_and_after_it(self):
        s = self.relay()
        self.assertIn("Before a push", s)
        self.assertIn("the same call without `--allow-behind`", s)

    def test_a_refusal_goes_back_to_the_agent(self):
        s = self.relay()
        self.assertIn("a refusal goes back to the agent verbatim with SendMessage", s)
