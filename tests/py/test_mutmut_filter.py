import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants

SRC = """\
import os


def add(a, b):
    return a + b


def sub(a, b):
    c = a - b
    return c


class Calc:
    def add(self, a, b):
        return a + b

    def neg(self, a):
        return -a


class Other:
    def add(self, a, b):
        return a + b + 0
"""


class TestScopeSpan(unittest.TestCase):
    def test_a_module_function_spans_its_def_to_its_last_line(self):
        self.assertEqual(mutants.scope_span(SRC, "calc.core.x_add__mutmut_1"), (4, 5))
        self.assertEqual(mutants.scope_span(SRC, "calc.core.x_sub__mutmut_3"), (8, 10))

    def test_a_method_is_found_inside_its_own_class(self):
        self.assertEqual(mutants.scope_span(SRC, "calc.core.xǁCalcǁadd__mutmut_1"), (14, 15))
        self.assertEqual(mutants.scope_span(SRC, "calc.core.xǁOtherǁadd__mutmut_1"), (22, 23))
        self.assertEqual(mutants.scope_span(SRC, "calc.core.xǁCalcǁneg__mutmut_1"), (17, 18))

    def test_blank_lines_after_a_function_are_not_part_of_it(self):
        src = "def one(): return 1\n\n\ndef two():\n    return 2\n\n\n"
        self.assertEqual(mutants.scope_span(src, "m.x_one__mutmut_1"), (1, 1))
        self.assertEqual(mutants.scope_span(src, "m.x_two__mutmut_1"), (4, 5))

    def test_an_unknown_function_class_or_name_form_is_none(self):
        for name in ("calc.core.x_mul__mutmut_1", "calc.core.xǁNopeǁadd__mutmut_1", "calc.core.weird__mutmut_1"):
            self.assertIsNone(mutants.scope_span(SRC, name), name)

    def test_locate_still_finds_the_line_inside_the_span(self):
        self.assertEqual(mutants.locate(SRC, "calc.core.x_sub__mutmut_1", "c = a - b"), 9)
        self.assertEqual(mutants.locate(SRC, "calc.core.xǁOtherǁadd__mutmut_1", "return a + b + 0"), 23)
        self.assertIsNone(mutants.locate(SRC, "calc.core.x_add__mutmut_1", "c = a - b"))  # sub's line is not in add
        self.assertIsNone(mutants.locate(SRC, "calc.core.x_mul__mutmut_1", "return a + b"))

    def test_locate_does_not_look_before_the_function(self):
        self.assertIsNone(mutants.locate(SRC, "calc.core.x_sub__mutmut_1", "return a + b"))  # add's line, above sub
        src = "x = 1\ndef f():\n    return x\n"
        self.assertIsNone(mutants.locate(src, "m.x_f__mutmut_1", "x = 1"))  # the line right above the def


class TestOutsideDiff(unittest.TestCase):
    """Whether a missed mutant can be settled as outside the diff from its name alone."""
    SOURCES = {"src/calc/core.py": SRC}

    def outside(self, name, lines, sources=None):
        return mutants.outside_diff(name, sources or self.SOURCES, {"src/calc/core.py": [(n, "") for n in lines]})

    def test_a_function_with_no_changed_line_is_outside(self):
        self.assertTrue(self.outside("calc.core.x_add__mutmut_1", [9]))

    def test_a_changed_line_anywhere_in_the_function_keeps_it(self):
        for line in (8, 9, 10):
            self.assertFalse(self.outside("calc.core.x_sub__mutmut_1", [line]), line)

    def test_the_lines_just_around_the_function_do_not_count(self):
        self.assertTrue(self.outside("calc.core.x_sub__mutmut_1", [7, 11]))

    def test_a_method_is_judged_by_its_own_class(self):
        self.assertFalse(self.outside("calc.core.xǁOtherǁadd__mutmut_1", [23]))
        self.assertTrue(self.outside("calc.core.xǁCalcǁadd__mutmut_1", [23]))

    def test_a_name_that_cannot_be_read_is_not_settled_here(self):
        self.assertIs(self.outside("calc.core.weird__mutmut_1", [9]), False)

    def test_a_function_found_in_no_changed_file_is_not_settled_here(self):
        self.assertIs(self.outside("calc.core.x_mul__mutmut_1", [9]), False)
        self.assertIs(mutants.outside_diff("calc.core.x_add__mutmut_1", {}, {}), False)

    def test_a_file_without_the_function_does_not_end_the_search(self):
        sources = {"src/a.py": "def other():\n    return 1\n", "src/calc/core.py": SRC}
        self.assertIs(mutants.outside_diff("calc.core.x_add__mutmut_1", sources, {"src/calc/core.py": [(9, "")]}), True)

    def test_with_several_files_one_touched_copy_keeps_it(self):
        sources = {"src/calc/core.py": SRC, "src/calc/more.py": "def add(a, b):\n    return b + a\n"}
        changed = {"src/calc/more.py": [(2, "")], "src/calc/core.py": [(9, "")]}
        self.assertFalse(mutants.outside_diff("calc.more.x_add__mutmut_1", sources, changed))
        self.assertTrue(mutants.outside_diff("calc.core.xǁCalcǁneg__mutmut_1", sources, changed))

    def test_a_file_with_no_changed_lines_recorded_is_outside(self):
        self.assertTrue(mutants.outside_diff("calc.core.x_add__mutmut_1", self.SOURCES, {}))


if __name__ == "__main__":
    unittest.main()
