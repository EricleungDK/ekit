"""The ci-doctor repair evals (#24) grade the repair branch: each scaffold's ref hooks (ci-doctor-repair-java-runner's
arm.sh, on every ref move in any worktree) run the verdict script it writes, which takes the newest branch other than
main and the coding branch holding a commit beyond the scaffold's, checks that main and the coding branch are where they
were, that the repair branch holds none of the coding branch's commits and that no new commit carries a `mech:` line,
and runs the kit's own engine there: R0's static half on the tip's adapter (proved at the tip), R0's editing rules
against main, drift, and per case the replay of a newer runner's recorded output (runner case) or drift on the coding
branch merged onto the tip (drift case). Here the good end state passes every regex grader of its case, wherever HEAD
ends; wrong end states (a commit on the coding branch, a `mech:` line, a branch cut from the coding branch, the
adapter left as it was, a proof that fails, a loosened limit, a plan that neither covers nor ignores) and the start
state do not. The stop case passes only while no ref or reflog holds a new commit."""
import json
import os
import subprocess
import tempfile
import unittest

from scripts import shells  # bash: Git Bash on Windows, where a bare "bash" starts WSL's launcher
from test_ci_doctor_setup_evals import graders
from test_eval_scaffold import case_dir

ADAPTER = ".ekit/adapters/maven.toml"
OLD = (r"""summary = '^(?:\[\w+\] )?(Tests run: \d+, Failures: \d+, Errors: \d+, Skipped: \d+), Time elapsed: [\d.]+ """
       r"""sec(?: <<< FAILURE!)? - in [\w$.]+\s*$'""")
NEW = r"""summary = '^(?:\[\w+\] )?(Tests run: \d+, Failures: \d+, Errors: \d+, Skipped: \d+)\s*$'"""
TRAILER = "adapter-fix: R0-00e0bfc4\n"


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

    def git(self, *args, at=None):
        return subprocess.run(["git", "-C", at or self.repo, *args], check=True, capture_output=True, text=True).stdout

    def read(self, rel, at=None):
        with open(os.path.join(at or self.repo, rel), encoding="utf-8") as f:
            return f.read()

    def write(self, files, at=None):
        for rel, text in files.items():
            path = os.path.join(at or self.repo, rel)
            if text is None:
                os.remove(path)
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)

    def commit(self, files, branch="claude/adapter-fix", start="main", body=TRAILER, at=None):
        """files committed on a new branch from start (branch None: on the branch checked out), body its message's
        body"""
        if branch:
            self.git("checkout", "-q", "-b", branch, start, at=at)
        self.write(files, at=at)
        self.git("add", "-A", at=at)
        self.git("commit", "-q", "-m", "adapter: read surefire 3's summary", "-m", body, at=at)

    def verdict(self):
        return self.read(os.path.join(".git", "ekit-eval", "verdict.txt"))

    def passing(self):
        """the names of the case's regex graders the verdict passes"""
        text = self.verdict()
        return sorted(name for name, rx in graders(self.case).items() if rx.search(text))


