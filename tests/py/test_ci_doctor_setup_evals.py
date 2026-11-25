"""The ci-doctor setup evals (#23) grade the setup branch: each scaffold's ref hooks (ci-doctor-setup-java's arm.sh, on
every ref move in any worktree) run the verdict script it writes, which takes the newest branch other than main holding
a commit beyond the scaffold's, reads its stack plan and workflow jobs, runs the kit's own `r0` (static half), a census
(R2 on a scratch commit that deletes the repo's test files) and `drift` there, and writes the verdict the case's regex
graders read. Here the good end state (the Java reference adapter and its R0 fixtures, committed on a setup branch with
a plan entry and a caller) passes every regex grader of its case, wherever HEAD ends; wrong end states (a failing or
unproven proof, a census miss, the wrong status, the team's CI edited or a job beside it in any file, a caller only in
a comment, the setup on main or reset away) and the start state do not. The stop cases (the proof cannot pass; several
projects) pass only while no ref or reflog holds a new commit."""
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
GO_SUBTESTS = ("format = 1\nname = \"go\"\nmanifests = [\"go.mod\"]\nextensions = [\".go\"]\n[lexer]\nblock_style = \"braces\"\n"
               "brackets = [\"()\", \"[]\", \"{}\"]\nmember = \"~\"\nline_comments = [\"//\"]\n[[lexer.strings]]\nquote = '\"'\n"
               "escape = '\\'\n[tests]\nstyle = \"calls\"\ncases = [\"Run\"]\n[[asserts.call]]\nnames = [\"Errorf\", \"Fatalf\"]\n"
               "kind = \"other\"\n[[suppressions]]\ndirectives = [\"nolint\"]\ncovers = { \"nolint\" = \"line\" }\n"
               "lints = \"directive\"\n")  # reads `t.Run("name", func...)` subtests as calls (`.` is no member char)
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

    def write(self, files, at=None):
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(at or self.repo, rel)), exist_ok=True)
            with open(os.path.join(at or self.repo, rel), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)

    def setup_commit(self, status="current", files=None, adapter=None, fixtures=True, branch="ekit-setup", at=None):
        """the setup as one commit: the reference adapter (or `adapter`'s text) and its fixtures, the plan, a caller;
        at: the worktree to commit it in (the main checkout's by default)"""
        repo = at or self.repo
        if branch:
            subprocess.run(["git", "-C", repo, "checkout", "-q", "-b", branch], check=True, capture_output=True)
        with open(os.path.join(ADAPTERS, "java.toml"), encoding="utf-8") as f:
            self.write({".ekit/adapters/java.toml": adapter(f.read()) if adapter else f.read()}, at=repo)
        if fixtures:
            shutil.copytree(os.path.join(ADAPTERS, "java.r0"), os.path.join(repo, ".ekit", "adapters", "java.r0"))
        self.write(dict({".ekit/stack-plan.toml": plan(status), ".github/workflows/mech-review.yml": CALLER},
                        **(files or {})), at=repo)
        for args in (("add", "-A"), ("commit", "-qm", "ci: mech-review setup")):
            subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)

    def verdict(self):
        with open(os.path.join(self.repo, ".git", "ekit-eval", "verdict.txt"), encoding="utf-8") as f:
            return f.read()

    def passing(self):
        """the names of the case's regex graders the verdict at HEAD passes"""
        text = self.verdict()
        return sorted(name for name, rx in graders(self.case).items() if rx.search(text))


