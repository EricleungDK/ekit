"""The ci-doctor setup evals (#23) grade the end state at HEAD: each scaffold's ref hooks (ci-doctor-setup-java's arm.sh,
on every commit, reset and checkout) run the verdict script it writes, which reads the stack plan and the workflows at HEAD and runs the
kit's own `r0` (static half) and `drift` on HEAD, and write the verdict the case's regex graders read. Here the good
end state (the Java reference adapter and its R0 fixtures, committed on a setup branch with a plan entry and a caller)
passes every regex grader of its case; wrong end states (a failing or unproven proof, the wrong status, the team's CI
edited or a base job beside it, the setup on main or reset away) and the start state do not. The stop cases (the proof
cannot pass; several projects) pass only while nothing is committed."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from scripts import shells  # bash: Git Bash on Windows, where a bare "bash" starts WSL's launcher
from test_eval_scaffold import case_dir

ADAPTERS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "adapters")
CALLER = "jobs:\n  mech-review:\n    uses: EricleungDK/ekit/.github/workflows/mech-review.yml@v0\n"
BASE_JOB = ("jobs:\n  test:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@v4\n"
            "      - run: mvn -B -ntp test\n")


def plan(status, folder="."):
    return f'[[stack]]\nname = "calc"\nfolder = "{folder}"\nadapter = ".ekit/adapters/java.toml"\nstatus = "{status}"\n'


def graders(case):
    """{grader file: compiled pattern} of the case's regex graders (front matter `pattern: '...'`, flags m)"""
    out = {}
    for name in sorted(os.listdir(os.path.join(case, "graders"))):
        with open(os.path.join(case, "graders", name), encoding="utf-8") as f:
            text = f.read()
        if re.search(r"^type: regex$", text, re.M):
            pattern = re.search(r"^pattern: '(.*)'$", text, re.M).group(1).replace("''", "'")
            out[name] = re.compile(pattern, re.M if re.search(r"^flags: m$", text, re.M) else 0)
    return out


class Scaffold(unittest.TestCase):
    CASE = None

    def setUp(self):
        self.case = case_dir(self.CASE)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(tmp.name), "repo")
        os.mkdir(self.repo)
        bash = shells.find("bash")
        subprocess.run([bash, os.path.join(self.case, "setup.sh")], cwd=self.repo, check=True, capture_output=True,
                       env=shells.env_for(bash, "bash"))

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, text=True).stdout

    def write(self, files):
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(self.repo, rel)), exist_ok=True)
            with open(os.path.join(self.repo, rel), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)

    def setup_commit(self, status="current", files=None, adapter=None, fixtures=True, branch="ekit-setup"):
        """the setup as one commit: the reference adapter (or `adapter`'s text) and its fixtures, the plan, a caller"""
        if branch:
            self.git("checkout", "-q", "-b", branch)
        with open(os.path.join(ADAPTERS, "java.toml"), encoding="utf-8") as f:
            self.write({".ekit/adapters/java.toml": adapter(f.read()) if adapter else f.read()})
        if fixtures:
            shutil.copytree(os.path.join(ADAPTERS, "java.r0"), os.path.join(self.repo, ".ekit", "adapters", "java.r0"))
        self.write(dict({".ekit/stack-plan.toml": plan(status), ".github/workflows/mech-review.yml": CALLER},
                        **(files or {})))
        self.git("add", "-A")
        self.git("commit", "-qm", "ci: mech-review setup")

    def verdict(self):
        with open(os.path.join(self.repo, ".git", "ekit-eval", "verdict.txt"), encoding="utf-8") as f:
            return f.read()

    def passing(self):
        """the names of the case's regex graders the verdict at HEAD passes"""
        text = self.verdict()
        return sorted(name for name, rx in graders(self.case).items() if rx.search(text))