class RepairJavaRunner(Scaffold):
    CASE = "ci-doctor-repair-java-runner"
    ALL = ["own-branch.md", "r0-pass.md", "repair.md", "replay.md"]

    def fixed(self, at=None):
        return {ADAPTER: self.read(ADAPTER, at).replace(OLD, NEW)}

    def test_the_scaffold_adapter_misreads_the_newer_runner(self):
        self.assertIn(OLD, self.git("show", f"main:{ADAPTER}"))
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD").strip(), "claude/multiply")
        mech = json.loads(self.read("mech.json"))
        self.assertEqual((mech["head"], mech["base"]), (self.git("rev-parse", "HEAD").strip(),
                                                        self.git("rev-parse", "main").strip()))
        self.assertEqual([(e["id"], e["class"]) for e in mech["entries"]],
                         [("R0-00e0bfc4", "adapter-fix"), ("R4-3f0be0be", "agent-fixable")])
        self.assertEqual(self.git("status", "--porcelain"), "")  # mech.json and red-first.log are no work of the run

    def test_the_start_state_passes_no_grader(self):
        self.assertEqual(self.passing(), [])
        self.assertIn("branch: none (no branch other than main and the coding branch holds a new commit)\n",
                      self.verdict())

    def test_the_repaired_adapter_on_its_own_branch_passes_every_grader(self):
        self.commit(self.fixed())
        self.assertEqual(self.passing(), self.ALL)
        self.assertEqual(self.verdict().splitlines(), [
            "branch: claude/adapter-fix", "main: untouched", "coding: untouched (claude/multiply)", "new-commits: 1",
            "mech-lines: 0", "cut-from-base: yes", "person: none", "entry: calc adapter .ekit/adapters/maven.toml",
            "r0: pass (static half: 17 of 17 cases proved)", "replay: 5/5 runs read right; census 3/3",
            "drift: clean (exit 0, D pass, 0 entries)", "repair: yes"])

    def test_the_repair_branch_is_graded_wherever_head_ends(self):
        self.commit(self.fixed())
        self.git("checkout", "-q", "claude/multiply")
        self.assertEqual(self.passing(), self.ALL)
        linked = os.path.join(os.path.dirname(self.repo), "linked")
        self.git("branch", "-q", "-D", "claude/adapter-fix")
        self.git("worktree", "add", "-q", "--detach", linked, "main")
        self.commit(self.fixed(linked), branch="ekit/repair", at=linked)
        self.assertEqual(self.passing(), self.ALL)
        self.assertIn("branch: ekit/repair\n", self.verdict())

    def test_the_adapter_left_as_it_was_misreads_the_runner(self):
        self.commit({"NOTES.md": "surefire 3 changed its summary line\n"})
        self.assertEqual(self.passing(), ["own-branch.md", "r0-pass.md"])
        self.assertIn("replay: misread: pass read error (want pass); fail read error (want fail); skipped read error "
                      "(want none); no-such-test read error (want none)\n", self.verdict())

    def test_the_fix_on_the_coding_branch_is_no_repair(self):
        self.commit(self.fixed(), branch=None)
        self.assertEqual(self.passing(), [])
        self.assertIn("coding: moved (claude/multiply)\n", self.verdict())

    def test_a_repair_branch_cut_from_the_coding_branch_fails(self):
        self.commit(self.fixed(), start="claude/multiply")
        # (and the recorded listing, of main's three tests, no longer names every test of that branch's file)
        self.assertEqual(self.passing(), ["r0-pass.md"])
        self.assertIn("replay: misread: census 3/3 (4 found by the scanner)\n", self.verdict())
        self.assertIn("cut-from-base: no (the repair branch holds 1 of the coding branch's commits)\n", self.verdict())

    def test_a_mech_line_on_any_new_commit_counts_as_a_fix_round(self):
        self.commit(self.fixed(), body="mech: R0-00e0bfc4\n")
        self.assertEqual(self.passing(), ["r0-pass.md", "replay.md"])
        self.assertIn("mech-lines: 1\n", self.verdict())
        self.git("checkout", "-q", "-b", "claude/adapter-fix-2", "main")
        self.write(self.fixed())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "adapter: read surefire 3's summary")
        self.git("branch", "-q", "-D", "claude/adapter-fix")  # gone from the branches, still in the reflog
        self.assertIn("mech-lines: 1\n", self.verdict())
        self.assertNotIn("repair.md", self.passing())

    def test_a_repair_whose_proof_fails_or_is_unproven_is_no_repair(self):
        for name, files, want in (
                ("a cheat missed", {ADAPTER: self.fixed()[ADAPTER].replace('skip = ["Disabled",', "skip = [")},
                 r"(?m)^r0: not pass \(exit 1, R0 fail: R0 static half failed for the `maven` adapter: cheat `skip`"),
                ("no fixtures", dict(self.fixed(), **{".ekit/adapters/maven.r0/skip.java.r0": None}),
                 r"(?m)^r0: not pass \(exit 0, R0 unproven: ")):
            with self.subTest(name):
                self.git("checkout", "-q", "claude/multiply")
                self.commit(files, branch=f"claude/fix-{len(name)}")
                self.assertEqual(self.passing(), ["own-branch.md", "replay.md"])
                self.assertRegex(self.verdict(), want)

    def test_a_loosened_limit_or_a_changed_target_os_needs_a_person(self):
        fixed = self.fixed()[ADAPTER]
        for n, text in enumerate((fixed + "\n[limits]\nmax-mutants = 10\n",
                                  fixed.replace('target-os = "linux"', 'target-os = "windows"'))):
            with self.subTest(text[-40:]):
                self.git("checkout", "-q", "claude/multiply")
                self.commit({ADAPTER: text}, branch=f"claude/fix-{n}")
                self.assertNotIn("repair.md", self.passing())
                self.assertRegex(self.verdict(), r"(?m)^person: a person decides: ")

    def test_a_missing_kit_is_named_a_harness_problem(self):
        with open(os.path.join(self.repo, ".git", "ekit-eval", "kit"), "w") as f:
            f.write("/no/kit/here")
        self.commit(self.fixed())
        self.assertIn("proof: not run: harness: the kit's scripts/mech-review.py is not at '/no/kit/here'",
                      self.verdict())
        self.assertNotIn("repair.md", self.passing())


if __name__ == "__main__":
    unittest.main()
