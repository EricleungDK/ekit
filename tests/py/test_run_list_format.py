"""An adapter file's [run.list] (#21, R0's census): its validation at load (adapter_file._list: each field named in the
error) and how the loaded adapter reads a listing (data_adapter.listed: the separator, a failed run, another runner).
In process, on the minirun fixture adapter."""
import os
import unittest

import _kit
from scripts.mech_review import adapter_file

MINIRUN = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "minirun.toml")
LIST = "[run.list]\ncommand = \"mini list\"\npattern = '^(?P<file>\\S+) :: (?P<name>.+)$'\n"


def text(listing=LIST, runners=""):
    with open(MINIRUN) as f:
        t = f.read()
    assert LIST in t
    return t.replace(LIST, listing + runners)


def load(listing=LIST, runners=""):
    return adapter_file.loads(text(listing, runners).encode(), "minirun.toml")


class Validation(unittest.TestCase):
    def refused(self, listing, field, runners=""):
        with self.assertRaises(adapter_file.AdapterFileError) as cm:
            load(listing, runners)
        self.assertIn(f"run.list.{field}" if field else "run.list", str(cm.exception))
        return str(cm.exception)

    def test_command_and_pattern_are_required(self):
        self.refused("[run.list]\npattern = '^(?P<name>.+)$'\n", "command")
        self.refused("[run.list]\ncommand = \"mini list\"\n", "pattern")

    def test_an_unknown_key_is_refused(self):
        self.refused(LIST + "format = \"lines\"\n", "")

    def test_the_command_is_split_as_the_engine_splits_it(self):
        self.assertIn("unbalanced quotes", self.refused(LIST.replace('"mini list"', '"mini \'list"'), "command"))

    def test_the_pattern_needs_a_name_group_and_only_name_and_file(self):
        self.assertIn("no named group `name`", self.refused(LIST.replace("(?P<name>.+)", "(.+)"), "pattern"))
        self.assertIn("the group `kind`", self.refused(LIST.replace("(?P<name>.+)", "(?P<name>.+) (?P<kind>\\w+)"),
                                                       "pattern"))

    def test_a_separator_must_be_text(self):
        self.refused(LIST + "separator = 5\n", "separator")

    def test_a_runner_must_be_text_and_a_run_runner_name(self):
        self.refused(LIST + "runner = 5\n", "runner")
        self.assertIn("no [[run.runner]] name", self.refused(LIST + "runner = \"jest\"\n", "runner"))


class Reading(unittest.TestCase):
    def test_the_listings_separator_splits_a_name_into_the_adapters_parts(self):
        a = load(LIST + "separator = \" > \"\n")
        self.assertEqual(a.listed(0, "tests/a.mini :: Calc > adds\n", "."), [("tests/a.mini", "Calc / adds")])

    def test_without_a_separator_the_adapters_own_joins_the_parts(self):
        a = load()
        self.assertEqual(a.listed(0, "tests/a.mini :: Calc / adds\n", "."), [("tests/a.mini", "Calc / adds")])
        self.assertEqual(a.listed(0, "tests/a.mini :: Calc > adds\n", "."), [("tests/a.mini", "Calc > adds")])

    def test_a_failed_listing_reads_none(self):
        a = load()
        self.assertIsNone(a.listed(1, "tests/a.mini :: adds\n", "."))
        self.assertIsNone(a.listed(0, "build error: unbalanced ( in tests/a.mini\n", "."))  # [run.outcome] build

    def test_a_listing_for_another_runner_gives_no_argv(self):
        runners = "\n[[run.runner]]\nname = \"other\"\nmatch = \"other\"\n\n[[run.runner]]\nname = \"mini\"\n"
        a = load(LIST + "runner = \"other\"\n", runners)
        self.assertEqual(a.list_argv("other test"), ["mini", "list"])
        self.assertIsNone(a.list_argv("mini test"))


if __name__ == "__main__":
    unittest.main()
