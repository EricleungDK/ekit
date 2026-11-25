"""The shared TOML loader and key check (tomlfile): what adapter files, the stack plan and co-change rules read through,
each naming a bad file the same way. Called in this process; the TOML is bytes as a file holds them."""
import sys
import unittest
from unittest import mock

import _kit  # noqa: F401 - puts the repo root on sys.path for the import below
from scripts.mech_review import tomlfile


class Bad(ValueError):
    pass


def err(field, msg):
    raise Bad(f"{field}: {msg}")


def load(raw):
    return tomlfile.loads(raw, "the file f.toml at 1a2b", Bad, "a test file")


class Loads(unittest.TestCase):
    def test_a_toml_file_reads_as_its_dict(self):
        self.assertEqual(load(b'format = 1\n[[rule]]\nid = "x"\n'), {"format": 1, "rule": [{"id": "x"}]})

    def test_a_utf8_bom_is_not_part_of_the_text(self):
        self.assertEqual(load(b"\xef\xbb\xbfformat = 1\n"), {"format": 1})

    def test_text_that_is_not_toml_is_named(self):
        with self.assertRaises(Bad) as c:
            load(b"format = \n")
        self.assertEqual(str(c.exception).split(" (")[0], "the file f.toml at 1a2b: not valid TOML: Invalid value")

    def test_bytes_that_are_not_utf8_are_named_with_the_byte(self):
        with self.assertRaises(Bad) as c:
            load(b'id = "\xff"\n')
        self.assertEqual(str(c.exception),
                         "the file f.toml at 1a2b: not valid TOML: not UTF-8 (invalid start byte at byte 6)")

    def test_arrays_nested_too_deep_are_named(self):
        with self.assertRaises(Bad) as c:
            load(b"x = " + b"[" * 100000 + b"]" * 100000 + b"\n")
        self.assertEqual(str(c.exception), "the file f.toml at 1a2b: not valid TOML: arrays or tables nested too deep")


class OldPython(unittest.TestCase):
    def test_no_tomllib_names_the_file_and_the_python_it_needs(self):
        with mock.patch.dict(sys.modules, {"tomllib": None}):
            with self.assertRaises(Bad) as c:
                load(b"format = 1\n")
        self.assertEqual(str(c.exception),
                         "the file f.toml at 1a2b: reading a test file needs python 3.11 or newer (tomllib)")


class Keys(unittest.TestCase):
    def test_known_and_present_keys_pass(self):
        self.assertIsNone(tomlfile.keys({"id": 1, "x": 2}, "rule[0]", ("id", "x"), ("id",), err))

    def test_an_unknown_key_is_named_under_its_table(self):
        with self.assertRaises(Bad) as c:
            tomlfile.keys({"id": 1, "nope": 2}, "rule[0]", ("id",), (), err)
        self.assertEqual(str(c.exception), "rule[0].nope: unknown key")

    def test_a_missing_key_is_named_under_its_table(self):
        with self.assertRaises(Bad) as c:
            tomlfile.keys({}, "rule[0]", ("id",), ("id",), err)
        self.assertEqual(str(c.exception), "rule[0].id: missing")

    def test_a_top_level_key_is_named_bare(self):
        with self.assertRaises(Bad) as c:
            tomlfile.keys({"nope": 1}, "", ("format",), (), err)
        self.assertEqual(str(c.exception), "nope: unknown key")
        with self.assertRaises(Bad) as c:
            tomlfile.keys({}, "", ("format",), ("format",), err)
        self.assertEqual(str(c.exception), "format: missing")


if __name__ == "__main__":
    unittest.main()
