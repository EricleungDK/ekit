"""doctor's python trial also runs the suite inside R3's mutmut sandbox (issue #7).

R3 copies into `<project dir>/mutants/` only mutmut 3.8.1's defaults, the source dirs and the tracked top-level entries
of the project dir (also_copy). A suite that reads a file outside those passes a plain run and fails there, so doctor
runs it once in the same sandbox and names the missing paths instead of reporting `ok`."""
import os
import subprocess
import sys
import tempfile
import unittest

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

    def commit(self, files):
        write(self.repo, files)
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

    def test_a_sandbox_failure_with_no_path_in_the_output_says_so_and_names_the_command(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/core.py": "X = 1\n", "tests/test_a.py": ""})

        def run(argv, cwd):
            if "--version" in argv:
                return 0, "mutmut, version 3.8.1\n"
            return (1, "E   assert 1 == 2\n1 failed in 0.01s\n") if cwd.endswith("/mutants") else (0, "1 passed in 0.01s\n")
        env = self.doctor(runner=run)
        [e] = [e for e in env["entries"] if e["check"] == "doctor" and "sandbox" in e["problem"]]
        self.assertIn("no missing path found in the output of `python3 -m pytest` run in mutants/", e["problem"])

    def test_each_missing_path_is_named_once_relative_to_the_sandbox_or_as_printed_when_outside_the_worktree(self):
        self.commit({"app/pyproject.toml": "[project]\n", "app/calc/core.py": "X = 1\n", "app/tests/test_a.py": ""})

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
        [e] = [e for e in env["entries"] if e["check"] == "doctor" and "sandbox" in e["problem"]]
        self.assertEqual(e["problem"], "R3's mutmut sandbox fails where the plain run passes (missing there: "
                                       "`scripts/demo.py`, `config/app.yaml`, `/nonexistent/it's.md`, `../docs/guide.md`)")
        self.assertIn("R3 copies into app/mutants/ only the project dir's tracked top-level entries", e["hint"])

    def test_a_failing_plain_run_skips_the_sandbox(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/core.py": "X = 1\n", "tests/test_a.py": ""})

        def run(argv, cwd):
            self.calls.append(cwd)
            return (0, "mutmut, version 3.8.1\n") if "--version" in argv else (1, "1 failed in 0.01s\n")
        env = self.doctor(runner=run)
        self.assertEqual(env["trial"]["sandbox"], "skipped")
        self.assertEqual([c for c in self.calls if c.endswith("/mutants")], [])

    def test_the_sandbox_holds_the_sources_also_copy_and_mutmut_defaults_merged_over_a_tracked_mutants_dir(self):
        self.commit({"pyproject.toml": "[project]\n", "setup.cfg": "", "uv.lock": "", "test_root.py": "",
                     "tests/test_a.py": "", "test/test_b.py": "", "src/calc/core.py": "X = 1\n", "conftest.py": "",
                     "README.md": "", "docs/guide.md": "# guide\n", "mutants/docs/stale.md": ""})
        write(self.repo, {"notes.txt": "untracked\n"})
        seen = {}

        def run(argv, cwd):
            if cwd.endswith("/mutants"):
                seen["top"] = sorted(os.listdir(cwd))
                with open(os.path.join(cwd, "docs", "guide.md")) as f:
                    seen["guide"] = f.read()
            return (0, "mutmut, version 3.8.1\n") if "--version" in argv else (0, "1 passed in 0.01s\n")
        env = self.doctor(runner=run)
        self.assertEqual(env["trial"]["sandbox"], "pass")
        self.assertEqual(seen, {"top": ["README.md", "conftest.py", "docs", "pyproject.toml", "setup.cfg", "src", "test",
                                        "test_root.py", "tests", "uv.lock"], "guide": "# guide\n"})

    def test_doctor_leaves_the_checkout_as_it_was_and_no_worktree(self):
        self.commit({"pyproject.toml": "[project]\n", "calc/core.py": "X = 1\n", "docs/guide.md": "# guide\n",
                     "tests/test_docs.py": READS % 1})
        self.doctor()
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(len(git(self.repo, "worktree", "list").splitlines()), 1)

    def test_rust_trial_runs_no_sandbox(self):
        self.commit({"Cargo.toml": "[package]\n", "src/lib.rs": ""})

        def run(argv, cwd):
            self.calls.append(cwd)
            return 0, "test result: ok. 1 passed; 0 failed; 0 ignored\n"
        env = doctor.run(self.repo, stack="rust", runner=run)
        self.assertEqual(env["trial"], {"tests": "pass", "command": "cargo test", "mutation_tool": "present"})
        self.assertEqual([c for c in self.calls if c.endswith("/mutants")], [])


if __name__ == "__main__":
    unittest.main()
