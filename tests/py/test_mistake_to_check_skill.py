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


if __name__ == "__main__":
    unittest.main()
