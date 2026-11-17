"""R3 for python: the files mutmut copies into its mutants/ sandbox besides the sources (issue #7).

mutmut 3.8.1 copies only source_paths, its fixed defaults (tests/, test/, setup.cfg, pyproject.toml, the lock files,
root test*.py) and `also_copy`. Tests that read a tracked docs/ file or load scripts/x.py by path then fail the
baseline inside mutants/. R3 lists the other tracked top-level entries as also_copy."""
import contextlib
import io
import os
import subprocess
import tempfile
import tomllib
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants
from scripts.mech_review.gitio import Review, merge_base
from scripts.mech_review.stack import ADAPTERS


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                          capture_output=True, text=True).stdout


def write(root, files):
    for path, text in files.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)


# a repo with every kind of top-level entry: sources, mutmut's defaults, files tests read, odd names
TRACKED = {
    "pyproject.toml": "[project]\nname = 'calc'\n",
    "setup.cfg": "", "uv.lock": "", "poetry.lock": "", "Pipfile.lock": "", "pdm.lock": "",
    "test_root.py": "", "tests_helper.py": "",
    "tests/test_core.py": "", "test/test_more.py": "",
    "src/calc/core.py": "def add(a, b):\n    return a + b\n",
    "mutants/stale.py": "",
    "README.md": "", "conftest.py": "", "pytest.ini": "",
    "docs/guide.md": "# guide\n", "scripts/x.py": "X = 1\n",
    'my "odd" file.txt': "", "back\\slash.txt": "",
}
UNTRACKED = {".venv/bin/python": "", "notes.txt": "", "docs/draft.md": ""}


class AlsoCopy(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name
        git(self.repo, "init", "-q")
        write(self.repo, TRACKED)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "head")
        self.head = git(self.repo, "rev-parse", "HEAD").strip()
        write(self.repo, UNTRACKED)

    def test_lists_tracked_top_level_entries_minus_sources_mutants_and_mutmut_defaults(self):
        self.assertEqual(mutants.also_copy(self.repo, self.head, ".", ["src"]),
                         ["README.md", "back\\slash.txt", "conftest.py", "docs", 'my "odd" file.txt', "pytest.ini",
                          "scripts"])

    def test_a_root_source_file_is_left_out_like_a_source_dir(self):
        self.assertEqual(mutants.also_copy(self.repo, self.head, ".", ["src", "scripts", "README.md"]),
                         ["back\\slash.txt", "conftest.py", "docs", 'my "odd" file.txt', "pytest.ini"])

    def test_reads_the_tree_at_head_not_the_working_tree(self):
        write(self.repo, {"later/new.md": ""})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "later")
        self.assertNotIn("later", mutants.also_copy(self.repo, self.head, ".", ["src"]))

    def test_a_repo_path_inside_the_repo_lists_from_the_root_all_the_same(self):
        self.assertEqual(mutants.also_copy(os.path.join(self.repo, "docs"), self.head, ".", ["src"]),
                         ["README.md", "back\\slash.txt", "conftest.py", "docs", 'my "odd" file.txt', "pytest.ini",
                          "scripts"])

    def test_a_name_that_is_not_utf8_is_left_out_since_no_toml_file_can_hold_it(self):
        blob = git(self.repo, "hash-object", "-w", os.devnull).strip()  # empty blob; the name goes in via the index only
        subprocess.run([b"git", b"-C", self.repo.encode(), b"update-index", b"--add", b"--cacheinfo",
                        b"100644," + blob.encode() + b",bad\xff.txt"], check=True, capture_output=True)
        git(self.repo, "commit", "-q", "-m", "bad name")
        head = git(self.repo, "rev-parse", "HEAD").strip()
        self.assertEqual(mutants.also_copy(self.repo, head, ".", ["src"]),
                         ["README.md", "back\\slash.txt", "conftest.py", "docs", 'my "odd" file.txt', "pytest.ini",
                          "scripts"])

    def test_entries_are_relative_to_the_project_dir(self):
        write(self.repo, {"pkg/pyproject.toml": "", "pkg/src/calc/core.py": "", "pkg/tests/test_core.py": "",
                          "pkg/data/table.csv": "", "pkg/NOTES.md": "", "pkg/test_x.py": ""})
        git(self.repo, "add", "pkg")
        git(self.repo, "commit", "-q", "-m", "pkg")
        head = git(self.repo, "rev-parse", "HEAD").strip()
        self.assertEqual(mutants.also_copy(self.repo, head, "pkg", ["src"]), ["NOTES.md", "data"])


