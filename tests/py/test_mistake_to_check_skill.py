"""mistake-to-check skill text is behaviour for agents: each test pins one acceptance criterion of #87 (spec #78)."""
import os
import re
import unittest

import _kit

SKILLS = os.path.join(_kit.ROOT, "skills")


def read(*parts):
    with open(os.path.join(SKILLS, *parts), encoding="utf-8") as f:
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


def skill():
    return read("mistake-to-check", "SKILL.md")


def frontmatter():
    return skill().split("---")[1]


class TestTheSkillShips(unittest.TestCase):
    def test_it_is_named_mistake_to_check_and_model_invoked(self):
        fm = frontmatter()
        self.assertRegex(fm, r"(?m)^name: mistake-to-check$")
        self.assertNotIn("disable-model-invocation", fm)  # retro, another skill, reaches it

    def test_its_description_triggers_on_an_agent_mistake_that_should_become_a_check(self):
        self.assertIn("an agent mistake should become a check", re.search(r"(?m)^description: (.*)$", frontmatter())
                      .group(1))

    def test_the_plugin_ships_it_and_the_readme_lists_it(self):
        with open(os.path.join(_kit.ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            self.assertIn('"./skills/mistake-to-check"', f.read())
        with open(os.path.join(_kit.ROOT, "README.md"), encoding="utf-8") as f:
            self.assertIn("[`mistake-to-check`](skills/mistake-to-check/SKILL.md)", f.read())


class TestFilterAndRoute(unittest.TestCase):
    """It states the filter and the routing table; its output is the change itself or a one-line reason for none."""

    def test_the_filter_asks_the_four_questions_in_order(self):
        s = flat(section(skill(), "1. Filter"))
        self.assertRegex(s, r"(?s)\*\*Decidable\*\*.*\*\*A class\*\*.*\*\*Visible at check time\*\*.*"
                            r"\*\*Worth its upkeep\*\*")
        self.assertIn("with no judgment", s)
        self.assertIn("name a second, different example", s)
        self.assertIn("stop at the first no with `No check: <mistake>: <the question>: <why>`", s)

    def test_the_routing_table_has_the_four_rows(self):
        s = section(skill(), "2. Remove the possibility, then route")
        for row in (r"^\| The code \(.*\) \| The stack's own linter, as a configured rule \|$",
                    r"^\| The diff \(.*\) \| A co-change rule with its two proof cases \|$",
                    r"^\| The process \(.*\) \| One of ekit's gates or command exit codes, with a red-first test \|$",
                    r"^\| The environment \(.*\) \| No rule: an environment fix \|$"):
            self.assertRegex(s, re.compile(row, re.M))

    def test_removing_the_possibility_is_tried_before_any_route(self):
        s = flat(section(skill(), "2. Remove the possibility, then route"))
        self.assertLess(s.index("First make the mistake impossible"), s.index("| The mistake is about |"))
        self.assertIn("derive the list from the directory", s)

    def test_the_result_is_the_change_or_one_no_check_line(self):
        s = section(skill(), "4. Result")
        self.assertIn("One result per mistake", s)
        self.assertRegex(s, r"(?m)^- `No check: <mistake>: <the question or route that stopped it>: <why>`$")
        for line in ("Rule added: <id>", "Rule promoted: <id>", "Rule removed: <id>", "Made impossible: <mistake>",
                     "Environment fix: <mistake>"):
            self.assertRegex(s, r"(?m)^- `" + re.escape(line))

    def test_the_co_change_template_has_every_key_a_new_rule_needs_and_no_severity(self):
        block = re.search(r"```toml\n(.*?)```", section(skill(), "The diff: a co-change rule"), re.S).group(1)
        keys = re.findall(r"(?m)^(\w+) = ", block)
        self.assertEqual(keys, ["id", "trigger", "require", "reason", "incident", "flagged", "control"])
        s = flat(section(skill(), "The diff: a co-change rule"))
        self.assertIn("Leave `severity` out: a new rule is `confirm`", s)
        self.assertIn("mech-review.py r0", s)


class TestLifeOfARule(unittest.TestCase):
    """It tells the orchestrator how to promote a rule and remove a misfiring one, neither in the PR where it fires."""

    def life(self):
        return flat(section(skill(), "3. Life of a rule"))

    def test_the_orchestrator_decides_alone(self):
        self.assertIn("The orchestrator adds, promotes and removes rules on its own", self.life())

    def test_how_to_promote(self):
        s = self.life()
        self.assertIn("**Promote**: when the rule has fired on real PRs and every firing was the mistake", s)
        self.assertIn('set `severity = "fail"`', s)

    def test_how_to_remove_a_misfiring_rule(self):
        s = self.life()
        self.assertIn("**Remove a misfiring rule**: a misfire is an entry on a PR that did not make the mistake", s)

    def test_neither_in_the_pr_where_the_rule_fires(self):
        s = self.life()
        self.assertIn("**Neither in the PR where the rule fires.** Promotion and removal each go in a PR of their own", s)


class TestRetroHandOff(unittest.TestCase):
    """The hand-off from retro is written here; retro lives outside this repo."""

    def test_retro_hands_over_one_mistake_at_a_time_and_gets_the_result_line_back(self):
        s = flat(section(skill(), "Input"))
        self.assertIn("The owner's `retro` skill (outside this kit)", s)
        self.assertIn("hands them here one at a time", s)
        self.assertIn("give retro back that mistake's result line", s)

    def test_no_retro_skill_ships_here(self):
        self.assertFalse(os.path.exists(os.path.join(SKILLS, "retro")))


class TestThisRunsMistakes(unittest.TestCase):
    """The #74-#77 run's mistakes, with the result each one gets (the scenario and the eval use the same five)."""

    def test_each_mistake_gets_its_result(self):
        rows = section(skill(), "Worked examples")
        for mistake, result in (("`RecursionError` at deep nesting", "`No check`: an instance"),
                                ("verified one commit", "Process: the `verified-commit.py` gate"),
                                ("left out of the layering test's list", "Made impossible: the list is derived"),
                                ("left the changelog and the two docs alone", "Diff: the co-change rule"),
                                ("failed on macOS only", "Environment: no rule")):
            self.assertRegex(rows, r"(?m)^\| [^|\n]*" + re.escape(mistake) + r"[^|\n]* \| " + re.escape(result))


class TestFinishReport(unittest.TestCase):
    """The finish skill's report carries one line per rule added, promoted or removed in the run."""

    def test_done_and_blocked_templates_carry_the_rule_lines(self):
        text = read("finish", "SKILL.md")
        done = text[text.index("### Done"): text.index("### Blocked")]
        blocked = text[text.index("### Blocked"): text.index("## Verification debt")]
        line = "<one line per rule added, promoted or removed in the run, as mistake-to-check wrote it>"
        self.assertIn(line, done)
        self.assertIn(line, blocked)

    def test_finish_says_where_the_lines_come_from_and_when_there_are_none(self):
        s = flat(read("finish", "SKILL.md"))
        self.assertIn("Rule lines: copy each `Rule added:`, `Rule promoted:` and `Rule removed:` line", s)
        self.assertIn("No rule changed in the run → leave them out", s)


class TestChangelog(unittest.TestCase):
    def test_unreleased_names_the_skill(self):
        with open(os.path.join(_kit.ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            log = f.read()
        unreleased = log[log.index("## Unreleased"): log.index("\n## ", log.index("## Unreleased") + 1)]
        self.assertIn("`mistake-to-check`", unreleased)
        self.assertIn("(#87)", unreleased)


if __name__ == "__main__":
    unittest.main()


class TestEkitsOwnSkillsHandOver(unittest.TestCase):
    """The agent self-invokes mistake-to-check at three moments ekit owns; retro is optional."""

    def test_failure_triage_hands_over_a_red_that_is_an_agent_mistake(self):
        s = flat(section(read("failure-triage", "SKILL.md"), "An agent's mistake"))
        self.assertIn("hand it to the mistake-to-check skill", s)
        self.assertIn("after the class's own next action", s)

    def test_the_review_relay_hands_over_a_process_mistake(self):
        s = flat(section(read("orchestrate-agent", "SKILL.md"), "Review relay"))
        self.assertIn("6. A refusal or finding that shows an agent's process mistake", s)
        self.assertIn("hand it to the mistake-to-check skill", s)

    def test_finish_hands_over_a_fix_round_caused_by_the_agents_own_mistake(self):
        s = flat(section(read("finish", "SKILL.md"), "2. Close the loop"))
        self.assertIn("hand it to the mistake-to-check skill before the report", s)

    def test_the_skill_names_its_three_callers_and_retro_as_optional(self):
        s = flat(section(skill(), "Input"))
        self.assertIn("failure-triage, the orchestrator's review relay and finish", s)
        self.assertIn("No retro run is needed", s)
