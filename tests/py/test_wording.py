import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review.stack import ADAPTERS


class TestIgnoredText(unittest.TestCase):
    """The R2 problem line for a skipped test speaks the stack's own language."""

    def test_python_names_skip_and_xfail_not_a_rust_attribute(self):
        self.assertEqual(ADAPTERS["python"]().ignored_text("test_div"), "test `test_div` marked skipped (skip or xfail)")

    def test_rust_names_the_ignore_attribute(self):
        self.assertEqual(ADAPTERS["rust"]().ignored_text("parses"), "test `parses` marked #[ignore]")

    def test_ts_names_skip_todo_and_the_x_prefix(self):
        self.assertEqual(ADAPTERS["ts"]().ignored_text("adds"), "test `adds` marked skipped (skip, todo or x-prefixed)")


if __name__ == "__main__":
    unittest.main()
