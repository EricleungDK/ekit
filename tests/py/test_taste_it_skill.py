"""taste-it and finish skill text is behaviour for agents: each test pins one outcome of #60 (seed scenarios from what
the user asked for; the finish report's features line)."""
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


def done_branch():
    """finish's `### Done` branch: its template's `## Finish: done` line would end a heading-based section"""
    text = read("finish", "SKILL.md")
    return text[text.index("### Done"): text.index("### Blocked")]


def flat(text):
    return re.sub(r"\s+", " ", text)


def seed():
    return flat(section(read("taste-it", "SKILL.md"), "7. Seed from what the user asked for"))


class TestFeatureField(unittest.TestCase):
    def test_the_scenario_md_field_list_has_the_feature_marker_as_the_runner_reads_it(self):
        fields = section(read("taste-it", "SKILL.md"), "2. Scenarios")
        fields = fields[fields.index("`SCENARIO.md` fields:"):]
        fields = fields[: fields.index("\n\n")]
        self.assertRegex(fields, r"(?m)^- \*\*feature\*\*: .*`- feature: <name>`")
        self.assertIn("seeded", flat(fields))


class TestSeeding(unittest.TestCase):
    def test_the_description_says_when_to_seed(self):
        head = read("taste-it", "SKILL.md").split("---")[1]
        self.assertIn("seed scenarios", head)

    def test_it_reads_the_description_and_every_saved_story(self):
        s = seed()
        self.assertIn("the user's description", s)
        for where in ("issues", "specs", "PRDs", "notes in the repo"):
            self.assertIn(where, s)

    def test_it_proposes_one_scenario_per_feature_and_shows_each_ones_wording(self):
        s = seed()
        self.assertIn("one scenario per described feature", s)
        self.assertIn("Show the user each one's wording", s)

    def test_only_approved_ones_are_written_a_rejected_one_dropped_a_reworded_one_as_reworded(self):
        s = seed()
        self.assertIn("Write only the approved ones", s)
        self.assertIn("A rejected one is dropped", s)
        self.assertIn("A reworded one is written as reworded, never as first proposed", s)

    def test_the_proposal_shows_the_feature_name_with_the_wording(self):
        self.assertIn("its `- feature:` name", seed())

    def test_why_each_seeded_scenario_failed_is_read_and_a_broken_one_repaired(self):
        s = seed()
        self.assertIn("Read why it failed: the reason on its `SEEDED ✓` line, and its transcript", s)
        self.assertIn("fails for another reason than the missing feature", s)
        self.assertIn("is broken: repair it, run `RUN seeded <id>` again", s)

    def test_a_seeding_task_reports_with_the_done_branch_and_its_own_bar(self):
        s = seed()
        self.assertIn("A seeding task (scenarios written, no feature built) reports with the finish skill's Done branch", s)
        bar = flat(section(read("taste-it", "SKILL.md"), "4. Quality bar"))
        self.assertIn("A seeding task (§7) has its own bar", bar)

    def test_the_seeding_bar_holds_in_an_app_whose_other_features_already_work(self):
        # an app with a marked working feature prints 1 of 2 after one more is seeded: `0 of M` cannot be the bar
        for text in (flat(section(read("taste-it", "SKILL.md"), "4. Quality bar")), flat(read("finish", "scenarios.md"))):
            self.assertIn('none of the newly seeded features works: N as before the seeding, M grown by the features seeded', text)
            self.assertIn("`0 of M` in a new app", text)
            self.assertNotIn("print `0 of M features working`", text)
            self.assertNotIn("prints `0 of M features working`", text)

    def test_answers_given_with_the_request_are_the_answers(self):
        self.assertIn("Answers given with the request count", seed())

    def test_each_seeded_scenario_is_a_run_py_with_the_feature_marker(self):
        s = seed()
        self.assertIn("`run.py`", s)
        self.assertIn("`- feature: <name>`", s)

    def test_each_one_is_run_right_after_it_is_written_and_a_pass_checks_nothing_yet(self):
        s = seed()
        self.assertIn("Right after writing each one: `RUN seeded <id>`", s)
        self.assertIn("`SEEDED ✓ <id>`", s)
        self.assertIn("`CHECKS NOTHING YET <id>`", s)
        self.assertIn('report it as "checks nothing yet"', s)
        self.assertIn("not seeded until `RUN seeded <id>` fails it", s)

    def test_the_run_table_has_the_seeded_check_with_each_exit(self):
        t = flat(section(read("taste-it", "SKILL.md"), "3. Run"))
        self.assertRegex(t, r"\| `RUN seeded <id>` \|[^|]*`SEEDED ✓ <id>[:`][^|]*`CHECKS NOTHING YET <id>`[^|]*\|")
        self.assertIn("`N of M features working`", t)

    def test_the_seeded_row_names_every_error_and_the_line_with_its_reason(self):
        row = [x for x in read("taste-it", "SKILL.md").splitlines() if x.startswith("| `RUN seeded <id>` |")][0]
        self.assertIn("`SEEDED ✓ <id>: fails on the repo as it is: <reason>: <its last line>`", row)
        for error in ("no or an empty `- feature:` line", "a feature line in another form", "two or more run files",
                      "a write into the repo"):
            self.assertIn(error, row)


class TestFinishFeaturesLine(unittest.TestCase):
    def test_the_done_template_has_the_features_line(self):
        self.assertRegex(done_branch(), r"(?m)^<the `N of M features working` line `RUN check` printed, as printed>$")

    def test_the_line_is_copied_from_check_never_counted_and_left_out_when_check_prints_none(self):
        for text in (flat(done_branch()), flat(read("finish", "scenarios.md"))):
            self.assertIn("`N of M features working`", text)
            self.assertIn("`RUN check`", text)
            self.assertIn("never count by hand", text)
            self.assertIn("leave the line out", text)

    def test_a_feature_not_working_is_not_done_for_a_task_that_claims_it_built(self):
        self.assertIn("N below M = not done for a task that claims the features built", flat(read("finish", "scenarios.md")))

    def test_a_seeding_task_is_done_with_every_scenario_seeded_and_none_working(self):
        s = flat(read("finish", "scenarios.md"))
        self.assertIn("A seeding task (taste-it §7: scenarios written, no feature built) is done when", s)
        self.assertIn("each written scenario's last `RUN seeded <id>` is `SEEDED ✓`", s)

    def test_the_features_line_goes_in_either_branch(self):
        self.assertIn("in either branch", flat(read("finish", "scenarios.md")))
        text = read("finish", "SKILL.md")
        blocked = text[text.index("### Blocked"): text.index("## Verification debt")]
        self.assertRegex(blocked, r"(?m)^<the `N of M features working` line `RUN check` printed, as printed>$")


if __name__ == "__main__":
    unittest.main()
