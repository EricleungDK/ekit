"""doctor's python trial also runs the suite inside R3's mutmut sandbox (issue #7).

R3 copies into `<project dir>/mutants/` only mutmut 3.8.1's defaults, the source dirs and the tracked top-level entries
of the project dir (also_copy). A suite that reads a file outside those passes a plain run and fails there, so doctor
runs it once in the same sandbox and names the missing paths instead of reporting `ok`."""
import os
import shutil
import signal
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

# what every doctor entry of the trial carries (report.entry): ids are sha1 of check + file + key, as the spec sets them
FORBIDDEN = "skipping or deselecting tests in the caller to get a green trial"
LINK_HINT = ("mutmut's copy follows links: a dangling link, one to a dir above it or one into the checkout by an "
             "absolute path under tests/ (or a dangling one in a source dir) stops or loops R3 too; drop or fix the "
             "link (track its target, make it relative); rerun doctor")

HELD_HINT = ("a link mutmut cannot copy (dangling, to a dir, or leaving the project dir) keeps its whole top-level "
             "entry out of R3's copy: track its target or remove the link; rerun doctor")


def entry(key_id, problem, hint):
    return {"id": key_id, "check": "doctor", "class": "env", "severity": "fail", "file": "", "line": 0,
            "problem": problem, "hint": hint, "forbidden": FORBIDDEN}


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
            os.makedirs(os.path.dirname(os.path.join(self.repo, path)), exist_ok=True)
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
        self.assertEqual(env["entries"], [entry("doctor-be15db16", "R3's mutmut sandbox cannot be built: mutmut's "
                                                "copy into mutants/ fails on `calc/conf.yaml`", LINK_HINT)])

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

    def test_a_link_to_a_dir_above_it_or_to_its_own_dir_under_tests_is_an_entry_found_before_any_copy(self):
        # mutmut's copytree of tests/ follows tests/up -> .. without end; doctor must not start that copy
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("tests/up", ".."), ("tests/self", ".")])
        before = signal.signal(signal.SIGALRM, lambda *_: self.fail("doctor still copying after 30 s"))
        signal.alarm(30)
        try:
            env = self.doctor()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, before)
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `tests/self`, `tests/up`")
        self.assertEqual((env["trial"]["sandbox"], env["entries"]),
                         ("fail", [entry("doctor-be15db16", "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                         "mutants/ fails on `tests/self`, `tests/up`", LINK_HINT)]))
        self.assertEqual([argv for argv, _ in self.calls], [["python3", "-m", "pytest"], ["mutmut", "--version"]])

    def test_a_chain_of_dir_links_that_comes_back_round_is_an_entry_found_before_any_copy(self):
        # tests/a -> shared, shared/b -> other, other/c -> shared: copytree goes round shared/b/c/b/c/... for ever
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     "shared/x.txt": "", "other/y.txt": "", ".github/workflows/mech-review.yml": CALLER % ""},
                    links=[("tests/a", "../shared"), ("shared/b", "../other"), ("other/c", "../shared")])
        before = signal.signal(signal.SIGALRM, lambda *_: self.fail("doctor still copying after 30 s"))
        signal.alarm(30)
        try:
            env = self.doctor()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, before)
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `tests/a/b/c`")

    def test_links_under_tests_to_tracked_files_and_dirs_inside_the_checkout_are_copied(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "docs/guide.md": "# guide\n",
                     ".github/workflows/mech-review.yml": CALLER % "",
                     "tests/test_a.py": "import pathlib\nimport unittest\n\nHERE = pathlib.Path(__file__).parent\n\n\n"
                     "class T(unittest.TestCase):\n    def test_links(self):\n"
                     "        self.assertEqual((HERE / 'guide.md').read_text(), '# guide\\n')\n"
                     "        self.assertEqual((HERE / 'docs' / 'guide.md').read_text(), '# guide\\n')\n"},
                    links=[("tests/guide.md", "../docs/guide.md"), ("tests/docs", "../docs")])
        env = self.doctor()
        self.assertEqual((env["trial"]["sandbox"], env["entries"]), ("pass", []))

    def test_links_under_tests_to_an_existing_dir_or_file_outside_the_checkout_are_copied(self):
        # copytree follows them and copies what is there, as mutmut does: no reason to stop doctor
        outside = os.path.join(os.path.dirname(self.repo), "outside")
        write(outside, {"data/x.txt": "x\n", "hosts": "h\n"})
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", ".github/workflows/mech-review.yml":
                     CALLER % "", "tests/test_a.py": "import pathlib\nimport unittest\n\nHERE = pathlib.Path(__file__).parent"
                     "\n\n\nclass T(unittest.TestCase):\n    def test_links(self):\n"
                     "        self.assertEqual((HERE / 'ext' / 'x.txt').read_text(), 'x\\n')\n"
                     "        self.assertEqual((HERE / 'hosts').read_text(), 'h\\n')\n"},
                    links=[("tests/ext", os.path.join(outside, "data")), ("tests/hosts", os.path.join(outside, "hosts"))])
        env = self.doctor()
        self.assertEqual((env["trial"]["sandbox"], env["entries"]), ("pass", []))

    def test_a_link_under_tests_to_a_missing_path_outside_the_checkout_is_an_entry(self):
        gone = os.path.join(os.path.dirname(self.repo), "gone", "x")
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("tests/gone", gone)])
        env = self.doctor()
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `tests/gone`")

    def test_a_top_level_test_link_to_the_dir_above_is_named_as_itself(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("test", "..")])
        env = self.doctor()
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `test`")

    def test_an_unreadable_dir_behind_a_top_level_test_link_outside_is_an_entry_not_a_crash(self):
        # test -> <outside> is not walked (it may be big); copytree then cannot read outside/locked
        outside = os.path.join(os.path.dirname(self.repo), "outside")
        write(outside, {"locked/x.txt": "", "ok.txt": ""})
        os.mkfifo(os.path.join(outside, "fifo"))
        os.chmod(os.path.join(outside, "locked"), 0)
        self.addCleanup(os.chmod, os.path.join(outside, "locked"), 0o700)
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("test", outside)])
        env = self.doctor()
        [e] = env["entries"]
        self.assertEqual((e["class"], e["severity"]), ("env", "fail"))
        self.assertEqual(e["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into mutants/ fails on "
                                       "`test/fifo`, `test/locked`")
        # the reason of the first path named, whatever order the filesystem lists them in
        self.assertEqual(e["hint"], "mutmut's copy into mutants/ fails on it: `test/fifo` is a named pipe; fix that in "
                                    "the tree, then rerun doctor")

    def test_a_named_pipe_behind_a_link_is_named_with_the_reason_not_the_link_hint(self):
        outside = os.path.join(os.path.dirname(self.repo), "outside")
        os.makedirs(outside)
        os.mkfifo(os.path.join(outside, "fifo"))
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""},
                    links=[("tests/pipe", os.path.join(outside, "fifo"))])
        env = self.doctor()
        [e] = env["entries"]
        self.assertEqual(e["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into mutants/ fails on "
                                       "`tests/pipe`")
        self.assertEqual(e["hint"], "mutmut's copy into mutants/ fails on it: `tests/pipe` is a named pipe; fix that "
                                    "in the tree, then rerun doctor")
        self.assertEqual((env["trial"]["sandbox"], e),
                         ("fail", entry("doctor-be15db16", "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                        "mutants/ fails on `tests/pipe`", "mutmut's copy into mutants/ fails on it: "
                                        "`tests/pipe` is a named pipe; fix that in the tree, then rerun doctor")))

    def test_a_named_pipe_in_a_possible_source_names_the_source_and_the_reason(self):
        # calc/ is left out of also_copy for its absolute link, so it is copied file by file as a source: copy2 on the
        # pipe gives a SpecialFileError with no file name of its own
        outside = os.path.join(os.path.dirname(self.repo), "outside")
        os.makedirs(outside)
        os.mkfifo(os.path.join(outside, "fifo"))
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""},
                    links=[("calc/pipe", os.path.join(outside, "fifo"))])
        env = self.doctor()
        self.assertEqual((env["trial"]["sandbox"], env["entries"]),
                         ("fail", [entry("doctor-be15db16", "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                         "mutants/ fails on `calc`", "mutmut's copy into mutants/ fails on it: "
                                         "`calc/pipe` is a named pipe; fix that in the tree, then rerun doctor")]))

    def test_a_tracked_file_named_mutants_names_the_path_that_cannot_be_made(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     "mutants": "", ".github/workflows/mech-review.yml": CALLER % ""})
        env = self.doctor()
        [e] = env["entries"]
        # the first entry copied (also_copy, sorted: .github) is the first that cannot be made under the file
        self.assertEqual(e["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into mutants/ fails on "
                                       "`mutants/.github`")
        self.assertEqual(e["hint"], "mutmut's copy into mutants/ fails on it: Not a directory; fix that in the tree, "
                                    "then rerun doctor")

    def test_copystat_failures_on_a_dir_and_its_subdir_are_an_entry_not_a_crash(self):
        # copytree reports the subdir by its DirEntry and the top dir by a str (as for a SIP-restricted /usr/share/vim)
        real_copystat = shutil.copystat

        def copystat(src, dst, **kw):
            if os.fspath(dst).endswith((os.sep + os.path.join("mutants", "tests"),
                                        os.sep + os.path.join("mutants", "tests", "sub"))):
                raise PermissionError(1, "Operation not permitted")
            return real_copystat(src, dst, **kw)
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     "tests/sub/x.txt": "", ".github/workflows/mech-review.yml": CALLER % ""})
        with unittest.mock.patch("shutil.copystat", copystat):
            env = self.doctor()
        [e] = env["entries"]
        self.assertEqual(e["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into mutants/ fails on "
                                       "`tests`, `tests/sub`")
        self.assertEqual(e["hint"], "mutmut's copy into mutants/ fails on it: Operation not permitted; fix that in the "
                                    "tree, then rerun doctor")

    def doctor_within(self, secs):
        """doctor.run, failed if it is still running after secs (a copy without end)."""
        before = signal.signal(signal.SIGALRM, lambda *_: self.fail(f"doctor still copying after {secs} s"))
        signal.alarm(secs)
        try:
            return self.doctor()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, before)

    def test_a_link_under_tests_into_the_callers_checkout_by_absolute_path_is_an_entry(self):
        # doctor's worktree is elsewhere: copytree would copy the caller's checkout, this link in it included, over and
        # over; in a fresh CI checkout the path does not exist at all
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("tests/x", self.repo)])
        env = self.doctor_within(30)
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `tests/x`")

    def test_a_temp_dir_inside_the_callers_checkout_does_not_flag_the_sandbox_itself(self):
        # TMPDIR inside the checkout puts doctor's worktree there: its own files are not links into the checkout
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".gitignore": ".scratch/\n", ".github/workflows/mech-review.yml": CALLER % ""})
        os.makedirs(os.path.join(self.repo, ".scratch"))
        with unittest.mock.patch("tempfile.tempdir", os.path.join(self.repo, ".scratch")):
            env = self.doctor()
        self.assertEqual((env["trial"]["sandbox"], env["entries"]), ("pass", []))

    def test_links_into_the_main_checkout_count_as_the_checkout_when_doctor_runs_from_a_linked_worktree(self):
        # doctor run on a linked worktree (<main>/.claude/worktrees/x): absolute links into <main> dangle in CI too,
        # and copytree through <main> reaches the linked worktree and its links again
        main = self.repo
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     "data/fixtures/a.txt": "", ".gitignore": ".claude/\n",
                     ".github/workflows/mech-review.yml": CALLER % ""},
                    links=[("tests/fx", os.path.join(main, "data", "fixtures")), ("tests/repo", main)])
        linked = os.path.join(main, ".claude", "worktrees", "x")
        git(main, "worktree", "add", "-q", "--detach", linked)
        before = signal.signal(signal.SIGALRM, lambda *_: self.fail("doctor still copying after 30 s"))
        signal.alarm(30)
        try:
            env = doctor.run(linked, stack="python", runner=unittest_runner(self.calls))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, before)
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `tests/fx`, `tests/repo`")

    def test_a_link_to_a_dir_holding_the_checkout_is_an_entry_without_walking_it(self):
        # tests/ws -> ws, the checkout at ws/org/P: copying ws copies the checkout and this link again; with the walk
        # cut short at once, only the containment rule can find it
        ws = os.path.join(os.path.dirname(self.repo), "ws")
        repo = os.path.join(ws, "org", "P")
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        write(repo, {"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""})
        os.symlink(ws, os.path.join(repo, "tests", "ws"))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "head")
        before = signal.signal(signal.SIGALRM, lambda *_: self.fail("doctor still copying after 30 s"))
        signal.alarm(30)
        try:
            with unittest.mock.patch.object(doctor, "OUTSIDE_WALK", 1):
                env = doctor.run(repo, stack="python", runner=unittest_runner(self.calls))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, before)
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `tests/ws`")

    def outside_chain(self):
        """tests/x -> outside, with outside/a/b/c/gone dangling: the walk meets gone as its fifth entry outside."""
        outside = os.path.join(os.path.dirname(self.repo), "outside")
        os.makedirs(os.path.join(outside, "a", "b", "c"))
        os.symlink(os.path.join(outside, "missing"), os.path.join(outside, "a", "b", "c", "gone"))
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("tests/x", outside)])

    def test_the_walk_outside_the_checkout_reaches_its_cap_and_no_further(self):
        # five entries walked: the dangling link is the fifth, found before copying
        self.outside_chain()
        with unittest.mock.patch.object(doctor, "OUTSIDE_WALK", 5):
            env = self.doctor()
        self.assertEqual(env["entries"], [entry("doctor-be15db16", "R3's mutmut sandbox cannot be built: mutmut's "
                                                "copy into mutants/ fails on `tests/x/a/b/c/gone`", LINK_HINT)])

    def test_past_its_cap_the_walk_outside_leaves_the_rest_to_the_copy(self):
        # four entries walked: c/ is not opened, so copytree meets the dangling link and names it with its reason
        self.outside_chain()
        with unittest.mock.patch.object(doctor, "OUTSIDE_WALK", 4):
            env = self.doctor()
        self.assertEqual(env["entries"], [entry("doctor-be15db16", "R3's mutmut sandbox cannot be built: mutmut's "
                                                "copy into mutants/ fails on `tests/x/a/b/c/gone`", "mutmut's copy into "
                                                "mutants/ fails on it: No such file or directory; fix that in the tree, "
                                                "then rerun doctor")])

    def test_a_loop_inside_a_dir_outside_the_checkout_is_an_entry(self):
        outside = os.path.join(os.path.dirname(self.repo), "outside")
        write(outside, {"a.txt": ""})
        os.symlink(".", os.path.join(outside, "self"))
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("tests/x", outside)])
        env = self.doctor_within(30)
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `tests/x/self`")

    def test_exactly_ten_links_are_all_named_with_no_more(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""},
                    links=[(f"tests/l{i}", f"../build/l{i}") for i in range(10)])
        env = self.doctor()
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                         "mutants/ fails on `tests/l0`, `tests/l1`, `tests/l2`, `tests/l3`, `tests/l4`, `tests/l5`, "
                         "`tests/l6`, `tests/l7`, `tests/l8`, `tests/l9`")

    def test_the_links_named_are_sorted_and_capped_whatever_order_the_filesystem_lists_them(self):
        names = ["l07", "l02", "l11", "l00", "l09", "l04", "l10", "l01", "l08", "l03", "l06", "l05"]
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""},
                    links=[(f"tests/{n}", f"../build/{n}") for n in names])
        env = self.doctor()
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                         "mutants/ fails on `tests/l00`, `tests/l01`, `tests/l02`, `tests/l03`, `tests/l04`, "
                         "`tests/l05`, `tests/l06`, `tests/l07`, `tests/l08`, `tests/l09` and 2 more")

    def test_a_copy_onto_itself_names_the_entry_being_copied(self):
        # a tracked mutants/tests -> ../tests: copytree copies each file onto itself (shutil.SameFileError)
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES,
                     ".github/workflows/mech-review.yml": CALLER % ""}, links=[("mutants/tests", "../tests")])
        env = self.doctor()
        self.assertEqual(env["entries"][0]["problem"], "R3's mutmut sandbox cannot be built: mutmut's copy into "
                                                       "mutants/ fails on `tests`")
        # shutil's own words (its src is a DirEntry on 3.8+), the checkout's temp prefix off the path
        self.assertIn(" and 'mutants/tests/test_a.py' are the same file; fix that in the tree, then rerun doctor",
                      env["entries"][0]["hint"])

    def test_doctor_leaves_no_pythonpath_behind_when_there_was_none(self):
        saved = os.environ.pop("PYTHONPATH", None)
        if saved is not None:
            self.addCleanup(os.environ.__setitem__, "PYTHONPATH", saved)
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES})
        self.doctor()
        self.assertNotIn("PYTHONPATH", os.environ)

    def test_doctor_puts_back_the_pythonpath_it_found(self):
        with unittest.mock.patch.dict(os.environ, {"PYTHONPATH": "/somewhere"}):
            self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "tests/test_a.py": PASSES})
            self.doctor()
            self.assertEqual(os.environ["PYTHONPATH"], "/somewhere")

    def test_the_sandbox_imports_from_source_before_src_as_mutmut_puts_them_on_sys_path(self):
        # the plain run imports an installed calc; in mutants/ the copy under source/ must win over src/ and the install
        lib = os.path.join(os.path.dirname(self.repo), "lib")
        write(lib, {"calc/__init__.py": "X = 'installed'\n"})
        self.commit({"pyproject.toml": "[project]\n", "source/calc/__init__.py": "X = 'source'\n",
                     "src/calc/__init__.py": "X = 'src'\n", ".github/workflows/mech-review.yml": CALLER % "",
                     "tests/test_calc.py": "import pathlib\nimport unittest\n\nimport calc\n\n"
                     "IN_SANDBOX = 'mutants' in pathlib.Path(__file__).parts\n\n\nclass T(unittest.TestCase):\n"
                     "    def test_x(self):\n        self.assertEqual(calc.X, 'source' if IN_SANDBOX else 'installed')\n"})
        env = self.doctor(runner=unittest_runner(self.calls, installed=lib))
        self.assertEqual((env["trial"]["sandbox"], env["entries"]), ("pass", []))

    def test_a_failing_sandbox_names_the_link_that_kept_a_top_level_entry_out_of_r3s_copy(self):
        # also_copy leaves docs/ out for its dangling docs/html (a known limit of R3): the tests then miss docs/usage.md
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", ".gitignore": "_build/\n",
                     "docs/usage.md": "# guide\n", ".github/workflows/mech-review.yml": CALLER % "",
                     "tests/test_docs.py": READS.replace("guide.md", "usage.md") % 1},
                    links=[("docs/html", "../_build/html")])
        env = self.doctor()
        self.assertEqual((env["trial"]["tests"], env["trial"]["sandbox"]), ("pass", "fail"))
        [e] = env["entries"]
        self.assertEqual(e["problem"], "R3's mutmut sandbox fails where the plain run passes (missing there: "
                                       "`docs/usage.md`); `docs/` is left out of R3's copy because of the link "
                                       "`docs/html`")
        self.assertEqual(e["hint"], "a link mutmut cannot copy (dangling, to a dir, or leaving the project dir) keeps "
                                    "its whole top-level entry out of R3's copy: track its target or remove the link; "
                                    "rerun doctor")
        self.assertEqual(e, entry("doctor-be15db16", e["problem"], e["hint"]))  # problem and hint pinned above

    def test_each_entry_kept_out_is_named_with_all_its_links(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "docs/usage.md": "# guide\n",
                     "site/index.md": "", ".github/workflows/mech-review.yml": CALLER % "",
                     "tests/test_docs.py": READS.replace("guide.md", "usage.md") % 1},
                    links=[("docs/pdf", "../_build/pdf"), ("docs/html", "../_build/html"), ("site/assets", "../docs")])
        env = self.doctor()
        self.assertEqual(env["entries"][0]["problem"],
                         "R3's mutmut sandbox fails where the plain run passes (missing there: `docs/usage.md`); "
                         "`docs/` is left out of R3's copy because of the links `docs/html`, `docs/pdf`; "
                         "`site/` is left out of R3's copy because of the link `site/assets`")

    def test_an_entry_kept_out_that_no_missing_path_lies_in_keeps_the_subfolder_hint(self):
        # the tests miss ../docs/guide.md (above project-dir app); app/site/ is kept out for an unrelated link
        self.commit({"app/pyproject.toml": "[project]\n", "app/calc/__init__.py": "X = 1\n", "docs/guide.md": "# guide\n",
                     "app/site/index.md": "", "app/tests/test_docs.py": READS % 2,
                     ".github/workflows/mech-review.yml": CALLER % "      project-dir: app\n      test-paths: app/tests/**\n"},
                    links=[("app/site/html", "../_build/html")])
        env = self.doctor(project_dir="app")
        [e] = env["entries"]
        self.assertEqual(e["problem"], "R3's mutmut sandbox fails where the plain run passes (missing there: "
                                       "`../docs/guide.md`); `site/` is left out of R3's copy because of the link "
                                       "`site/html`")
        self.assertEqual(e["hint"], "R3 copies into app/mutants/ only the project dir's tracked top-level entries and "
                                    "mutmut's defaults; keep the files the tests read inside the project dir, or make "
                                    "the tests not depend on files above it (a project-dir in a subfolder whose tests "
                                    "read ../ is a known limit); rerun doctor")

    def test_an_entry_kept_out_is_named_by_its_top_level_name_whatever_the_depth(self):
        # the missing file and the link both sit two levels down in docs/
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "docs/guide/usage.md": "# guide\n",
                     ".github/workflows/mech-review.yml": CALLER % "",
                     "tests/test_docs.py": READS.replace('"guide.md"', '"guide" / "usage.md"') % 1},
                    links=[("docs/api/html", "../../_build/html")])
        env = self.doctor()
        self.assertEqual(env["entries"], [entry("doctor-be15db16", "R3's mutmut sandbox fails where the plain run "
                                                "passes (missing there: `docs/guide/usage.md`); `docs/` is left out of "
                                                "R3's copy because of the link `docs/api/html`", HELD_HINT)])

    def test_only_links_that_miss_a_tracked_file_keep_an_entry_out(self):
        # notes/latest.md reaches notes/v1/latest.md through tracked dirs: notes/ is copied. odd/x.md steps through
        # a file (ENOTDIR) and chain/y.md reaches a link, not a file: those two are kept out, as also_copy does
        # site/ is kept out for site/html alone: its own site/latest.md -> v1/latest.md is fine and not named. A tracked
        # name with a newline in it reads like any other (git ls-tree -z keeps it raw)
        self.commit({"pyproject.toml": "[project]\n", "calc/__init__.py": "X = 1\n", "site/index.md": "# guide\n",
                     "notes/v1/latest.md": "", "odd/keep.md": "", "chain/keep.md": "", "site/v1/latest.md": "",
                     "notes/two\nlines.md": "", ".github/workflows/mech-review.yml": CALLER % "",
                     "tests/test_docs.py": READS.replace('"docs" / "guide.md"', '"site" / "index.md"') % 1},
                    links=[("site/html", "../_build/html"), ("site/latest.md", "v1/latest.md"),
                           ("notes/latest.md", "v1/latest.md"),
                           ("odd/x.md", "../notes/v1/latest.md/../latest.md"), ("chain/y.md", "../notes/latest.md")])
        env = self.doctor()
        self.assertEqual(env["entries"], [entry("doctor-be15db16", "R3's mutmut sandbox fails where the plain run "
                                                "passes (missing there: `site/index.md`); `chain/` is left out of R3's "
                                                "copy because of the link `chain/y.md`; `odd/` is left out of R3's copy "
                                                "because of the link `odd/x.md`; `site/` is left out of R3's copy "
                                                "because of the link `site/html`", HELD_HINT)])

    def test_a_possible_source_is_copied_whole_not_only_the_dirs_holding_its_py_files(self):
        # pkg/ (left out of also_copy for its dir link) holds .py files only in pkg/sub/; pkg/conf.txt must come too
        self.commit({"pyproject.toml": "[project]\n", "pkg/sub/mod.py": "", "pkg/conf.txt": "# guide\n",
                     "shared/x.txt": "", ".github/workflows/mech-review.yml": CALLER % "",
                     "tests/test_docs.py": READS.replace('"docs" / "guide.md"', '"pkg" / "conf.txt"') % 1},
                    links=[("pkg/link", "../shared")])
        env = self.doctor()
        self.assertEqual((env["trial"]["sandbox"], env["entries"]), ("pass", []))

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
        self.assertEqual(e, entry("doctor-7384cffc", "R3's mutmut sandbox run timed out where the plain run passes "
                                  "(`python3 -m pytest -p no:randomly -p no:random-order` in mutants/)",
                                  "the suite ran past doctor's 900 s limit there: rerun doctor; if it repeats, find "
                                  "what in the sandbox makes the suite hang"))

    def test_a_failing_plain_run_skips_the_sandbox(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/core.py": "X = 1\n", "tests/test_a.py": ""})

        def run(argv, cwd):
            self.calls.append(argv)
            return (0, "mutmut, version 3.8.1\n") if "--version" in argv else (1, "1 failed in 0.01s\n")
        env = self.doctor(runner=run)
        self.assertEqual(env["trial"]["sandbox"], "skipped")
        self.assertEqual(self.calls, [["python3", "-m", "pytest"], ["mutmut", "--version"]])
        self.assertEqual(env["entries"][0], entry("doctor-e361183b", "tests fail at head (fail): `python3 -m pytest`",
                                                     "fix them, or set setup-command for what they need; rerun doctor"))

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
