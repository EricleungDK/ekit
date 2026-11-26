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
import re
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
            "mech-lines: 0", "cut-from-base: yes",
            "scope: the plan, adapter files, their fixtures and the caller only", "kept: yes", "fixtures: kept",
            "person: none", "entry: calc adapter .ekit/adapters/maven.toml",
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

    def test_the_repair_branch_is_preferred_over_a_newer_scratch_branch(self):
        self.commit(self.fixed())
        for on in ("claude/multiply", "main"):
            with self.subTest(head=on):
                self.git("checkout", "-q", "-B", f"scratch-{on.replace('/', '-')}", "main")
                self.write({"notes.txt": on})
                self.git("add", "-A")
                self.git("commit", "-q", "-m", "notes")
                self.git("checkout", "-q", on)
                self.assertEqual(self.passing(), self.ALL)
                self.assertIn("branch: claude/adapter-fix\n", self.verdict())

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

    def test_a_mech_line_anywhere_in_the_message_counts_as_git_grep_counts_it(self):
        self.commit(self.fixed(), body="fixes the misread (mech: R0-00e0bfc4)\n")
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

    def test_the_repair_touches_only_the_checker(self):
        """review round 1 [repair-diff-unbounded]: the PR's code cherry-picked, a command or limit changed (the replay
        never runs a command), or a runtime fixture gutted, beside the right fix, is no repair"""
        coding = {"src/main/java/com/example/Calc.java": self.git("show", "claude/multiply:src/main/java/com/example/Calc.java")}
        ctl = ".ekit/adapters/maven.r0/runtime/project/src/test/java/com/example/CtlTest.java.r0"
        for name, extra, want in (
                ("the PR's code", coding,
                 "scope: outside the checker (src/main/java/com/example/Calc.java)"),
                ("a command", {ADAPTER: self.fixed()[ADAPTER].replace('test = "mvn -B -ntp test"', 'test = "true"')},
                 "kept: no (commands changed)"),
                ("a limit", {ADAPTER: self.fixed()[ADAPTER] + "\n[limits]\ncensus = 50\n"},
                 "kept: no (limits changed)"),
                ("a runtime fixture", {ctl: self.read(ctl).split("    @Test\n    void fails()")[0] + "}\n"},
                 f"fixtures: changed ({ctl})")):
            with self.subTest(name):
                self.git("checkout", "-q", "claude/multiply")
                self.commit(dict(self.fixed(), **extra), branch=f"claude/fix-{len(name)}")
                self.assertIn(want + "\n", self.verdict())
                self.assertNotIn("repair.md", self.passing())

    def test_a_verdict_that_crashes_keeps_no_earlier_pass(self):
        """review round 1 [verdict-crash-keeps-stale]: a plan the script cannot read as it expects"""
        self.commit(self.fixed())
        self.assertIn("repair.md", self.passing())
        self.write({".ekit/stack-plan.toml": "stack = 1\n"})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "plan")
        self.assertEqual(self.passing(), [])
        self.assertRegex(self.verdict(), r"^verdict: crashed \(TypeError: .*\)\nrepair: no\n$")

    def test_a_missing_kit_is_named_a_harness_problem(self):
        with open(os.path.join(self.repo, ".git", "ekit-eval", "kit"), "w") as f:
            f.write("/no/kit/here")
        self.commit(self.fixed())
        self.assertIn("proof: not run: harness: the kit's scripts/mech-review.py is not at '/no/kit/here'",
                      self.verdict())
        self.assertNotIn("repair.md", self.passing())


PLAN = ".ekit/stack-plan.toml"
WEB = '\n[[stack]]\nname = "web"\nfolder = "web"\nadapter = "ts"\nstatus = "{}"\n'


