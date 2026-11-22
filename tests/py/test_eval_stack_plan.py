"""The eval stack-plan-js-to-ts grades the end state at HEAD: its scaffold's ref hooks (on every commit, reset and
checkout) read the plan at HEAD with tomllib and run the kit's drift check on HEAD, and write the verdict its regex
graders read. A wrong end state (a TS entry only in a comment, the js entry gone, an invalid plan, an edit not
committed, a migration reset away or left on another branch) and the start state must not pass."""
import os
import shutil
import subprocess
import tempfile
import unittest

import _kit
from scripts import shells  # bash: Git Bash on Windows, where a bare "bash" starts WSL's launcher
from test_eval_scaffold import case_dir

CASE = case_dir("stack-plan-js-to-ts")
VERDICT = ("ekit-eval", "verdict.txt")
JS_RETIRING = '[[stack]]\nname = "js"\nfolder = "."\nadapter = "ts"\nstatus = "retiring"\n'
TS = '\n[[stack]]\nname = "web"\nfolder = "."\nadapter = "ts"\nstatus = "current"\n'


class EndState(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(tmp.name), "repo")
        os.mkdir(self.repo)
        bash = shells.find("bash")
        subprocess.run([bash, os.path.join(CASE, "setup.sh")], cwd=self.repo, check=True, capture_output=True,
                       env=shells.env_for(bash, "bash"))

    def commit(self, plan, files=()):
        for rel in files:
            os.makedirs(os.path.dirname(os.path.join(self.repo, rel)) or self.repo, exist_ok=True)
            with open(os.path.join(self.repo, rel), "w") as f:
                f.write("{}")
        with open(os.path.join(self.repo, ".ekit", "stack-plan.toml"), "w", newline="\n") as f:
            f.write(plan)
        subprocess.run(["git", "-C", self.repo, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-qm", "c"], check=True)

    def verdict(self):
        with open(os.path.join(self.repo, ".git", *VERDICT)) as f:
            return f.read().splitlines()

    def git(self, *args):
        subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True)

    def test_ts_current_beside_js_retiring_passes_all_three(self):
        self.commit(JS_RETIRING + TS)
        lines = self.verdict()
        self.assertIn("ts-entry: yes", lines)
        self.assertIn("js-retiring: yes", lines)
        self.assertRegex(lines[2], r"^drift: clean \(exit 0, D pass, 0 entries, messages \[\"retiring stack `js`")
        self.assertEqual(lines[-1], "migrated: yes")

    def test_the_start_state_passes_no_grader(self):
        lines = self.verdict()
        self.assertEqual(lines[:2], ["ts-entry: no", "js-retiring: no"])
        self.assertEqual(lines[-1], "migrated: no")  # its drift check is clean, but that alone is no end state

    def test_a_migration_reset_away_or_left_on_another_branch_is_not_the_end_state(self):
        self.commit(JS_RETIRING + TS)
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.assertEqual(self.verdict()[-1], "migrated: no")
        self.git("checkout", "-q", "-b", "side")
        self.commit(JS_RETIRING + TS)
        self.git("checkout", "-q", "main")
        self.assertEqual(self.verdict()[:2], ["ts-entry: no", "js-retiring: no"])
        self.assertEqual(self.verdict()[-1], "migrated: no")
        self.git("merge", "-q", "--ff-only", "side")
        self.assertEqual(self.verdict()[-1], "migrated: yes")

    def test_a_missing_kit_is_named_a_harness_problem(self):
        with open(os.path.join(self.repo, ".git", "ekit-eval", "kit"), "w") as f:
            f.write("/no/kit/here")
        self.commit(JS_RETIRING + TS)
        lines = self.verdict()
        self.assertRegex(lines[2], r"^drift: not run: harness: the kit's scripts/mech-review.py is not at '/no/kit/here'")
        self.assertEqual(lines[-1], "migrated: no")

    def test_a_kit_path_with_a_quote_works(self):
        kit = os.path.join(os.path.dirname(self.repo), "it's kit")  # a copy of the kit's scripts: any OS holds it
        shutil.copytree(_kit.SCRIPTS, os.path.join(kit, "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(self.repo, ".git", "ekit-eval", "kit"), "w") as f:
            f.write(kit)
        self.commit(JS_RETIRING + TS)
        self.assertEqual(self.verdict()[-1], "migrated: yes")

    def test_wrong_end_states_fail(self):
        comment = "".join("# " + line + "\n" for line in TS.splitlines())
        cases = {  # plan, extra manifest: the verdict's ts-entry, js-retiring, drift lines
            "a TS entry in a comment only": (JS_RETIRING + comment, None, ("no", "yes", "clean")),
            "the js entry renamed": (TS.lstrip(), None, ("yes", "no", "clean")),
            "a manifest no entry covers": (JS_RETIRING + TS, "api/pyproject.toml", ("yes", "yes", "not clean")),
        }
        for case, (plan, manifest, (ts, js, drift)) in cases.items():
            with self.subTest(case=case):
                self.commit(plan, files=[manifest] if manifest else ())
                lines = self.verdict()
                self.assertEqual(lines[:2], [f"ts-entry: {ts}", f"js-retiring: {js}"])
                self.assertTrue(lines[2].startswith(f"drift: {drift} "), lines[2])
                self.assertEqual(lines[-1], "migrated: no")

    def test_an_invalid_plan_fails_the_drift_check(self):
        self.commit(JS_RETIRING + TS.replace('name = "web"', 'name = "js"'))  # two entries named js
        lines = self.verdict()
        self.assertIn("js-retiring: no", lines)
        self.assertRegex(lines[2], r"^drift: not clean \(exit 2: ")
        self.assertEqual(lines[-1], "migrated: no")

    def test_an_edit_left_uncommitted_is_not_the_end_state(self):
        self.commit(JS_RETIRING + TS)
        with open(os.path.join(self.repo, ".ekit", "stack-plan.toml"), "w") as f:
            f.write("")
        subprocess.run(["git", "-C", self.repo, "commit", "-qm", "empty", "--allow-empty"], check=True)
        self.assertIn("ts-entry: yes", self.verdict())  # HEAD still has the plan: the working tree is not read


if __name__ == "__main__":
    unittest.main()
