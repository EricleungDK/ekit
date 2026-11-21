"""R2's mutation-config rule for python on a python without tomllib (3.9, 3.10): only an edit to the [tool.mutmut]
table counts, as on 3.11+, read from the table's own text. Through the CLI (`r2 --stack python`), tomllib blocked."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _kit

PYPROJECT = "[project]\nname = 'calc'\nversion = '%s'\n\n[tool.mutmut]\nsource_paths = [%s]\n\n[tool.ruff]\nline-length = 100\n"


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True)


class MutationConfigWithoutTomllib(unittest.TestCase):
    def r2(self, before, after, tomllib=False):
        """the mutation-config entries R2 gives for pyproject.toml going from `before` to `after`"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = tmp.name
        git(repo, "init", "-q")
        for i, text in enumerate((before, after)):
            with open(os.path.join(repo, "pyproject.toml"), "w") as f:
                f.write(text)
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", str(i))
        blocked = {} if tomllib else {"tomllib": None}  # None in sys.modules: `import tomllib` raises ImportError
        with mock.patch.dict(sys.modules, blocked):
            r = _kit.run_cli(["r2", "--repo", repo, "--base", "HEAD~1", "--head", "HEAD", "--stack", "python"])
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return [e["problem"] for e in json.loads(r.stdout)["entries"] if e["problem"].startswith("mutation config")]

    def test_a_version_bump_beside_a_mutmut_table_is_no_mutation_config_change(self):
        for tomllib in (False, True):
            with self.subTest(tomllib=tomllib):
                self.assertEqual(self.r2(PYPROJECT % ("1.0", "'src'"), PYPROJECT % ("1.1", "'src'"), tomllib), [])

    def test_an_edit_to_the_mutmut_table_is_one(self):
        for tomllib in (False, True):
            with self.subTest(tomllib=tomllib):
                self.assertEqual(self.r2(PYPROJECT % ("1.0", "'src'"), PYPROJECT % ("1.0", "'src', 'lib'"), tomllib),
                                 ["mutation config changed: [tool.mutmut] in pyproject.toml"])

    def test_a_mutmut_subtable_counts_and_a_table_added_counts(self):
        base = "[project]\nname = 'calc'\n"
        self.assertEqual(self.r2(base, base + "\n[tool.mutmut]\nsource_paths = ['src']\n"),
                         ["mutation config changed: [tool.mutmut] in pyproject.toml"])
        self.assertEqual(self.r2(base + "\n[tool.mutmut.x]\na = 1\n", base + "\n[tool.mutmut.x]\na = 2\n"),
                         ["mutation config changed: [tool.mutmut] in pyproject.toml"])


if __name__ == "__main__":
    unittest.main()
