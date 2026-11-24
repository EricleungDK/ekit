"""The python built-in scanner (#21 review S4, option b): a class with `test*` methods whose bases include a name that is
not `object` and not a non-test class of this file (a base imported from another module, `from _kit import Fixture`)
counts as a test class, as unittest and pytest collect it through that base. A class with `test*` methods and no base,
or only `object`, stays a non-test unless it is named `Test*`, as pytest treats it."""
import unittest

import _kit  # noqa: F401 - the repo root on sys.path
from scripts.mech_review import stack

PY = stack.PythonAdapter()


def names(text):
    return [t.name for t in PY.test_fns(text)]


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


if __name__ == "__main__":
    unittest.main()