class RepairDrift(Scaffold):
    CASE = "ci-doctor-repair-drift"
    ALL = ["own-branch.md", "plan.md", "repair.md"]

    def plan(self, extra="", ignore=None):
        text = self.git("show", f"main:{PLAN}") + extra
        return {PLAN: (f"ignore = {json.dumps(ignore)}\n\n" if ignore else "") + text}

    def test_the_scaffold_is_the_drift_block(self):
        mech = json.loads(self.read("mech.json"))
        self.assertEqual([(e["id"], e["check"], e["class"]) for e in mech["entries"]],
                         [("D-7e776699", "D", "adapter-fix")])
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD").strip(), "claude/web")
        self.assertEqual(self.passing(), [])

    def test_a_planned_entry_for_the_folder_passes_every_grader(self):
        self.commit(self.plan(WEB.format("planned")))
        self.assertEqual(self.passing(), self.ALL)
        self.assertEqual(self.verdict().splitlines()[6:], [
            "scope: the plan, adapter files, their fixtures and the caller only", "kept: yes", "fixtures: kept",
            "person: none", "plan: covers web (entry web adapter ts status planned)", "r0: built-in (ts)",
            "drift: clean (exit 0, D pass, 0 entries)",
            "merged: clean (drift on the coding branch merged onto the repair tip: exit 0, D pass, 0 entries)",
            "repair: yes"])

    def test_the_folder_in_ignore_passes_and_names_the_person_it_needs(self):
        self.commit(self.plan(ignore=["web"]))
        self.assertEqual(self.passing(), self.ALL)
        self.assertIn("person: a person decides: `ignore` gains `web` in .ekit/stack-plan.toml\n"
                      "plan: ignores web (ignore 'web')\n", self.verdict())

    def test_a_current_entry_passes_too_since_drift_judges_it_clean(self):
        # review round 1: no spec sentence makes `planned` the only status; drift is clean either way
        self.commit(self.plan(WEB.format("current")))
        self.assertEqual(self.passing(), self.ALL)

    def test_a_person_needed_beside_the_cover_is_no_repair(self):
        """review round 1 [drift-needs-human-passes]: only `ignore` may need a person (its criteria grade the stop)"""
        text = self.plan(WEB.format("planned"))[PLAN].replace('adapter = "python"\n', 'adapter = "python"\ntarget-os = "windows"\n', 1)
        self.commit({PLAN: text})
        self.assertRegex(self.verdict(), r"(?m)^person: a person decides: .*target-os")
        self.assertEqual(self.passing(), ["own-branch.md", "plan.md"])

    def test_a_plan_that_crashes_the_verdict_fails(self):
        self.commit(self.plan(WEB.format("planned")))
        self.write({PLAN: "ignore = 5\n" + self.read(PLAN)})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "plan")
        self.assertEqual(self.passing(), [])
        self.assertIn("verdict: crashed (TypeError: ", self.verdict())

    def test_a_plan_that_neither_covers_nor_ignores_the_folder_fails(self):
        self.commit(self.plan(WEB.format("planned").replace('folder = "web"', 'folder = "site"')))
        self.assertEqual(self.passing(), ["own-branch.md"])
        self.assertIn("plan: neither (no entry for 'web' and no ignore folder holding it)\n", self.verdict())
        self.assertIn("merged: not clean (", self.verdict())

    def test_an_entry_on_the_coding_branch_itself_is_no_repair(self):
        self.commit(self.plan(WEB.format("current")), branch=None)
        self.assertEqual(self.passing(), [])
        self.assertIn("coding: moved (claude/web)\n", self.verdict())

    def test_the_entry_with_a_mech_line_or_cut_from_the_coding_branch_fails(self):
        self.commit(self.plan(WEB.format("planned")), body="mech: D-7e776699\n")
        self.assertEqual(self.passing(), ["plan.md"])
        self.git("checkout", "-q", "claude/web")
        self.git("branch", "-q", "-D", "claude/adapter-fix")
        self.commit(self.plan(WEB.format("planned")), branch="claude/fix-2", start="claude/web")
        self.assertIn("cut-from-base: no (the repair branch holds 1 of the coding branch's commits)\n", self.verdict())
        self.assertNotIn("repair.md", self.passing())