class SetupJava(Scaffold):
    CASE = "ci-doctor-setup-java"
    ALL = ["ci-kept.md", "plan-current.md", "r0-pass.md", "setup.md"]

    def test_the_generated_setup_on_its_branch_passes_every_grader(self):
        self.setup_commit()
        self.assertEqual(self.passing(), self.ALL)
        lines = self.verdict().splitlines()
        self.assertEqual(lines[:5], ["branch: ekit-setup", "main: untouched", "new-commits: 1",
                                     "entry: calc adapter .ekit/adapters/java.toml status current", "target-os: linux"])
        self.assertEqual(lines[5], "r0: pass (static half: 17 of 17 cases proved)")
        self.assertEqual(lines[6:], ["drift: clean (exit 0, D pass, 0 entries)", "caller: yes", "ci-kept: yes",
                                     "base-jobs: none", "setup: yes"])

    def test_the_start_state_passes_only_the_kept_ci(self):
        self.assertEqual(self.passing(), ["ci-kept.md"])  # the team's CI is there as it was: nothing set up yet
        self.assertIn("drift: not clean (exit 0, no plan: no D)", self.verdict())

    def test_an_adapter_that_misses_a_cheat_fails_the_proof(self):
        self.setup_commit(adapter=lambda text: text.replace('skip = ["Disabled",', "skip = ["))
        self.assertEqual(self.passing(), ["ci-kept.md", "plan-current.md"])
        self.assertRegex(self.verdict(), r"(?m)^r0: not pass \(exit 1, R0 fail: R0 static half failed for the `java` "
                                         r"adapter: cheat `skip` gave no R2 fail")

    def test_an_adapter_with_no_fixtures_is_unproven_not_a_pass(self):
        self.setup_commit(fixtures=False)
        self.assertEqual(self.passing(), ["ci-kept.md", "plan-current.md"])
        self.assertRegex(self.verdict(), r"(?m)^r0: not pass \(exit 0, R0 unproven: ")

    def test_a_planned_entry_for_a_manifest_that_is_there_is_the_wrong_status(self):
        self.setup_commit(status="planned")
        self.assertEqual(self.passing(), ["ci-kept.md", "r0-pass.md"])

    def test_the_teams_ci_edited_or_a_base_job_beside_it_fails(self):
        self.setup_commit(files={".github/workflows/ci.yml": "name: ci\non: [push]\njobs: {}\n"})
        self.assertEqual(self.passing(), ["plan-current.md", "r0-pass.md"])
        self.git("checkout", "-q", "main")
        self.setup_commit(files={".github/workflows/build.yml": BASE_JOB}, branch="setup-2")
        self.assertEqual(self.passing(), ["plan-current.md", "r0-pass.md"])
        self.assertIn("base-jobs: yes (.github/workflows/build.yml run `mvn -B -ntp test`)", self.verdict())

    def test_the_setup_on_main_or_reset_away_is_not_the_end_state(self):
        self.setup_commit(branch=None)
        self.assertNotIn("setup.md", self.passing())
        self.assertIn("branch: main\nmain: moved\n", self.verdict())
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.git("checkout", "-q", "-b", "ekit-setup")
        self.assertEqual(self.passing(), ["ci-kept.md"])

    def test_no_caller_is_no_setup(self):
        self.setup_commit()
        self.git("rm", "-q", ".github/workflows/mech-review.yml")
        self.git("commit", "-qm", "no caller")
        self.assertEqual(self.passing(), ["ci-kept.md", "plan-current.md", "r0-pass.md"])

    def test_a_missing_kit_is_named_a_harness_problem(self):
        with open(os.path.join(self.repo, ".git", "ekit-eval", "kit"), "w") as f:
            f.write("/no/kit/here")
        self.setup_commit()
        self.assertIn("r0: not run: harness: the kit's scripts/mech-review.py is not at '/no/kit/here'", self.verdict())
        self.assertNotIn("setup.md", self.passing())


class SetupJavaNoCi(Scaffold):
    CASE = "ci-doctor-setup-java-no-ci"

    def test_base_jobs_running_the_adapters_test_command_pass(self):
        self.setup_commit(files={".github/workflows/build.yml": BASE_JOB})
        self.assertEqual(self.passing(), ["base-jobs.md", "r0-pass.md", "setup.md"])

    def test_no_base_job_or_one_that_runs_no_test_command_fails(self):
        self.setup_commit()
        self.assertEqual(self.passing(), ["r0-pass.md"])
        self.write({".github/workflows/build.yml": BASE_JOB.replace("mvn -B -ntp test", "mvn -B verify")})
        self.git("add", "-A")
        self.git("commit", "-qm", "base job")
        self.assertEqual(self.passing(), ["r0-pass.md"])
        self.assertIn("base-jobs: no test command (.github/workflows/build.yml never run the adapter's [commands] "
                      "test)", self.verdict())


class SetupPlanned(Scaffold):
    CASE = "ci-doctor-setup-planned"

    def test_a_planned_entry_with_a_proven_adapter_and_base_jobs_passes(self):
        self.setup_commit(status="planned", files={".github/workflows/build.yml": BASE_JOB})
        self.assertEqual(self.passing(), ["plan-planned.md", "r0-pass.md", "setup.md"])
        self.assertIn("drift: clean (exit 0, D pass, 0 entries)", self.verdict())  # no manifest: dormant, not drift

    def test_a_current_entry_with_no_manifest_fails(self):
        self.setup_commit(status="current", files={".github/workflows/build.yml": BASE_JOB})
        self.assertEqual(self.passing(), ["r0-pass.md"])

    def test_the_start_state_passes_no_grader(self):
        self.assertEqual(self.passing(), [])


class StopProofFails(Scaffold):
    """the proof cannot pass (a Go module): no commit on any branch is the only end state that passes"""
    CASE = "ci-doctor-setup-proof-fails"

    def test_only_the_start_state_passes(self):
        self.assertEqual(self.passing(), ["no-pr.md"])
        self.git("checkout", "-q", "-b", "claude/setup")
        self.write({"notes.txt": "wip\n"})
        self.git("add", "-A")
        self.git("commit", "-qm", "wip")
        self.assertEqual(self.passing(), [])
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--ff-only", "claude/setup")
        self.assertIn("main: moved\nnew-commits: 1\n", self.verdict())


class StopAmbiguous(StopProofFails):
    """several projects (a Java backend beside a TS frontend): the same, nothing set up on a guess"""
    CASE = "ci-doctor-setup-ambiguous"


if __name__ == "__main__":
    unittest.main()
