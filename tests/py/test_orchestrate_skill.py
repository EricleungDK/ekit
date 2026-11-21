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

    def test_taster_brief_carries_its_fields(self):
        t = flat(read("taster-brief-template.md"))
        for field in ("Read list:", "Criteria:", "Install:", "Runner:", "`can-fail` baseline:", "Commit scope:"):
            self.assertIn(field, t)

    def test_taster_brief_is_black_box(self):
        t = flat(read("taster-brief-template.md"))
        self.assertIn("no source, diff, or implementer reasoning", t)

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
        t = flat(read("brief-template.md"))
        self.assertIn("scripts/r3-local.py", t)
        self.assertIn("before the review request", t)
        self.assertIn("a MISSED on a changed line is fixed before review", t)

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


if __name__ == "__main__":
    unittest.main()
