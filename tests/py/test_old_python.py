"""The engine runs on the python a user's machine has. tomllib came with 3.11: only reading a crate's
.cargo/mutants.toml needs it, so nothing else may ask for it."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _kit
from scripts.mech_review import gitio, mutants


class TestWithoutTomllib(unittest.TestCase):
    def test_the_engine_and_the_comment_poster_load_on_a_python_without_tomllib(self):
        code = ("import sys; sys.modules['tomllib'] = None; sys.path.insert(0, sys.argv[1]); "
                "import mech_review.cli, mech_review.merge")
        r = subprocess.run([sys.executable, "-I", "-c", code, _kit.SCRIPTS], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stderr), (0, ""))


class TestCargoConfig(unittest.TestCase):
    def config(self, text):
        with tempfile.TemporaryDirectory() as crate:
            if text is not None:
                os.makedirs(os.path.join(crate, ".cargo"))
                with open(os.path.join(crate, ".cargo", "mutants.toml"), "w") as f:
                    f.write(text)
            with mock.patch.dict(sys.modules, {"tomllib": None}):
                return mutants.cargo_config(crate)

    def test_a_crate_without_the_file_gets_cargo_mutants_defaults(self):
        self.assertEqual(self.config(None), (5.0, 20.0))

    def test_a_config_file_is_a_stated_error_not_a_traceback(self):
        with self.assertRaises(gitio.Die) as e:
            self.config("timeout_multiplier = 3.0\n")
        self.assertEqual(str(e.exception), "reading .cargo/mutants.toml needs python 3.11 or newer (tomllib)")


if __name__ == "__main__":
    unittest.main()
