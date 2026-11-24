"""The python built-in scanner (#21 review S4, option b): a class with `test*` methods whose bases include a name that is
not `object` and not a non-test class of this file (a base imported from another module, `from _kit import Fixture`)
counts as a test class, as unittest and pytest collect it through that base. A class with `test*` methods and no base,
or only `object`, stays a non-test unless it is named `Test*`, as pytest treats it."""
import json
import os
import subprocess
import tempfile
import unittest

import _kit
from scripts.mech_review import stack

PY = stack.PythonAdapter()


def names(text, path="tests/test_x.py"):
    """the test names the scanner finds in text as the file at path (R2 binds each file's path, #21 review S4b)."""
    return [t.name for t in PY.at(path).test_fns(text)]


class ImportedBase(unittest.TestCase):
    def test_a_class_on_an_imported_base_with_test_methods_is_a_test_class(self):
        self.assertEqual(names("from _kit import Fixture\n\n\nclass X(Fixture):\n    def test_runs(self):\n"
                               "        self.assertEqual(1, 1)\n"), ["X::test_runs"])

    def test_a_dotted_imported_base_counts_too(self):
        self.assertEqual(names("import base\n\n\nclass X(base.Shared):\n    def test_runs(self):\n        pass\n"),
                         ["X::test_runs"])

    def test_a_mixin_with_test_methods_on_an_imported_base_is_guarded(self):
        text = ("from checks import Mixin\n\n\nclass MoreChecks(Mixin):\n    def test_more(self):\n        pass\n\n\n"
                "class Uses(MoreChecks):\n    def test_uses(self):\n        pass\n")
        self.assertEqual(names(text), ["MoreChecks::test_more", "Uses::test_uses"])

    def test_a_plain_helper_class_with_no_test_methods_is_not_a_test_class(self):
        self.assertEqual(names("from _kit import Fixture\n\n\nclass Helper(Fixture):\n    def build(self):\n"
                               "        return 1\n"), [])

    def test_a_class_with_no_base_or_only_object_stays_a_non_test(self):
        self.assertEqual(names("class Helper:\n    def test_x(self):\n        pass\n\n\n"
                               "class Other(object):\n    def test_y(self):\n        pass\n"), [])

    def test_a_base_that_is_a_non_test_class_of_this_file_does_not_count(self):
        self.assertEqual(names("class Base:\n    pass\n\n\nclass Helper(Base):\n    def test_x(self):\n        pass\n"),
                         [])

    def test_the_explicit_cases_stay(self):
        text = ("import unittest\n\n\nclass Case(unittest.TestCase):\n    def test_a(self):\n        pass\n\n\n"
                "class TestNamed:\n    def test_b(self):\n        pass\n")
        self.assertEqual(names(text), ["Case::test_a", "TestNamed::test_b"])


FAKE = "from base import BaseDB\n\n\nclass FakeDB(BaseDB):\n    def test_connection(self):\n        return True\n"


class OnlyInTestFiles(unittest.TestCase):
    """review S4b: the imported-base rule holds only in files pytest collects tests from (test_*.py, *_test.py): a
    fake's `test_connection` in conftest.py or a helper module is no test. The explicit cases hold in every file."""

    def test_a_fake_in_conftest_is_no_test(self):
        self.assertEqual(names(FAKE, "tests/conftest.py"), [])

    def test_a_fake_in_a_helper_module_is_no_test(self):
        for path in ("tests/_kit.py", "tests/helpers.py"):
            with self.subTest(path=path):
                self.assertEqual(names(FAKE, path), [])

    def test_the_explicit_cases_hold_in_a_helper_module(self):
        self.assertEqual(names("import unittest\n\n\nclass Base(unittest.TestCase):\n    def test_a(self):\n"
                               "        pass\n", "tests/_kit.py"), ["Base::test_a"])

    def test_the_rule_holds_in_a_test_file_of_either_name_form(self):
        for path in ("tests/test_db.py", "tests/db_test.py"):
            with self.subTest(path=path):
                self.assertEqual(names(FAKE, path), ["FakeDB::test_connection"])

    def r2(self, files_base, files_head):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = tmp.name
        g = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(g[:3] + ["init", "-q", "-b", "main"], check=True)
        shas = []
        for files in (files_base, files_head):
            for p, text in files.items():
                os.makedirs(os.path.dirname(os.path.join(repo, p)), exist_ok=True)
                with open(os.path.join(repo, p), "w") as f:
                    f.write(text)
            subprocess.run(g + ["add", "-A"], check=True)
            subprocess.run(g + ["commit", "-qm", "c", "--allow-empty"], check=True)
            shas.append(subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip())
        r = _kit.run_cli(["r2", "--repo", repo, "--base", shas[0], "--head", shas[1], "--stack", "python",
                          "--test-paths", "tests/**"])
        return json.loads(r.stdout)["entries"]

    def test_renaming_a_fakes_method_in_conftest_or_a_helper_gives_no_r2_entry(self):
        for path in ("tests/conftest.py", "tests/helpers.py"):
            with self.subTest(path=path):
                self.assertEqual(self.r2({path: FAKE}, {path: FAKE.replace("test_connection", "ping")}), [])

    def test_removing_a_test_of_a_class_on_an_imported_base_in_a_test_file_is_an_r2_fail(self):
        text = ("from _kit import Fixture\n\n\nclass X(Fixture):\n    def test_a(self):\n        self.assertEqual(1, 1)\n"
                "\n    def test_b(self):\n        self.assertEqual(2, 2)\n")
        got = self.r2({"tests/test_x.py": text}, {"tests/test_x.py": text.split("\n    def test_b")[0] + "\n"})
        self.assertEqual([(e["severity"], e["problem"][:30]) for e in got], [("fail", "test fn `X::test_b` removed")])


if __name__ == "__main__":
    unittest.main()
