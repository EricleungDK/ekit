"""The eval stack-plan-js-to-ts grades the end state at HEAD: its scaffold's verdict script, run by evals/git-shim.sh
after every ref move (commit, reset, checkout), reads the plan at HEAD with tomllib, runs the kit's drift check on HEAD
and writes the verdict its regex graders read. A wrong end state (a TS entry only in a comment, the js entry gone, an
invalid plan, an edit not committed, a migration reset away or left on another branch) and the start state must not
pass."""
import os
import shutil
import subprocess
import tempfile
import unittest

import _kit
from scripts import shells  # bash: Git Bash on Windows, where a bare "bash" starts WSL's launcher
from test_eval_scaffold import case_dir, eval_git

CASE = case_dir("stack-plan-js-to-ts")
GIT = eval_git()
VERDICT = ("ekit-eval", "verdict.txt")
JS_RETIRING = '[[stack]]\nname = "js"\nfolder = "."\nadapter = "ts"\nstatus = "retiring"\n'
TS = '\n[[stack]]\nname = "web"\nfolder = "."\nadapter = "ts"\nstatus = "current"\n'


class Scaffold(unittest.TestCase):
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
        subprocess.run([*GIT, "-C", self.repo, "add", "-A"], check=True)
        subprocess.run([*GIT, "-C", self.repo, "commit", "-qm", "c"], check=True)

    def verdict(self):
        with open(os.path.join(self.repo, ".git", *VERDICT)) as f:
            return f.read().splitlines()

    def git(self, *args):
        subprocess.run([*GIT, "-C", self.repo, *args], check=True, capture_output=True)


class EndState(Scaffold):
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

    def test_a_linked_worktree_works_and_the_verdict_stays_the_main_checkouts(self):
        linked = os.path.join(os.path.dirname(self.repo), "linked")
        self.git("worktree", "add", "-q", "-b", "w2", linked)  # check=True: the shim must not fail it
        with open(os.path.join(linked, ".ekit", "stack-plan.toml"), "w", newline="\n") as f:
            f.write(JS_RETIRING + TS)
        subprocess.run([*GIT, "-C", linked, "commit", "-qam", "ts"], check=True, capture_output=True)
        subprocess.run([*GIT, "-C", linked, "checkout", "-q", "-b", "w3"], check=True, capture_output=True)
        self.assertEqual(self.verdict()[-1], "migrated: no")  # main's HEAD has not moved
        self.git("merge", "-q", "--ff-only", "w2")
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
        # a usage error (exit 2), whether the engine says why on stderr only or in its result's entry as well
        self.assertRegex(lines[2], r"^drift: not clean \(exit 2: .*stack\[1\] `js`, field name: `js` is already "
                                   r"stack\[0\]\)$")
        self.assertEqual(lines[-1], "migrated: no")

    def test_an_edit_left_uncommitted_is_not_the_end_state(self):
        self.commit(JS_RETIRING + TS)
        with open(os.path.join(self.repo, ".ekit", "stack-plan.toml"), "w") as f:
            f.write("")
        subprocess.run([*GIT, "-C", self.repo, "commit", "-qm", "empty", "--allow-empty"], check=True)
        self.assertIn("ts-entry: yes", self.verdict())  # HEAD still has the plan: the working tree is not read


@unittest.skipIf(os.name == "nt", "a bash script named git on PATH: POSIX only (the evals run in WSL on Windows)")
class ShimAsGit(Scaffold):
    """evals/run.sh's install: the shim as `git`, first on PATH. It finds the real git past itself, its git output
    and exit status are the real git's, and the verdict script's own git calls (and the kit's) do not recurse into a
    second verdict run."""

    def setUp(self):
        super().setUp()
        bin_dir = os.path.join(os.path.dirname(self.repo), "bin")
        os.mkdir(bin_dir)
        shutil.copy(GIT[1], os.path.join(bin_dir, "git"))
        os.chmod(os.path.join(bin_dir, "git"), 0o755)
        self.env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"])

    def run_git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, env=self.env)

    def test_a_commit_through_git_on_path_writes_the_verdict(self):
        with open(os.path.join(self.repo, ".ekit", "stack-plan.toml"), "w", newline="\n") as f:
            f.write(JS_RETIRING + TS)
        self.assertEqual(self.run_git("commit", "-qam", "ts").returncode, 0)
        self.assertEqual(self.verdict()[-1], "migrated: yes")

    def test_output_and_exit_status_are_the_real_gits(self):
        real = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True)
        self.assertEqual(self.run_git("rev-parse", "HEAD").stdout, real.stdout)
        self.assertEqual(self.run_git("no-such-command").returncode, 1)
        self.assertEqual(self.run_git("rev-parse", "no-such-rev").returncode, 128)


if __name__ == "__main__":
    unittest.main()
