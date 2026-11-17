"""doctor's python trial also runs the suite inside R3's mutmut sandbox (issue #7).

R3 copies into `<project dir>/mutants/` only mutmut 3.8.1's defaults, the source dirs and the tracked top-level entries
of the project dir (also_copy). A suite that reads a file outside those passes a plain run and fails there, so doctor
runs it once in the same sandbox and names the missing paths instead of reporting `ok`."""
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import doctor

CALLER = """jobs:
  mech-review:
    uses: EricleungDK/ekit/.github/workflows/mech-review.yml@v0
    with:
      stack: python
%s"""

# a test that reads a docs file `up` levels above its own dir, the way real suites locate files (from __file__)
READS = """import pathlib
import unittest


class Docs(unittest.TestCase):
    def test_guide(self):
        path = pathlib.Path(__file__).resolve().parents[%d] / "docs" / "guide.md"
        self.assertEqual(path.read_text(), "# guide\\n")
"""

PASSES = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, 1)\n"

# writes tests/gen.txt at the git top of the checkout it runs in, then reads it beside the test file
GEN = """import pathlib
import subprocess
import unittest

HERE = pathlib.Path(__file__).parent


class T(unittest.TestCase):
    def test_gen(self):
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=HERE, capture_output=True, text=True)
        out = pathlib.Path(top.stdout.strip()) / "tests" / "gen.txt"
        if not out.exists():
            out.write_text("x")
        self.assertEqual((HERE / "gen.txt").read_text(), "x")
"""
# makes tests/out and leaves it there
MKDIR = """import os
import pathlib
import unittest


class T(unittest.TestCase):
    def test_mk(self):
        os.mkdir(pathlib.Path(__file__).parent / "out")
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           *args], check=True, capture_output=True, text=True).stdout


def write(root, files):
    for path, text in files.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)


def unittest_runner(calls, installed=None):
    """the test command (`python3 -m pytest`) as a real unittest run of tests/, in the cwd doctor picks, with the
    environment doctor gives it; the mutation tool's --version passes. Every (argv, cwd) is recorded. installed: a dir
    on sys.path after PYTHONPATH, the way an editable install's .pth puts the caller's checkout there."""
    def run(argv, cwd):
        calls.append((argv, cwd))
        if "--version" in argv:
            return 0, "mutmut, version 3.8.1\n"
        env = dict(os.environ)
        if installed:
            env["PYTHONPATH"] = os.pathsep.join(p for p in (env.get("PYTHONPATH"), installed) if p)
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=cwd, env=env,
                           capture_output=True, text=True)
        out = r.stdout + r.stderr
        # pytest's shape, which the python adapter reads
        return (0, out + "\n1 passed in 0.01s\n") if r.returncode == 0 else (1, out + "\n1 failed in 0.01s\n")
    return run


class SandboxTrial(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(tmp.name, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        self.calls = []

    def commit(self, files, links=()):
        write(self.repo, files)
        for path, target in links:
            os.symlink(target, os.path.join(self.repo, path))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "head")

    def doctor(self, runner=None, **kw):
        return doctor.run(self.repo, stack="python", runner=runner or unittest_runner(self.calls), **kw)

    def test_tests_reading_a_tracked_top_level_docs_file_pass_in_the_sandbox(self):
        self.commit({"pyproject.toml": "[project]\nname = 'calc'\n", "calc/core.py": "X = 1\n",
                     "docs/guide.md": "# guide\n", "tests/test_docs.py": READS % 1,
                     ".github/workflows/mech-review.yml": CALLER % "      test-paths: tests/**\n"})
        env = self.doctor()
        self.assertEqual(env["trial"]["sandbox"], "pass")
        self.assertEqual(env["entries"], [])
        self.assertTrue(env["summary"].startswith("ok "))

    def test_a_subfolder_project_whose_tests_read_a_file_above_it_fails_the_sandbox_naming_the_path(self):
        self.commit({"app/pyproject.toml": "[project]\nname = 'calc'\n", "app/calc/core.py": "X = 1\n",
                     "docs/guide.md": "# guide\n", "app/tests/test_docs.py": READS % 2,
                     ".github/workflows/mech-review.yml": CALLER % "      project-dir: app\n      test-paths: app/tests/**\n"})
        env = self.doctor(project_dir="app")
        self.assertEqual(env["trial"]["tests"], "pass")
        self.assertEqual(env["trial"]["sandbox"], "fail")
        [e] = env["entries"]
        self.assertEqual((e["check"], e["class"], e["severity"]), ("doctor", "env", "fail"))
        self.assertIn("R3's mutmut sandbox fails where the plain run passes", e["problem"])
        self.assertIn("`../docs/guide.md`", e["problem"])
        self.assertEqual(env["summary"], f"fail {env['head']} (1 problems)")

    def test_the_sandbox_imports_its_own_copy_of_src_layout_code_not_an_installed_checkout(self):
        # app/src/calc reads <repo>/docs/guide.md from its own __file__: found from the checkout, not from R3's copy
        self.commit({"app/pyproject.toml": "[project]\nname = 'calc'\n", "docs/guide.md": "# guide\n",
                     "app/src/calc/__init__.py": "import pathlib\n"
                     "GUIDE = (pathlib.Path(__file__).resolve().parents[3] / 'docs' / 'guide.md').read_text()\n",
                     "app/tests/test_calc.py": "import unittest\n\nimport calc\n\n\nclass T(unittest.TestCase):\n"
                     "    def test_guide(self):\n        self.assertEqual(calc.GUIDE, '# guide\\n')\n"})
        runner = unittest_runner(self.calls, installed=os.path.join(self.repo, "app", "src"))
        env = self.doctor(runner=runner, project_dir="app")
        self.assertEqual((env["trial"]["tests"], env["trial"]["sandbox"]), ("pass", "fail"))
        self.assertEqual(env["entries"][0]["problem"],
                         "R3's mutmut sandbox fails where the plain run passes (missing there: `../docs/guide.md`)")

    def test_a_source_dir_left_out_of_also_copy_for_a_dir_link_is_still_copied_as_mutmut_copies_sources(self):
        # also_copy leaves out calc/ (it holds a link to a dir); R3 copies it as a source when the diff touches it
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "shared/data/x.txt": "x\n",
                     ".github/workflows/mech-review.yml": CALLER % "",
                     "tests/test_calc.py": "import unittest\n\nimport calc\n\n\nclass T(unittest.TestCase):\n"
                     "    def test_x(self):\n        self.assertEqual(calc.X, 1)\n"},
                    links=[("calc/data", "../shared/data")])
        env = self.doctor()
        self.assertEqual((env["trial"]["sandbox"], env["entries"]), ("pass", []))

    def test_a_dir_link_inside_a_source_dir_is_not_followed_as_mutmut_does_not_follow_it(self):
        self.commit({"pyproject.toml": "[project]\n", "shared/data/x.txt": "x\n",
                     "calc/__init__.py": "import pathlib\n"
                     "X = (pathlib.Path(__file__).parent / 'data' / 'x.txt').read_text()\n",
                     "tests/test_calc.py": "import unittest\n\nimport calc\n\n\nclass T(unittest.TestCase):\n"
                     "    def test_x(self):\n        self.assertEqual(calc.X, 'x\\n')\n"},
                    links=[("calc/data", "../shared/data")])
        env = self.doctor()
        self.assertEqual((env["trial"]["tests"], env["trial"]["sandbox"]), ("pass", "fail"))
        self.assertEqual(env["entries"][0]["problem"],
                         "R3's mutmut sandbox fails where the plain run passes (missing there: `calc/data/x.txt`)")

    def test_a_dangling_link_mutmut_cannot_copy_is_an_entry_naming_it_not_a_crash(self):
        # mutmut copies tests/ with copytree, which stops on a link whose target is untracked (build/ is ignored)
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("tests/data", "../build/data")])
        env = self.doctor()
        self.assertEqual((env["trial"]["tests"], env["trial"]["sandbox"]), ("pass", "fail"))
        [e] = env["entries"]
        self.assertEqual((e["check"], e["class"], e["severity"]), ("doctor", "env", "fail"))
        self.assertEqual(e["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into mutants/ fails on "
                                       "`tests/data`")

    def test_a_dangling_file_link_in_a_possible_source_is_an_entry_naming_it(self):
        # also_copy leaves calc/ out for the link; mutmut's copy of calc/ as a source copies each file and stops on it
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("calc/conf.yaml", "../build/conf.yaml")])
        env = self.doctor()
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `calc/conf.yaml`")

    def test_the_sandbox_run_turns_off_random_test_order_as_mutmut_does(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES})
        self.doctor()
        sandbox_run = self.calls[1]  # after the plain run, before the mutation tool's --version
        self.assertEqual(sandbox_run[0], ["python3", "-m", "pytest", "-p", "no:randomly", "-p", "no:random-order"])

    def test_a_dangling_top_level_link_is_skipped_as_mutmut_skips_a_missing_source(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("gen.py", "build/gen.py")])
        env = self.doctor()
        self.assertEqual((env["trial"]["sandbox"], env["entries"]), ("pass", []))

    def test_a_possible_source_is_found_when_repo_names_the_project_dir_itself(self):
        # git lists a tree from the cwd unless told --full-tree: with --repo app/ it would list nothing under app/
        self.commit({"app/pyproject.toml": "[project]\n", "app/calc/__init__.py": "X = 1\n", "shared/data/x.txt": "x\n",
                     "app/tests/test_calc.py": "import unittest\n\nimport calc\n\n\nclass T(unittest.TestCase):\n"
                     "    def test_x(self):\n        self.assertEqual(calc.X, 1)\n"},
                    links=[("app/calc/data", "../../shared/data")])
        env = doctor.run(os.path.join(self.repo, "app"), stack="python", project_dir="app",
                         runner=unittest_runner(self.calls))
        self.assertEqual(env["trial"]["sandbox"], "pass")

    def test_the_sandbox_run_keeps_an_inherited_pythonpath_after_its_own(self):
        lib = os.path.join(os.path.dirname(self.repo), "lib")
        write(lib, {"helper.py": "Y = 2\n"})
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n",
                     ".github/workflows/mech-review.yml": CALLER % "",
                     "tests/test_a.py": "import unittest\n\nimport helper\n\n\nclass T(unittest.TestCase):\n"
                     "    def test_y(self):\n        self.assertEqual(helper.Y, 2)\n"})
        with unittest.mock.patch.dict(os.environ, {"PYTHONPATH": lib}):
            env = self.doctor()
        self.assertEqual((env["trial"]["sandbox"], env["entries"]), ("pass", []))

    def test_a_file_the_plain_run_leaves_behind_does_not_reach_the_sandbox(self):
        # the test writes tests/gen.txt at the checkout's top and reads it beside itself: in R3's fresh worktree the
        # copy in mutants/tests/ never has it
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", ".gitignore": "tests/gen.txt\n",
                     ".github/workflows/mech-review.yml": CALLER % "", "tests/test_gen.py": GEN})
        env = self.doctor()
        self.assertEqual((env["trial"]["tests"], env["trial"]["sandbox"]), ("pass", "fail"))
        self.assertEqual([e["problem"] for e in env["entries"]],
                         ["R3's mutmut sandbox fails where the plain run passes (missing there: `tests/gen.txt`)"])

    def test_a_dir_the_plain_run_leaves_behind_does_not_fail_the_sandbox(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", ".gitignore": "tests/out/\n",
                     ".github/workflows/mech-review.yml": CALLER % "", "tests/test_mk.py": MKDIR})
        env = self.doctor()
        self.assertEqual((env["trial"]["tests"], env["trial"]["sandbox"], env["entries"]), ("pass", "pass", []))

    def test_a_sandbox_failure_with_no_path_in_the_output_says_so_and_names_the_command(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/core.py": "X = 1\n", "tests/test_a.py": "",
                     ".github/workflows/mech-review.yml": CALLER % ""})

        def run(argv, cwd):
            if "--version" in argv:
                return 0, "mutmut, version 3.8.1\n"
            return (1, "E   assert 1 == 2\n1 failed in 0.01s\n") if cwd.endswith("/mutants") else (0, "1 passed in 0.01s\n")
        env = self.doctor(runner=run)
        [e] = env["entries"]
        self.assertEqual(e["problem"], "R3's mutmut sandbox fails where the plain run passes (no missing path found in "
                                       "the output of `python3 -m pytest -p no:randomly -p no:random-order` run in "
                                       "mutants/)")

    def test_each_missing_path_is_named_once_relative_to_the_sandbox_or_as_printed_when_outside_the_worktree(self):
        self.commit({"app/pyproject.toml": "[project]\n", "app/calc/core.py": "X = 1\n", "app/tests/test_a.py": "",
                     ".github/workflows/mech-review.yml": CALLER % "      project-dir: app\n      test-paths: app/tests/**\n"})

        def run(argv, cwd):
            if "--version" in argv:
                return 0, "mutmut, version 3.8.1\n"
            if not cwd.endswith("/mutants"):
                return 0, "1 passed in 0.01s\n"
            return 1, (f"E   FileNotFoundError: [Errno 2] No such file or directory: '{cwd}/scripts/demo.py'\n"
                       f"ERROR tests/test_a.py - FileNotFoundError: [Errno 2] No such file or directory: '{cwd}/scripts/demo.py'\n"
                       "E   FileNotFoundError: [Errno 2] No such file or directory: './config/app.yaml'\n"
                       "E   FileNotFoundError: [Errno 2] No such file or directory: \"/nonexistent/it's.md\"\n"
                       f"E   FileNotFoundError: [Errno 2] No such file or directory: '{cwd}/../docs/guide.md'\n"
                       "1 failed in 0.01s\n")
        env = self.doctor(runner=run, project_dir="app")
        [e] = env["entries"]
        self.assertEqual(e["problem"], "R3's mutmut sandbox fails where the plain run passes (missing there: "
                                       "`scripts/demo.py`, `config/app.yaml`, `/nonexistent/it's.md`, `../docs/guide.md`)")
        self.assertIn("R3 copies into app/mutants/ only the project dir's tracked top-level entries", e["hint"])

    def test_a_sandbox_run_that_times_out_says_so_not_that_no_path_was_found(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/core.py": "X = 1\n", "tests/test_a.py": "",
                     ".github/workflows/mech-review.yml": CALLER % ""})

        def run(argv, cwd):
            if "--version" in argv:
                return 0, "mutmut, version 3.8.1\n"
            return ("timeout", "") if cwd.endswith("/mutants") else (0, "1 passed in 0.01s\n")
        env = self.doctor(runner=run)
        self.assertEqual(env["trial"]["sandbox"], "fail")
        [e] = env["entries"]
        self.assertEqual((e["class"], e["severity"]), ("env", "fail"))
        self.assertEqual(e["problem"], "R3's mutmut sandbox run timed out where the plain run passes "
                                       "(`python3 -m pytest -p no:randomly -p no:random-order` in mutants/)")

    def test_a_failing_plain_run_skips_the_sandbox(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/core.py": "X = 1\n", "tests/test_a.py": ""})

        def run(argv, cwd):
            self.calls.append(argv)
            return (0, "mutmut, version 3.8.1\n") if "--version" in argv else (1, "1 failed in 0.01s\n")
        env = self.doctor(runner=run)
        self.assertEqual(env["trial"]["sandbox"], "skipped")
        self.assertEqual(self.calls, [["python3", "-m", "pytest"], ["mutmut", "--version"]])

    def test_the_sandbox_holds_the_sources_also_copy_and_mutmut_defaults_merged_over_a_tracked_mutants_dir(self):
        self.commit({"pyproject.toml": "[project]\n", "setup.cfg": "", "uv.lock": "", "test_root.py": "",
                     "tests/test_a.py": "", "test/test_b.py": "", "src/calc/core.py": "X = 1\n", "conftest.py": "",
                     "README.md": "", "docs/guide.md": "# guide\n", "mutants/docs/stale.md": "",
                     "mutants/stale.py": ""})
        seen = {}

        def run(argv, cwd):
            if cwd.endswith("/mutants"):
                seen["top"] = sorted(os.listdir(cwd))
                seen["docs"] = sorted(os.listdir(os.path.join(cwd, "docs")))
                with open(os.path.join(cwd, "docs", "guide.md")) as f:
                    seen["guide"] = f.read()
            return (0, "mutmut, version 3.8.1\n") if "--version" in argv else (0, "1 passed in 0.01s\n")
        env = self.doctor(runner=run)
        self.assertEqual(env["trial"]["sandbox"], "pass")
        self.assertEqual(seen, {"top": ["README.md", "conftest.py", "docs", "pyproject.toml", "setup.cfg", "src", "stale.py",
                                        "test", "test_root.py", "tests", "uv.lock"],
                                "docs": ["guide.md", "stale.md"], "guide": "# guide\n"})

    def test_doctor_leaves_the_checkout_as_it_was_and_no_worktree(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/core.py": "X = 1\n", "docs/guide.md": "# guide\n",
                     "tests/test_docs.py": READS % 1})
        self.doctor()
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(len(git(self.repo, "worktree", "list").splitlines()), 1)

    def test_rust_trial_runs_no_sandbox(self):
        self.commit({"Cargo.toml": "[package]\n", "src/lib.rs": ""})

        def run(argv, cwd):
            self.calls.append(argv)
            return 0, "test result: ok. 1 passed; 0 failed; 0 ignored\n"
        env = doctor.run(self.repo, stack="rust", runner=run)
        self.assertEqual(env["trial"], {"tests": "pass", "command": "cargo test", "mutation_tool": "present"})
        self.assertEqual(self.calls, [["cargo", "test"], ["cargo", "mutants", "--version"]])


if __name__ == "__main__":
    unittest.main()