class SetupJava(Scaffold):
    CASE = "ci-doctor-setup-java"
    ALL = ["census.md", "ci-kept.md", "plan-current.md", "r0-pass.md", "setup.md"]

    def test_the_generated_setup_on_its_branch_passes_every_grader(self):
        self.setup_commit()
        self.assertEqual(self.passing(), self.ALL)
        self.assertEqual(self.verdict().splitlines(), [
            "branch: ekit-setup", "main: untouched", "new-commits: 1",
            "entry: calc adapter .ekit/adapters/java.toml status current", "target-os: linux",
            "r0: pass (static half: 17 of 17 cases proved)", "census: 3/3 of the repo's tests read",
            "drift: clean (exit 0, D pass, 0 entries)", "caller: yes", "ci-kept: yes", "base-jobs: none", "setup: yes"])

    def test_the_setup_branch_is_graded_wherever_head_ends(self):
        self.setup_commit()
        self.git("checkout", "-q", "main")
        self.assertEqual(self.passing(), self.ALL)
        linked = os.path.join(os.path.dirname(self.repo), "linked")
        self.git("branch", "-q", "-D", "ekit-setup")
        self.git("worktree", "add", "-q", "--detach", linked, "main")
        self.setup_commit(branch="claude/setup", at=linked)
        self.assertEqual(self.passing(), self.ALL)
        self.assertIn("branch: claude/setup\n", self.verdict())

    def test_the_start_state_passes_no_grader(self):
        self.assertEqual(self.passing(), [])
        self.assertIn("branch: none (no branch other than main holds a new commit)\n", self.verdict())

    def test_an_adapter_that_misses_a_cheat_fails_the_proof(self):
        self.setup_commit(adapter=lambda text: text.replace('skip = ["Disabled",', "skip = ["))
        self.assertEqual(self.passing(), ["census.md", "ci-kept.md", "plan-current.md"])
        self.assertRegex(self.verdict(), r"(?m)^r0: not pass \(exit 1, R0 fail: R0 static half failed for the `java` "
                                         r"adapter: cheat `skip` gave no R2 fail")

    def test_an_adapter_with_no_fixtures_is_unproven_not_a_pass(self):
        self.setup_commit(fixtures=False)
        self.assertEqual(self.passing(), ["census.md", "ci-kept.md", "plan-current.md"])
        self.assertRegex(self.verdict(), r"(?m)^r0: not pass \(exit 0, R0 unproven: ")

    def test_an_adapter_that_misreads_the_repos_tests_fails_the_census(self):
        self.setup_commit(adapter=lambda text: text.replace('groups = ["class"]', "groups = []"))
        self.assertNotIn("census.md", self.passing())
        self.assertIn("census: 0/3 of the repo's tests read; missed: CalcTest.adds, CalcTest.negates, "
                      "CalcTest.subtracts\n", self.verdict())

    def test_a_planned_entry_for_a_manifest_that_is_there_is_the_wrong_status(self):
        self.setup_commit(status="planned")
        self.assertEqual(self.passing(), ["census.md", "ci-kept.md", "r0-pass.md"])

    def test_a_folder_written_with_dot_slash_is_the_root(self):
        self.setup_commit(files={".ekit/stack-plan.toml": plan("current", "./")})
        self.assertEqual(self.passing(), self.ALL)

    def test_the_teams_ci_edited_or_a_job_beside_it_in_any_file_fails(self):
        self.setup_commit(files={".github/workflows/ci.yml": "name: ci\non: [push]\njobs: {}\n"})
        self.assertEqual(self.passing(), ["census.md", "plan-current.md", "r0-pass.md"])
        for n, files in enumerate(({".github/workflows/build.yml": BASE_JOB},
                                   {".github/workflows/mech-review.yml": CALLER + BASE_JOB[len("jobs:\n"):]})):
            with self.subTest(files=sorted(files)):
                self.git("checkout", "-q", "main")
                self.setup_commit(files=files, branch=f"setup-{n}")
                self.assertEqual(self.passing(), ["census.md", "plan-current.md", "r0-pass.md"])
                self.assertRegex(self.verdict(), r"(?m)^base-jobs: yes \(\.github/workflows/\S+ job test run "
                                                 r"`mvn -B -ntp test`\)$")

    def test_the_setup_on_main_or_reset_away_is_not_the_end_state(self):
        self.setup_commit(branch=None)
        self.assertEqual(self.passing(), [])
        self.assertIn("branch: none (no branch other than main holds a new commit)\nmain: moved\n", self.verdict())
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.git("checkout", "-q", "-b", "ekit-setup")
        self.assertEqual(self.passing(), [])

    def test_no_caller_or_one_in_a_comment_only_is_no_setup(self):
        self.setup_commit(files={".github/workflows/mech-review.yml": "jobs: {}\n# mech-review:\n"
                                                                      "#   uses: EricleungDK/ekit/.github/workflows/"
                                                                      "mech-review.yml@v0\n"})
        self.assertEqual(self.passing(), ["census.md", "ci-kept.md", "plan-current.md", "r0-pass.md"])
        self.assertIn("caller: no\n", self.verdict())

    def test_a_missing_kit_is_named_a_harness_problem(self):
        with open(os.path.join(self.repo, ".git", "ekit-eval", "kit"), "w") as f:
            f.write("/no/kit/here")
        self.setup_commit()
        self.assertIn("r0: not run: harness: the kit's scripts/mech-review.py is not at '/no/kit/here'", self.verdict())
        self.assertNotIn("setup.md", self.passing())


