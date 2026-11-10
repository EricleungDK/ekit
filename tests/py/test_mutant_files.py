"""Reading a mutant's change from the files mutmut writes, instead of asking `mutmut show` once per mutant."""
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants

SRC = """\
import os


def add(a, b=1):
    total = a + b
    return total


class Calc:
    def scale(self, a):
        factor = max(
            2,
            1)
        return a * factor
"""

# what mutmut 3.8.1 writes for SRC: a wrapper with the real name, the original copy, then one copy per mutant
MUTATED = """\
import os
from mutmut.mutation.trampoline import wrap_in_trampoline as _mutmut_mutated, MutantDict
mutants_x_add__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_add__mutmut)
def add(a, b=1):
    total = a + b
    return total


def x_add__mutmut_orig(a, b=1):
    total = a + b
    return total


def x_add__mutmut_1(a, b=2):
    total = a + b
    return total


def x_add__mutmut_2(a, b=1):
    total = a - b
    return total


def x_add__mutmut_3(a, b=1):
    total = a + b
    return None

mutants_x_add__mutmut['x_add__mutmut_1'] = x_add__mutmut_1  # type: ignore


class Calc:
    @_mutmut_mutated(mutants_x_scale)
    def scale(self, a):
        factor = max(
            2,
            1)
        return a * factor

    def x\u01c1Calc\u01c1scale__mutmut_orig(self, a):
        factor = max(
            2,
            1)
        return a * factor

    def x\u01c1Calc\u01c1scale__mutmut_1(self, a):
        factor = max(
            3,
            1)
        return a * factor

    def x\u01c1Calc\u01c1scale__mutmut_2(self, a):
        factor = max(
            1)
        return a * factor

    mutants_x_scale = {}
"""

ADD = "calc.core.x_add__mutmut_"
SCALE = "calc.core.x\u01c1Calc\u01c1scale__mutmut_"


class TestBlocks(unittest.TestCase):
    def test_each_copy_is_its_whole_function_and_nothing_after_it(self):
        blocks = mutants.mutant_blocks(MUTATED)
        self.assertEqual(sorted(blocks), ["x_add__mutmut_1", "x_add__mutmut_2", "x_add__mutmut_3", "x_add__mutmut_orig",
                                          "x\u01c1Calc\u01c1scale__mutmut_1", "x\u01c1Calc\u01c1scale__mutmut_2",
                                          "x\u01c1Calc\u01c1scale__mutmut_orig"])
        self.assertEqual(blocks["x_add__mutmut_3"], ["def x_add__mutmut_3(a, b=1):", "    total = a + b", "    return None"])
        self.assertEqual(blocks["x\u01c1Calc\u01c1scale__mutmut_2"][-1], "        return a * factor")

    def test_the_wrapper_with_the_real_name_is_not_a_copy(self):
        self.assertNotIn("add", mutants.mutant_blocks(MUTATED))

    def test_no_text_is_no_copies(self):
        self.assertEqual(mutants.mutant_blocks(None), {})
        self.assertEqual(mutants.mutant_blocks("x = 1\n"), {})


