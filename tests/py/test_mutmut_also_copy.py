"""R3 for python: the files mutmut copies into its mutants/ sandbox besides the sources (issue #7).

mutmut 3.8.1 copies only source_paths, its fixed defaults (tests/, test/, setup.cfg, pyproject.toml, the lock files,
root test*.py) and `also_copy`. Tests that read a tracked docs/ file or load scripts/x.py by path then fail the
baseline inside mutants/. R3 lists the other tracked top-level entries as also_copy."""
import contextlib
import io
import os
import re
import subprocess
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants
from scripts.mech_review.gitio import Review, merge_base
from scripts.mech_review.stack import ADAPTERS


def tomllib():
    """tomllib where this python has it (3.11+), else None: the text R3 writes is asserted on every version, and read
    back as TOML as well where a reader exists."""
    try:
        import tomllib as t
    except ImportError:
        return None
    return t


def reads_back(test, text, table):
    """`text` is TOML whose [tool.mutmut] is `table`, where this python can read TOML"""
    t = tomllib()
    if t:
        test.assertEqual(t.loads(text)["tool"]["mutmut"], table)


def mutmut_block(text):
    """the [tool.mutmut] table R3 appended: from its header to the end"""
    return text[text.index("[tool.mutmut]\n"):]


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                          capture_output=True, text=True).stdout


# a name Windows will not hold in its filesystem (", a backslash, a control char, a trailing dot or space): such a
# name goes into the repo through the index only, which is all also_copy reads (the tree at a commit)
REFUSED = re.compile(r'[\x00-\x1f"*:<>?\\|]|[ .](/|$)') if os.name == "nt" else re.compile(r"(?!)")