class Table(unittest.TestCase):
    def test_also_copy_goes_into_the_table_beside_source_paths_and_only_mutate(self):
        text = mutants.add_mutmut_table("[project]\nname = 'x'\n", ["src"], ["src/calc/core.py"], ["docs", "scripts"])
        self.assertEqual(tomllib.loads(text)["tool"]["mutmut"],
                         {"source_paths": ["src"], "only_mutate": ["src/calc/core.py"], "also_copy": ["docs", "scripts"]})

    def test_odd_names_stay_valid_toml_and_read_back_unchanged(self):
        names = ["my file.md", 'say "hi".txt', "back\\slash.txt", "tab\there.txt", "del\x7fname.txt", "café 😀.md"]
        text = mutants.add_mutmut_table("", ["src"], ["src/a.py"], names)
        self.assertEqual(tomllib.loads(text)["tool"]["mutmut"]["also_copy"], names)

    def test_the_repos_own_mutmut_table_is_still_not_overridden(self):
        self.assertIsNone(mutants.add_mutmut_table("[tool.mutmut]\nsource_paths = ['src']\n", ["src"], ["src/a.py"],
                                                   ["docs"]))


class ConfigMutmutReads(unittest.TestCase):
    """R3 end to end with mutmut replaced: the [tool.mutmut] table in the worktree when mutmut first runs."""

    def r3(self, files, change, project_dir="."):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = tmp.name
        git(repo, "init", "-q")
        write(repo, files)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        write(repo, {change: "def add(a, b):\n    return a - b\n"})
        git(repo, "commit", "-q", "-am", "head")
        write(repo, {os.path.join(project_dir, "notes.txt"): ""})  # untracked in the caller's checkout
        tables = []

        def fake(argv, cwd, timeout):
            if argv[1] == "--version":
                return 0, "mutmut, version 3.8.1"
            with open(os.path.join(cwd, "pyproject.toml"), "rb") as f:
                tables.append(tomllib.load(f)["tool"]["mutmut"])
            return 1, "failed to collect stats. runner returned 1\n"  # stop at the first run: the table is all we need

        base, head, mb = merge_base(repo, "HEAD~1", "HEAD")
        rv = Review(repo, mb, head, ADAPTERS["python"](), [os.path.join(project_dir, "tests/**")], project_dir)
        with contextlib.redirect_stderr(io.StringIO()):
            mutants.run(rv, None, 5, None, None, fake)
        return tables

    def test_the_table_lists_the_tracked_files_tests_read_besides_the_sources(self):
        tables = self.r3({"pyproject.toml": "[project]\nname = 'calc'\n", "src/calc/core.py": "def add(a, b):\n    return a + b\n",
                          "tests/test_core.py": "", "docs/guide.md": "", "scripts/x.py": "", "README.md": ""},
                         "src/calc/core.py")
        self.assertEqual(tables, [{"source_paths": ["src"], "only_mutate": ["src/calc/core.py"],
                                   "also_copy": ["README.md", "docs", "scripts"]}])

    def test_with_a_project_dir_the_list_is_that_dirs_entries_relative_to_it(self):
        tables = self.r3({"pkg/pyproject.toml": "[project]\nname = 'calc'\n",
                          "pkg/src/calc/core.py": "def add(a, b):\n    return a + b\n", "pkg/tests/test_core.py": "",
                          "pkg/config/app.example.yaml": "", "docs/top.md": ""},
                         "pkg/src/calc/core.py", project_dir="pkg")
        self.assertEqual(tables, [{"source_paths": ["src"], "only_mutate": ["src/calc/core.py"], "also_copy": ["config"]}])


if __name__ == "__main__":
    unittest.main()
