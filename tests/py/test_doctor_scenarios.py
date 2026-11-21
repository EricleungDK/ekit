"""doctor and `.ekit/scenarios/` (#39): scenario files are test support, so `test-paths` should cover them, or R3 mutates
a scenario fixture as production code. Through `cli.main(["doctor", ...])`, read-only (`--no-trial`)."""
import contextlib
import io
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import cli
from test_adapter_cli import Repo

TESTS = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, 1)\n"


def caller(test_paths):
    globs = "".join(f"        {g}\n" for g in test_paths)
    return ("name: mech-review\non:\n  pull_request:\njobs:\n  mech-review:\n"
            "    uses: EricleungDK/ekit/.github/workflows/mech-review.yml@v0\n    with:\n      stack: python\n"
            f"      test-paths: |\n{globs}      protected-paths: |\n        .github/**\n")


class DoctorScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(os.path.join(self.tmp.name, "r"))

    def tearDown(self):
        self.tmp.cleanup()

    def doctor(self, files):
        self.repo.commit(dict({"pyproject.toml": "[project]\nname = 'x'\n", "calc.py": "X = 1\n",
                               "tests/test_calc.py": TESTS}, **files), "c")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["doctor", "--repo", self.repo.path, "--no-trial"])
        env = json.loads(out.getvalue())
        return rc, env, [(e["class"], e["problem"], e["hint"]) for e in env["entries"]]

    def test_a_stack_file_under_scenarios_that_no_test_path_covers_is_an_env_entry(self):
        rc, env, got = self.doctor({".ekit/scenarios/s/fixtures/fake_tool.py": "print(1)\n",
                                    ".ekit/scenarios/s/run.sh": "true\n",
                                    ".github/workflows/mech-review.yml": caller(["tests/**"])})
        self.assertEqual(rc, 1)
        self.assertEqual(got, [("env", "`.ekit/scenarios/` holds python files no test path covers "
                                       "(`.ekit/scenarios/s/fixtures/fake_tool.py`): R3 mutates them as production code",
                                "add `.ekit/scenarios/**` to test-paths: set test-paths: tests/**\n.ekit/scenarios/**")])

    def test_scenarios_covered_by_test_paths_give_no_entry(self):
        rc, env, got = self.doctor({".ekit/scenarios/s/fixtures/fake_tool.py": "print(1)\n",
                                    ".github/workflows/mech-review.yml": caller(["tests/**", ".ekit/scenarios/**"])})
        self.assertEqual((rc, got), (0, []))

    def test_the_wanted_test_paths_hold_both_globs_when_the_repo_has_scenarios(self):
        rc, env, got = self.doctor({".ekit/scenarios/s/run.sh": "true\n"})
        self.assertEqual(env["inputs"]["test-paths"], "tests/**\n.ekit/scenarios/**")

    def test_scenarios_with_no_file_of_the_stack_give_no_entry(self):
        rc, env, got = self.doctor({".ekit/scenarios/s/run.sh": "true\n",
                                    ".github/workflows/mech-review.yml": caller(["tests/**"])})
        self.assertEqual((rc, got), (0, []))

    def test_shell_only_scenarios_in_a_repo_with_no_tests_dir_add_no_test_paths_entry(self):
        self.repo.commit({"pyproject.toml": "[project]\nname = 'x'\n", "calc.py": "X = 1\n",
                          "test_calc.py": TESTS, ".ekit/scenarios/s/run.sh": "true\n",
                          ".github/workflows/mech-review.yml": caller(["tests/**"])}, "c")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["doctor", "--repo", self.repo.path, "--no-trial"])
        self.assertEqual((rc, json.loads(out.getvalue())["entries"]), (0, []))

    def test_files_outside_scenarios_that_are_not_of_the_stack_still_count_for_stack_auto(self):
        # the caller leaves `stack` at auto: doctor finds the project from pyproject.toml, a file python does not classify
        auto = caller(["tests/**", ".ekit/scenarios/**"]).replace("      stack: python\n", "")
        rc, env, got = self.doctor({".ekit/scenarios/s/run.sh": "true\n", ".github/workflows/mech-review.yml": auto})
        self.assertEqual((rc, got), (0, []))

    def test_a_repo_without_scenarios_wants_the_tests_glob_alone(self):
        rc, env, got = self.doctor({".github/workflows/mech-review.yml": caller(["tests/**"])})
        self.assertEqual((rc, env["inputs"]["test-paths"], got), (0, "tests/**", []))


if __name__ == "__main__":
    unittest.main()