def commit(repo, files, msg):
    """Commit `files` ({path: text}) in `repo`: on disk where the OS can hold the name, else in the index alone."""
    on_disk = [p for p in files if not REFUSED.search(p)]
    write(repo, {p: files[p] for p in on_disk})
    if on_disk:
        git(repo, "add", "--", *on_disk)
    for path, text in files.items():
        if REFUSED.search(path):
            blob = subprocess.run(["git", "-C", repo, "hash-object", "-w", "--stdin"], input=text, check=True,
                                  capture_output=True, text=True).stdout.strip()
            # Git for Windows refuses such a path in the index unless told the repo is not checked out on NTFS
            git(repo, "-c", "core.protectNTFS=false", "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
    git(repo, "-c", "core.protectNTFS=false", "commit", "-q", "-m", msg)


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
        commit(self.repo, TRACKED, "head")
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

    def test_a_name_with_a_tab_or_a_leading_space_is_listed_whole(self):
        commit(self.repo, {"tab\there.txt": "", " lead.txt": "", "docs/a\tb.md": ""}, "odd")
        head = git(self.repo, "rev-parse", "HEAD").strip()
        self.assertEqual(mutants.also_copy(self.repo, head, ".", ["src"]),
                         [" lead.txt", "README.md", "back\\slash.txt", "conftest.py", "docs", 'my "odd" file.txt',
                          "pytest.ini", "scripts", "tab\there.txt"])

    def test_a_name_that_is_not_utf8_is_left_out_since_no_toml_file_can_hold_it(self):
        blob = git(self.repo, "hash-object", "-w", os.devnull).strip()  # empty blob; the name goes in via the index only
        # on stdin, not in argv: Windows passes a command line as text, which no byte 0xff is
        subprocess.run(["git", "-C", self.repo, "update-index", "--index-info"],
                       input=b"100644 blob " + blob.encode() + b"\tbad\xff.txt\n", check=True, capture_output=True)
        git(self.repo, "-c", "core.protectNTFS=false", "commit", "-q", "-m", "bad name")
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


class Symlinks(unittest.TestCase):
    """mutmut copies a dir with copytree, following links: a dangling link inside raises, a link to an ancestor dir
    recurses until ELOOP. An entry is kept only when each link in it points, inside the project dir and through no
    other link, at a tracked regular file. The links go in through the index (a tree entry is all also_copy reads)."""

    def repo_with_links(self, files, links):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = tmp.name
        git(repo, "init", "-q")
        write(repo, files)
        git(repo, "add", "-A")
        git(repo, "update-index", "--chmod=+x", "--", *[p for p in files if p.endswith(".sh")])
        for path, target in links.items():
            blob = subprocess.run(["git", "-C", repo, "hash-object", "-w", "--stdin"], input=target, check=True,
                                  capture_output=True, text=True).stdout.strip()
            git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},{path}")
        git(repo, "commit", "-q", "-m", "head")
        return repo, git(repo, "rev-parse", "HEAD").strip()

    FILES = {"pyproject.toml": "", "src/a.py": "", "README.md": "", "docs/guide.md": "", "good/a.txt": "",
             "deep/sub/f.txt": "", "todir/a.txt": "", "abs/a.txt": "", "slash/a.txt": "", "chain/a.txt": "",
             "viafile/a.txt": "", "vialink/a.txt": "", "loop/a.txt": "", "tool.sh": "", "dotafter/a.txt": "",
             "dotsafter/a.txt": ""}
    LINKS = {
        "docs/latest": "../build/html",              # dangling: build/ is not tracked
        "loop/self": "..",                           # an ancestor dir
        "good/readme": "../README.md",               # a tracked file: kept
        "good/readme2": "..//README.md",             # the same, with an empty step
        "good/deepfile": "../deep/sub/f.txt",        # a tracked file through tracked dirs: kept
        "exec/run": "../tool.sh",                    # a tracked executable file: kept
        "deep/f": "./sub/f.txt",                     # a tracked file below: kept
        "todir/d": "../deep",                        # a dir
        "abs/root": "/a.txt",                        # absolute (abs/a.txt, the same name relative, is tracked)
        "slash/readme": "../README.md/",             # a trailing slash wants a dir
        "chain/readme": "../good/readme",            # a link to a link
        "viafile/readme": "../README.md/../README.md",  # through a file
        "dotafter/readme": "../README.md/.",         # a `.` after a file: ENOTDIR on disk
        "dotsafter/readme": "../README.md/./.",      # the same, twice
        "good/dotdir": "../deep/./sub/f.txt",        # a `.` after a dir: kept
        "vialink/f": "../todir/d/sub/f.txt",          # through a link to a dir
        "toplink": "README.md",                      # top-level link to a tracked file: kept
        "topdangling": "nothing",                    # top-level dangling link
        "topdir": "docs",                            # top-level link to a dir
    }

    def test_only_entries_whose_links_all_reach_a_tracked_file_are_kept(self):
        repo, head = self.repo_with_links(self.FILES, self.LINKS)
        self.assertEqual(mutants.also_copy(repo, head, ".", ["src"]), ["README.md", "deep", "exec", "good", "tool.sh", "toplink"])

    def test_a_dot_after_a_file_in_a_link_target_drops_its_entry(self):
        repo, head = self.repo_with_links({"pyproject.toml": "", "src/a.py": "", "README.md": "", "docs/guide.md": "",
                                           "site/a.txt": "", "deep/sub/f.txt": "", "good/a.txt": ""},
                                          {"docs/bad": "../README.md/.", "site/bad": "../README.md/./.",
                                           "good/dotdir": "../deep/./sub/f.txt"})
        self.assertEqual(mutants.also_copy(repo, head, ".", ["src"]), ["README.md", "deep", "good"])

    def test_a_bad_link_deep_inside_an_entry_drops_the_whole_entry(self):
        repo, head = self.repo_with_links({"pyproject.toml": "", "src/a.py": "", "README.md": "",
                                           "docs/api/v1/guide.md": "", "site/a/b/c.txt": ""},
                                          {"docs/api/v1/latest": "../../../build/html", "site/a/b/readme": "../../../README.md"})
        self.assertEqual(mutants.also_copy(repo, head, ".", ["src"]), ["README.md", "site"])

    def test_a_link_that_leaves_the_project_dir_drops_its_entry(self):
        repo, head = self.repo_with_links({"README.md": "", "pkg/pyproject.toml": "", "pkg/src/a.py": "",
                                           "pkg/notes/a.txt": "", "pkg/up/a.txt": "", "pkg/NOTES.md": ""},
                                          {"pkg/up/readme": "../../README.md", "pkg/notes/n": "../NOTES.md"})
        self.assertEqual(mutants.also_copy(repo, head, "pkg", ["src"]), ["NOTES.md", "notes"])