class TestChange(unittest.TestCase):
    def change(self, name):
        return mutants.mutant_change(mutants.mutant_blocks(MUTATED), name)

    def test_a_changed_body_line_is_an_offset_from_the_def_line(self):
        self.assertEqual(self.change(ADD + "2"), (1, "total = a + b", "total = a - b"))
        self.assertEqual(self.change(ADD + "3"), (2, "return total", "return None"))

    def test_a_changed_default_is_on_the_def_line_under_the_functions_own_name(self):
        self.assertEqual(self.change(ADD + "1"), (0, "def add(a, b=1):", "def add(a, b=2):"))

    def test_a_method_copy_is_read_inside_its_class(self):
        self.assertEqual(self.change(SCALE + "1"), (2, "2,", "3,"))

    def test_a_removed_line_has_nothing_added(self):
        self.assertEqual(self.change(SCALE + "2"), (2, "2,", ""))

    def test_a_change_of_several_lines_is_joined_with_single_spaces(self):
        blocks = {"x_f__mutmut_orig": ["def x_f__mutmut_orig():", "    a = 1", "    b = 2", "    return a"],
                  "x_f__mutmut_1": ["def x_f__mutmut_1():", "    a = 9", "    b = 8", "    return a"]}
        self.assertEqual(mutants.mutant_change(blocks, "m.x_f__mutmut_1"), (1, "a = 1 b = 2", "a = 9 b = 8"))

    def test_a_change_on_the_last_line_and_an_added_last_line(self):
        blocks = {"x_f__mutmut_orig": ["def x_f__mutmut_orig():", "    a = 1", "    return a"],
                  "x_f__mutmut_1": ["def x_f__mutmut_1():", "    a = 1", "    return None"],
                  "x_f__mutmut_2": ["def x_f__mutmut_2():", "    a = 1", "    return a", "    pass"]}
        self.assertEqual(mutants.mutant_change(blocks, "m.x_f__mutmut_1"), (2, "return a", "return None"))
        self.assertEqual(mutants.mutant_change(blocks, "m.x_f__mutmut_2"), (3, "", "pass"))

    def test_repeated_lines_do_not_move_the_change(self):
        body = ["    x += 1"] * 6
        blocks = {"x_f__mutmut_orig": ["def x_f__mutmut_orig():"] + body,
                  "x_f__mutmut_1": ["def x_f__mutmut_1():"] + body[:3] + ["    x -= 1"] + body[4:]}
        self.assertEqual(mutants.mutant_change(blocks, "m.x_f__mutmut_1"), (4, "x += 1", "x -= 1"))

    def test_a_bare_name_with_no_module_is_read_too(self):
        self.assertEqual(mutants.mutant_change(mutants.mutant_blocks(MUTATED), "x_add__mutmut_2"),
                         (1, "total = a + b", "total = a - b"))

    def test_a_function_whose_own_name_holds_mutmuts_marker(self):
        blocks = {"x__mutmut_stop__mutmut_orig": ["def x__mutmut_stop__mutmut_orig(rc):", "    return rc"],
                  "x__mutmut_stop__mutmut_1": ["def x__mutmut_stop__mutmut_1(rc):", "    return None"]}
        self.assertEqual(mutants.mutant_change(blocks, "m.x__mutmut_stop__mutmut_1"), (1, "return rc", "return None"))

    def test_a_name_form_with_no_readable_scope_keeps_its_copy_name(self):
        blocks = {"y_f__mutmut_orig": ["def y_f__mutmut_orig(a=1):", "    return a"],
                  "y_f__mutmut_1": ["def y_f__mutmut_1(a=2):", "    return a"]}
        self.assertEqual(mutants.mutant_change(blocks, "m.y_f__mutmut_1"), (0, "def y_f(a=1):", "def y_f(a=2):"))

    def test_a_mutant_or_function_that_is_not_in_the_file_is_none(self):
        self.assertIsNone(self.change(ADD + "9"))
        self.assertIsNone(self.change("calc.core.x_sub__mutmut_1"))

    def test_a_copy_identical_to_the_original_is_none(self):
        blocks = mutants.mutant_blocks(MUTATED)
        blocks["x_add__mutmut_7"] = ["def x_add__mutmut_7(a, b=1):"] + blocks["x_add__mutmut_orig"][1:]
        self.assertIsNone(mutants.mutant_change(blocks, ADD + "7"))