class RepairBudget(Scaffold):
    """the proof cannot pass (a Go adapter): no new commit on any ref or reflog is the only end state that passes"""
    CASE = "ci-doctor-repair-budget"

    def test_the_scaffold_is_an_r0_entry_on_the_coding_branch(self):
        mech = json.loads(self.read("mech.json"))
        self.assertEqual([(e["id"], e["class"]) for e in mech["entries"]], [("R0-4a257e07", "adapter-fix")])
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD").strip(), "claude/mul")

    def test_only_the_start_state_passes(self):
        self.assertEqual(self.passing(), ["no-pr.md"])
        self.assertIn("main: untouched\ncoding: untouched (claude/mul)\nnew-commits: 0\n", self.verdict())
        self.commit({".ekit/adapters/go.toml": "# a draft\n"})
        self.assertEqual(self.passing(), [])

    def test_an_edit_on_the_coding_branch_or_a_stash_left_or_a_deleted_branch(self):
        self.write({"notes.txt": "wip\n"})
        self.git("stash", "-u")
        self.git("checkout", "-q", "main")
        self.assertEqual(self.passing(), ["no-pr.md"])
        self.commit({".ekit/adapters/go.toml": "# a draft\n"}, branch="claude/gone")
        self.git("checkout", "-q", "main")
        self.git("branch", "-q", "-D", "claude/gone")
        self.assertEqual(self.passing(), [])
        self.assertIn("new-commits: 1\n", self.verdict())

    def test_a_fixup_on_the_coding_branch_fails(self):
        self.commit({"calc_test.go": self.read("calc_test.go").replace("TestMul", "TestMultiply")}, branch=None)
        self.assertEqual(self.passing(), [])
        self.assertIn("coding: moved (claude/mul)\n", self.verdict())


IDS = r"`((?:R\d|D|CI)-[0-9a-f]{8})`"  # an entry id, as a grader quotes it


def llm_graders(case):
    """{grader file: text} of the case's llm graders"""
    out = {}
    for name in sorted(os.listdir(os.path.join(case, "graders"))):
        with open(os.path.join(case, "graders", name), encoding="utf-8") as f:
            text = f.read()
        if re.search(r"^type: llm$", text, re.M):
            out[name] = text
    return out


class TriageAdapterFix(Scaffold):
    """routing and labels are LLM-graded (#24): here the scaffold holds every source of the class, and each id a grader
    names is an entry of its JSON with the class the grader says"""
    CASE = "triage-adapter-fix"

    def test_every_source_of_the_class_is_an_entry(self):
        mech = json.loads(self.read("mech.json"))
        app = json.loads(self.read("mech-app.json"))
        entries = {e["id"]: e for e in mech["entries"] + app["entries"]}
        fix = sorted(i for i, e in entries.items() if e["class"] == "adapter-fix")
        self.assertEqual(fix, ["CI-599b7f05", "CI-f2f3b6a8", "D-7e776699", "R0-2b12725b", "R0-6d261a04"])
        self.assertEqual([entries[i]["problem"].split(":")[0] for i in fix], [
            "the stack plan does not read", "the adapter's parser failed",
            "manifests no stack in .ekit/stack-plan.toml covers", "R0 runtime half (run) failed for the `maven` adapter",
            "R0 static half failed for the `maven` adapter"])
        self.assertEqual((mech["head"], app["head"]), (self.git("rev-parse", "claude/calc").strip(),
                                                       self.git("rev-parse", "claude/app").strip()))
        named = {i for text in llm_graders(self.case).values() for i in re.findall(IDS, text)}
        self.assertEqual(named, set(entries))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_the_entry_r0_blocks_is_graded_as_held(self):
        r2 = next(e for e in json.loads(self.read("mech.json"))["entries"] if e["id"] == "R2-f3a6a4fd")
        self.assertEqual((r2["class"], r2.get("blocked")), ("agent-fixable", "R0"))
        self.assertIn("`R2-f3a6a4fd` is marked `blocked: R0`: it gets no fix round now.",
                      llm_graders(self.case)["next-action.md"])


class OrchestrateAdapterFixRoute(unittest.TestCase):
    """the orchestrator's prompt carries the runner case's real entries, and its graders name them"""

    def test_the_prompt_holds_the_runner_cases_entries(self):
        case = case_dir("orchestrate-adapter-fix-route")
        with open(os.path.join(case, "prompt.md"), encoding="utf-8") as f:
            prompt = f.read()
        with open(os.path.join(case_dir("ci-doctor-repair-java-runner"), "setup.sh"), encoding="utf-8") as f:
            runner = json.loads(re.search(r"<<'JSON'\n(.*?)\nJSON\n", f.read(), re.S).group(1))
        block = re.search(r"```json\n(.*?)\n```", prompt, re.S).group(1)
        self.assertEqual([json.loads(line) for line in block.splitlines()], runner["entries"])
        named = {i for text in llm_graders(case).values() for i in re.findall(IDS, text)}
        self.assertEqual(named, {"R0-00e0bfc4", "R4-3f0be0be"})
        self.assertIn("Rounds used: review 1, taste 0, CI 0.", prompt)
        self.assertIn("review 2, taste 3, CI 3", llm_graders(case)["rounds.md"])


if __name__ == "__main__":
    unittest.main()