class Table(unittest.TestCase):
    def test_also_copy_goes_into_the_table_beside_source_paths_and_only_mutate(self):
        text = mutants.add_mutmut_table("[project]\nname = 'x'\n", ["src"], ["src/calc/core.py"], ["docs", "scripts"])
        self.assertEqual(text, "[project]\nname = 'x'\n\n[tool.mutmut]\nsource_paths = [\"src\"]\n"
                               "only_mutate = [\"src/calc/core.py\"]\nalso_copy = [\"docs\", \"scripts\"]\n")
        reads_back(self, text, {"source_paths": ["src"], "only_mutate": ["src/calc/core.py"],
                                "also_copy": ["docs", "scripts"]})

    def test_odd_names_stay_valid_toml_and_read_back_unchanged(self):
        names = ["my file.md", 'say "hi".txt', "back\\slash.txt", "tab\there.txt", "del\x7fname.txt", "café 😀.md"]
        text = mutants.add_mutmut_table("", ["src"], ["src/a.py"], names)
        self.assertEqual(text, '[tool.mutmut]\nsource_paths = ["src"]\nonly_mutate = ["src/a.py"]\nalso_copy = '
                               '["my file.md", "say \\"hi\\".txt", "back\\\\slash.txt", "tab\\there.txt", '
                               '"del\\u007fname.txt", "caf\xe9 \U0001f600.md"]\n')
        reads_back(self, text, {"source_paths": ["src"], "only_mutate": ["src/a.py"], "also_copy": names})

    def test_a_source_path_outside_the_bmp_stays_valid_toml(self):
        text = mutants.add_mutmut_table("", ["😀"], ["😀/a.py", "src/😀.py"])
        self.assertEqual(text, '[tool.mutmut]\nsource_paths = ["\U0001f600"]\nonly_mutate = ["\U0001f600/a.py", '
                               '"src/\U0001f600.py"]\n')
        reads_back(self, text, {"source_paths": ["😀"], "only_mutate": ["😀/a.py", "src/😀.py"]})

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
            with open(os.path.join(cwd, "pyproject.toml"), encoding="utf-8") as f:
                self.pyprojects.append(f.read())
            tables.append(mutmut_block(self.pyprojects[-1]))
            return 1, "failed to collect stats. runner returned 1\n"  # stop at the first run: the table is all we need

        self.pyprojects = []  # each pyproject.toml mutmut read, whole
        base, head, mb = merge_base(repo, "HEAD~1", "HEAD")
        rv = Review(repo, mb, head, ADAPTERS["python"](), [os.path.join(project_dir, "tests/**")], project_dir)
        with contextlib.redirect_stderr(io.StringIO()):
            self.check, _ = mutants.run(rv, None, 5, None, None, fake)
        return tables

    def test_the_table_lists_the_tracked_files_tests_read_besides_the_sources(self):
        tables = self.r3({"pyproject.toml": "[project]\nname = 'calc'\n", "src/calc/core.py": "def add(a, b):\n    return a + b\n",
                          "tests/test_core.py": "", "docs/guide.md": "", "scripts/x.py": "", "README.md": ""},
                         "src/calc/core.py")
        self.assertEqual(tables, ['[tool.mutmut]\nsource_paths = ["src"]\nonly_mutate = ["src/calc/core.py"]\n'
                                  'also_copy = ["README.md", "docs", "scripts"]\n'])
        reads_back(self, self.pyprojects[0], {"source_paths": ["src"], "only_mutate": ["src/calc/core.py"],
                                              "also_copy": ["README.md", "docs", "scripts"]})

    def test_with_a_project_dir_the_list_is_that_dirs_entries_relative_to_it(self):
        tables = self.r3({"pkg/pyproject.toml": "[project]\nname = 'calc'\n",
                          "pkg/src/calc/core.py": "def add(a, b):\n    return a + b\n", "pkg/tests/test_core.py": "",
                          "pkg/config/app.example.yaml": "", "docs/top.md": ""},
                         "pkg/src/calc/core.py", project_dir="pkg")
        self.assertEqual(tables, ['[tool.mutmut]\nsource_paths = ["src"]\nonly_mutate = ["src/calc/core.py"]\n'
                                  'also_copy = ["config"]\n'])
        reads_back(self, self.pyprojects[0], {"source_paths": ["src"], "only_mutate": ["src/calc/core.py"],
                                              "also_copy": ["config"]})

    def test_the_rest_of_the_repos_pyproject_is_kept_beside_the_table(self):
        self.r3({"pyproject.toml": "[project]\nname = 'calc'\n\n[tool.pytest.ini_options]\npythonpath = ['src']\n",
                 "src/calc/core.py": "def add(a, b):\n    return a + b\n", "tests/test_core.py": ""}, "src/calc/core.py")
        self.assertEqual(self.pyprojects, ["[project]\nname = 'calc'\n\n[tool.pytest.ini_options]\npythonpath = ['src']\n"
                                           '\n[tool.mutmut]\nsource_paths = ["src"]\nonly_mutate = ["src/calc/core.py"]\n'])
        t = tomllib()
        if t:
            self.assertEqual(t.loads(self.pyprojects[0]),
                             {"project": {"name": "calc"}, "tool": {"pytest": {"ini_options": {"pythonpath": ["src"]}},
                              "mutmut": {"source_paths": ["src"], "only_mutate": ["src/calc/core.py"]}}})

    def test_a_repo_with_its_own_mutmut_table_gets_r3_not_applicable_and_mutmut_never_runs(self):
        tables = self.r3({"pyproject.toml": "[project]\nname = 'calc'\n\n[tool.mutmut]\nsource_paths = ['src']\n",
                          "src/calc/core.py": "def add(a, b):\n    return a + b\n", "tests/test_core.py": "",
                          "docs/guide.md": ""}, "src/calc/core.py")
        self.assertEqual((self.check, tables), ({"status": "n/a", "note": "the repo already configures mutmut "
                                                 "([tool.mutmut]) in . (env): R3 cannot set only_mutate; not overridden"},
                                                []))


if __name__ == "__main__":
    unittest.main()