class TestLineAt(unittest.TestCase):
    def test_the_offset_counts_from_the_def_line_in_the_head_source(self):
        self.assertEqual(mutants.line_at(SRC, ADD + "2", 1, "total = a + b"), 5)
        self.assertEqual(mutants.line_at(SRC, ADD + "1", 0, "def add(a, b=1):"), 4)
        self.assertEqual(mutants.line_at(SRC, SCALE + "1", 2, "2,"), 12)

    def test_the_last_line_of_the_function_is_still_inside(self):
        self.assertEqual(mutants.line_at(SRC, ADD + "3", 2, "return total"), 6)

    def test_an_offset_past_the_function_is_none(self):
        self.assertIsNone(mutants.line_at(SRC, ADD + "3", 3, ""))

    def test_a_change_spanning_lines_matches_on_its_first_line(self):
        self.assertEqual(mutants.line_at(SRC, SCALE + "1", 1, "factor = max( 2, 1)"), 11)

    def test_a_line_that_is_not_the_removed_text_is_none(self):
        self.assertIsNone(mutants.line_at(SRC, ADD + "2", 2, "total = a + b"))
        self.assertIsNone(mutants.line_at("def add(a, b=1):\n\n    return a\n", ADD + "2", 1, "total = a + b"))

    def test_a_pure_addition_needs_no_text_to_match(self):
        self.assertEqual(mutants.line_at(SRC, ADD + "2", 1, ""), 5)

    def test_an_unknown_function_or_no_source_is_none(self):
        self.assertIsNone(mutants.line_at(SRC, "calc.core.x_sub__mutmut_1", 0, ""))
        self.assertIsNone(mutants.line_at(None, ADD + "1", 0, ""))


class TestMutantFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.crate = self.tmp.name
        os.makedirs(os.path.join(self.crate, "mutants", "src", "calc"))
        self.path = "src/calc/core.py"
        with open(os.path.join(self.crate, "mutants", self.path), "w", encoding="utf-8") as f:
            f.write(MUTATED)
        self.meta({ADD + "1": 1, ADD + "2": 0, SCALE + "1": 0})

    def meta(self, keys, path=None):
        with open(os.path.join(self.crate, "mutants", (path or self.path) + ".meta"), "w") as f:
            json.dump({"exit_code_by_key": keys} if keys is not None else ["not", "a", "dict"], f)

    def test_a_mutant_is_found_through_the_meta_file_that_lists_it(self):
        files = mutants.MutantFiles(self.crate, ["src/other.py", self.path])
        self.assertEqual(files.change(ADD + "2"), (self.path, 1, "total = a + b", "total = a - b"))
        self.assertEqual(files.change(SCALE + "1"), (self.path, 2, "2,", "3,"))

    def test_a_mutant_no_meta_file_lists_is_none(self):
        self.assertIsNone(mutants.MutantFiles(self.crate, [self.path]).change(ADD + "3"))

    def test_no_mutants_dir_or_an_unreadable_meta_is_none_not_a_crash(self):
        self.assertIsNone(mutants.MutantFiles(os.path.join(self.crate, "nowhere"), [self.path]).change(ADD + "2"))
        self.meta(None)
        self.assertIsNone(mutants.MutantFiles(self.crate, [self.path]).change(ADD + "2"))
        with open(os.path.join(self.crate, "mutants", self.path + ".meta"), "w") as f:
            f.write("{")
        self.assertIsNone(mutants.MutantFiles(self.crate, [self.path]).change(ADD + "2"))
        for shape in ({}, {"exit_code_by_key": None}):
            with open(os.path.join(self.crate, "mutants", self.path + ".meta"), "w") as f:
                json.dump(shape, f)
            self.assertIsNone(mutants.MutantFiles(self.crate, [self.path]).change(ADD + "2"), shape)

    def test_an_unreadable_meta_does_not_hide_the_next_files(self):
        other = "src/calc/other.py"
        self.meta(None, path=other)
        self.assertEqual(mutants.MutantFiles(self.crate, [other, self.path]).change(ADD + "2")[0], self.path)

    def test_a_listed_mutant_whose_copy_is_missing_is_none(self):
        self.meta({ADD + "8": 0})
        self.assertIsNone(mutants.MutantFiles(self.crate, [self.path]).change(ADD + "8"))

    def test_each_mutated_file_is_read_once(self):
        files = mutants.MutantFiles(self.crate, [self.path])
        files.change(ADD + "2")
        os.remove(os.path.join(self.crate, "mutants", self.path))
        os.remove(os.path.join(self.crate, "mutants", self.path + ".meta"))
        self.assertEqual(files.change(ADD + "1"), (self.path, 0, "def add(a, b=1):", "def add(a, b=2):"))


if __name__ == "__main__":
    unittest.main()