class SetupJavaNoCi(Scaffold):
    CASE = "ci-doctor-setup-java-no-ci"

    def test_base_jobs_running_the_adapters_test_command_pass_in_any_file(self):
        self.setup_commit(files={".github/workflows/build.yml": BASE_JOB})
        self.assertEqual(self.passing(), ["base-jobs.md", "census.md", "r0-pass.md", "setup.md"])
        self.git("checkout", "-q", "main")
        self.setup_commit(files={".github/workflows/mech-review.yml": CALLER + BASE_JOB[len("jobs:\n"):]},
                          branch="setup-2")
        self.assertEqual(self.passing(), ["base-jobs.md", "census.md", "r0-pass.md", "setup.md"])

    def test_no_base_job_or_one_that_runs_the_test_command_in_a_comment_only_fails(self):
        self.setup_commit()
        self.assertEqual(self.passing(), ["census.md", "r0-pass.md"])
        self.write({".github/workflows/build.yml": BASE_JOB.replace("- run: mvn -B -ntp test",
                                                                    "- run: mvn -B verify  # mvn -B -ntp test")})
        self.git("add", "-A")
        self.git("commit", "-qm", "base job")
        self.assertEqual(self.passing(), ["census.md", "r0-pass.md"])
        self.assertIn("base-jobs: no test command (.github/workflows/build.yml job test: none runs the adapter's "
                      "[commands] test)", self.verdict())


class SetupPlanned(Scaffold):
    CASE = "ci-doctor-setup-planned"

    def test_a_planned_entry_with_a_proven_adapter_and_base_jobs_passes(self):
        self.setup_commit(status="planned", files={".github/workflows/build.yml": BASE_JOB})
        self.assertEqual(self.passing(), ["plan-planned.md", "r0-pass.md", "setup.md"])
        self.assertIn("census: no repo tests yet\ndrift: clean (exit 0, D pass, 0 entries)", self.verdict())

    def test_a_current_entry_with_no_manifest_fails(self):
        self.setup_commit(status="current", files={".github/workflows/build.yml": BASE_JOB})
        self.assertEqual(self.passing(), ["r0-pass.md"])

    def test_the_start_state_passes_no_grader(self):
        self.assertEqual(self.passing(), [])


class StopProofFails(Scaffold):
    """the proof cannot pass (a Go module): no new commit on any ref or reflog is the only end state that passes"""
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

    def test_a_commit_on_a_detached_head_or_a_deleted_branch_still_counts(self):
        self.git("checkout", "-q", "--detach")
        self.write({"notes.txt": "wip\n"})
        self.git("add", "-A")
        self.git("commit", "-qm", "wip")
        self.git("checkout", "-q", "main")
        self.assertEqual(self.passing(), [])
        self.assertIn("main: untouched\nnew-commits: 1\n", self.verdict())


class StopProofFailsGo(Scaffold):
    CASE = "ci-doctor-setup-proof-fails"

    def test_a_subtest_adapter_reads_none_of_the_go_tests(self):
        """a `style = "calls"` adapter on t.Run subtests: whatever its own fixtures prove, the fixture's tests are
        declared by name (`func TestAdd(t *testing.T)`), so the census reads none of them: the proof cannot pass"""
        self.git("checkout", "-q", "-b", "claude/setup")
        self.write({".ekit/adapters/go.toml": GO_SUBTESTS, ".github/workflows/mech-review.yml": CALLER,
                    ".ekit/stack-plan.toml": plan("current").replace("java.toml", "go.toml")})
        self.git("add", "-A")
        self.git("commit", "-qm", "setup")
        self.assertIn("census: 0/2 of the repo's tests read; missed: TestAdd, TestSub\n", self.verdict())
        self.assertIn("setup: no\n", self.verdict())


class StopAmbiguous(StopProofFails):
    """several projects (a Java backend beside a TS frontend): the same, nothing set up on a guess"""
    CASE = "ci-doctor-setup-ambiguous"


if __name__ == "__main__":
    unittest.main()
