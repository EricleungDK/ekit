"""The ci-doctor repair evals (#24) grade the repair branch: evals/git-shim.sh runs the verdict script each scaffold
writes (ci-doctor-repair-java-runner's arm.sh) after every ref move in any worktree; it takes the newest branch other
than main and the coding branch holding a commit beyond the scaffold's, checks that main and the coding branch are where
they were, that the repair branch holds none of the coding branch's commits and that no new commit carries a `mech:`
line, and runs the kit's own engine there: R0's static half on the tip's adapter (proved at the tip), R0's editing rules
against main, drift, and per case the replay of a newer runner's recorded output (runner case) or drift on the coding
branch merged onto the tip (drift case). Here the good end state passes every regex grader of its case, wherever HEAD
ends; wrong end states (a commit on the coding branch, a `mech:` line, a branch cut from the coding branch, the adapter
left as it was, a proof that fails, a loosened limit, a plan that neither covers nor ignores) and the start state do
not. The stop case passes only while no ref or reflog holds a new commit."""
import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest

from scripts import shells  # bash: Git Bash on Windows, where a bare "bash" starts WSL's launcher
from test_ci_doctor_setup_evals import graders
from test_eval_scaffold import case_dir, eval_git
from scripts.mech_review import cli

ADAPTER = ".ekit/adapters/maven.toml"
PLAN = ".ekit/stack-plan.toml"
OLD = (r"""summary = '^(?:\[\w+\] )?(Tests run: \d+, Failures: \d+, Errors: \d+, Skipped: \d+), Time elapsed: [\d.]+ """
       r"""sec(?: <<< FAILURE!)? - in [\w$.]+\s*$'""")
NEW = r"""summary = '^(?:\[\w+\] )?(Tests run: \d+, Failures: \d+, Errors: \d+, Skipped: \d+)\s*$'"""
TRAILER = "adapter-fix: R0-00e0bfc4\n"
GIT = eval_git()


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
        return subprocess.run([*GIT, "-C", at or self.repo, *args], check=True, capture_output=True, text=True).stdout

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
            "mech-lines: 0", "cut-from-base: yes", "allow: yes",
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

    def copy_fixtures(self, to):
        """{path: text}: maven.r0's files under the fixture dir `to`"""
        files, src = {}, os.path.join(self.repo, ".ekit", "adapters", "maven.r0")
        for root, _, names in os.walk(src):
            for fn in names:
                rel = os.path.relpath(os.path.join(root, fn), src).replace(os.sep, "/")
                files[f"{to}/{rel}"] = self.read(os.path.join(".ekit/adapters/maven.r0", rel))
        return files

    def test_every_change_beside_the_fix_is_no_repair(self):
        """review rounds 1-3 [repair-diff-unbounded]: the allowlist is the adapter file alone, its TOML the base's but
        for the [run.outcome] and [run.list] patterns; each known way past an earlier grader reads `allow: no`"""
        fixed = self.fixed()[ADAPTER]
        ctl = ".ekit/adapters/maven.r0/runtime/project/src/test/java/com/example/CtlTest.java.r0"
        wf = ".github/workflows/mech-review.yml"
        to_maven2 = self.read(PLAN).replace('adapter = ".ekit/adapters/maven.toml"', 'adapter = ".ekit/adapters/maven2.toml"')
        shapes = {
            "the PR's code": {"src/main/java/com/example/Calc.java":
                              self.git("show", "claude/multiply:src/main/java/com/example/Calc.java")},
            "test = true": {ADAPTER: fixed.replace('test = "mvn -B -ntp test"', 'test = "true"')},
            "a list command": {ADAPTER: fixed.replace('command = "mvn -B -ntp test -Djunit', 'command = "echo -Djunit')},
            "a limit": {ADAPTER: fixed + "\n[limits]\ncensus = 50\n"},
            "a gutted fixture": {ctl: self.read(ctl).split("    @Test\n    void fails()")[0] + "}\n"},
            "a renamed adapter": dict(self.copy_fixtures(".ekit/adapters/maven2.r0"),
                                      **{".ekit/adapters/maven2.toml": fixed, PLAN: to_maven2}),
            "the caller workflow": {wf: self.read(wf).replace("src/test/**", "nowhere/**")},
            "a decoy entry first": {PLAN: '[[stack]]\nname = "decoy"\nfolder = "."\nadapter = ".ekit/adapters/maven.toml"'
                                          '\nstatus = "planned"\n\n' + self.read(PLAN)},
            "a runtime-surefire shadow dir": {".ekit/adapters/maven.r0/runtime-surefire/controls.json": "{}\n"},
        }
        for n, (name, extra) in enumerate(shapes.items()):
            with self.subTest(name):
                self.git("checkout", "-q", "claude/multiply")
                self.commit(dict({ADAPTER: fixed}, **extra), branch=f"claude/fix-{n}")
                self.assertRegex(self.verdict(), r"(?m)^allow: no \(")
                self.assertIn("repair: no\n", self.verdict())
                self.assertNotIn("repair.md", self.passing())

    def test_a_comment_edit_beside_the_fix_passes(self):
        self.commit({ADAPTER: self.fixed()[ADAPTER].replace("# The calc team's adapter", "# The calc team's own adapter")})
        self.assertEqual(self.passing(), self.ALL)
        self.assertIn("allow: yes\n", self.verdict())

    def test_a_malformed_harness_file_writes_a_crashed_verdict(self):
        """review round 2 [verdict-crash early reads]"""
        self.commit(self.fixed())
        with open(os.path.join(self.repo, ".git", "ekit-eval", "expect.json"), "w") as f:
            f.write("{not json")
        self.git("checkout", "-q", "main")
        self.assertRegex(self.verdict(), r"^verdict: crashed \(JSONDecodeError: .*\)\nrepair: no\n$")

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
            "allow: yes", "person: none", "plan: covers web (entry web adapter ts status planned)", "r0: built-in (ts)",
            "drift: clean (exit 0, D pass, 0 entries)",
            "merged: clean (drift on the coding branch merged onto the repair tip: exit 0, D pass, 0 entries)",
            "repair: yes"])

    def test_the_folder_in_ignore_passes_and_names_the_person_it_needs(self):
        self.commit(self.plan(ignore=["web"]))
        self.assertEqual(self.passing(), self.ALL)
        self.assertIn("person: a person decides: `ignore` gains `web` in .ekit/stack-plan.toml\n"
                      "plan: ignores web (ignore 'web')\n", self.verdict())

    def test_the_entrys_status_is_left_to_the_criteria(self):
        # review round 3: the script grades no status; the criteria name `planned` (the manifest arrives with the PR)
        self.commit(self.plan(WEB.format("current")))
        self.assertEqual(self.passing(), self.ALL)

    def test_the_new_entry_placed_first_passes(self):
        self.commit({PLAN: WEB.format("planned").lstrip("\n") + "\n" + self.git("show", f"main:{PLAN}")})
        self.assertEqual(self.passing(), self.ALL)
        self.assertIn("allow: yes\n", self.verdict())

    def test_every_plan_change_beyond_the_cover_folder_is_no_repair(self):
        """review round 3: the allowlist keeps every base entry as it is, adds entries for web/ only (a built-in or a
        file under .ekit/adapters/), lets `ignore` gain web/ at most, and adds files under .ekit/adapters/ only"""
        base = self.git("show", f"main:{PLAN}")
        web = WEB.format("planned")

        def dot(name, adapter, status):
            return f'\n[[stack]]\nname = "{name}"\nfolder = "."\nadapter = "{adapter}"\nstatus = "{status}"\n'

        shapes = {
            "a decoy entry first": {PLAN: dot("decoy", "python", "planned").lstrip("\n") + base + web},
            "retiring + current for the base folder": {PLAN: base.replace('"current"', '"retiring"') + web
                                                      + dot("slug2", ".ekit/adapters/py.toml", "current"),
                                                      ".ekit/adapters/py.toml": 'format = 1\nname = "py"\n'},
            "current + current for the base folder": {PLAN: base + web + dot("slug2", "rust", "current")},
            "a built-in swapped for an adapter file": {PLAN: base.replace('adapter = "python"',
                                                                          'adapter = ".ekit/adapters/py.toml"') + web,
                                                      ".ekit/adapters/py.toml": 'format = 1\nname = "py"\n'},
            "the plan naming pyproject.toml as an adapter": {PLAN: base + web.replace('adapter = "ts"',
                                                                                     'adapter = "pyproject.toml"')},
            "an edit to pyproject.toml": {PLAN: base + web, "pyproject.toml": '[project]\nname = "slug"\n'},
            "a file named like a built-in": {PLAN: base + web, ".ekit/adapters/ts.toml": 'format = 1\nname = "ts"\n'},
            "an ignore beyond the cover folder": {PLAN: 'ignore = ["web", "src"]\n\n' + base},
            "another top-level key": {PLAN: 'format = 2\n' + base + web},
        }
        for n, (name, files) in enumerate(shapes.items()):
            with self.subTest(name):
                self.git("checkout", "-q", "claude/web")
                self.commit(files, branch=f"claude/fix-{n}")
                self.assertRegex(self.verdict(), r"(?m)^allow: no \(")
                self.assertNotIn("repair.md", self.passing())

    def test_a_person_needed_beside_the_cover_is_no_repair(self):
        """review round 1 [drift-needs-human-passes]: only `ignore` may need a person (its criteria grade the stop)"""
        text = self.plan(WEB.format("planned"))[PLAN].replace('adapter = "python"\n', 'adapter = "python"\ntarget-os = "windows"\n', 1)
        self.commit({PLAN: text})
        self.assertRegex(self.verdict(), r"(?m)^person: a person decides: .*target-os")
        self.assertEqual(self.passing(), ["own-branch.md", "plan.md"])

    def test_only_the_cases_own_folder_may_be_ignored(self):
        """review round 2 [drift-needs-human-passes]: an ignore beyond web/ (the python package's own src/) is a
        person's call like any other"""
        for n, files in enumerate((self.plan(ignore=["web", "src"]), self.plan(WEB.format("planned"), ignore=["src"]))):
            with self.subTest(n):
                self.git("checkout", "-q", "claude/web")
                self.commit(files, branch=f"claude/fix-{n}")
                self.assertRegex(self.verdict(), r"(?m)^person: a person decides: .*`ignore` gains `src`")
                self.assertNotIn("repair.md", self.passing())

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
        self.assertEqual(fix, ["CI-599b7f05", "CI-f2f3b6a8", "D-7e776699", "R0-00e0bfc4", "R0-6d261a04"])
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
        r2 = next(e for e in json.loads(self.read("mech.json"))["entries"] if e["id"] == "R2-0734ae9c")
        self.assertEqual((r2["class"], r2.get("blocked")), ("agent-fixable", "R0"))
        self.assertIn("`R2-0734ae9c` is marked `blocked: R0`: it gets no fix round now.",
                      llm_graders(self.case)["next-action.md"])
        self.assertIn("It plans no fix for it, now or for later", llm_graders(self.case)["next-action.md"])


class TriageAdapterFixIsReal(Scaffold):
    """the triage scaffold is the repo its results report (both runs refused two CI entries whose plan stack, adapter,
    SHA and position the files did not hold): the kit's own drift, r0 (static half) and r2 at each result's base and
    head give the entries the JSON holds, id and text. Not reproduced (the setup.sh header's named limits): the parser
    run (ktfacts is not installed), R0's runtime half, R1 and R4"""
    CASE = "triage-adapter-fix"

    def kit(self, *argv):
        """(exit code, envelope) of `mech-review.py <argv>` on the scaffold, through cli.main in this process"""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main([argv[0], "--repo", self.repo, *argv[1:]])
        return rc, json.loads(out.getvalue())

    def result(self, name):
        with open(os.path.join(self.repo, name), encoding="utf-8") as f:
            data = json.load(f)
        return data, {e["id"]: e for e in data["entries"]}

    def assertEntry(self, got, want):
        self.assertEqual({k: v for k, v in want.items() if k != "blocked"}, got)

    def test_each_result_names_its_branch_head_and_a_base_on_main(self):
        for name, branch, base in (("mech.json", "claude/calc", "main"), ("mech-app.json", "claude/app", "main~1")):
            with self.subTest(name):
                data, _ = self.result(name)
                self.assertEqual((data["base"], data["head"]),
                                 (self.git("rev-parse", base).strip(), self.git("rev-parse", branch).strip()))
                self.assertEqual(self.git("merge-base", "main", branch).strip(), data["base"])
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD").strip(), "claude/calc")

    def test_the_bad_plan_entry_is_drift_at_the_app_head(self):
        data, entries = self.result("mech-app.json")
        rc, env = self.kit("drift", "--base", data["base"], "--head", data["head"])
        self.assertEqual(rc, 2)
        self.assertEqual(env["checks"]["D"], data["checks"]["D"])
        self.assertEqual(len(env["entries"]), 1)
        self.assertEntry(env["entries"][0], entries["CI-599b7f05"])

    def test_the_parser_entry_names_a_file_the_base_plan_runs_ktfacts_on(self):
        _, entries = self.result("mech-app.json")
        problem = entries["CI-f2f3b6a8"]["problem"]
        m = re.fullmatch(r"the adapter's parser failed: parser `(\S+)` on (\S+): exited with status 1: App\.kt:(\d+):(\d+): "
                         r".+, found `(\w+)`", problem)
        self.assertTrue(m, problem)
        program, path, line, col, token = m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), m.group(5)
        self.assertEqual(path, entries["CI-f2f3b6a8"]["file"])
        plan = self.git("show", "main~1:.ekit/stack-plan.toml")
        self.assertIn('name = "app"\nfolder = "app"\nadapter = ".ekit/adapters/kotlin.toml"\nstatus = "current"', plan)
        self.assertIn(f'[parser]\ncommand = "{program} ', self.git("show", "main~1:.ekit/adapters/kotlin.toml"))
        head = self.git("show", f"claude/app:{path}").splitlines()
        self.assertTrue(head[line - 1][col - 1:].startswith(token + " "), head[line - 1])  # the guard ktfacts misses
        # the agent under test reads the checked-out file alone: there the position holds another token, so the
        # message reads as the head's change, never as a position the file does not hold
        self.assertFalse(self.read(path).splitlines()[line - 1][col - 1:].startswith(token))
        self.assertNotIn(head[line - 1], self.git("show", f"main~1:{path}").splitlines())

    def test_the_drift_entry_is_drift_at_the_calc_head(self):
        data, entries = self.result("mech.json")
        rc, env = self.kit("drift", "--base", data["base"], "--head", data["head"])
        self.assertEqual(rc, 1)
        self.assertEqual(env["checks"]["D"], data["checks"]["D"])
        self.assertEqual(len(env["entries"]), 1)
        self.assertEntry(env["entries"][0], entries["D-7e776699"])

    def test_the_static_r0_entry_is_the_calc_bases_adapter_and_the_app_bases_passes(self):
        data, entries = self.result("mech.json")
        _, env = self.kit("r0", "--base", data["base"], "--head", data["head"], "--stack", "maven", "--project-dir", ".")
        self.assertEqual(env["checks"]["R0"]["status"], "fail")
        self.assertTrue(data["checks"]["R0"]["note"].startswith(env["checks"]["R0"]["note"] + "; "),
                        env["checks"]["R0"]["note"])
        self.assertEqual(len(env["entries"]), 1)
        self.assertEntry(env["entries"][0], entries["R0-6d261a04"])
        app, _ = self.result("mech-app.json")
        _, env = self.kit("r0", "--base", app["base"], "--head", app["head"], "--stack", "maven", "--project-dir", ".")
        self.assertEqual(env["checks"]["R0"]["note"], app["checks"]["R0"]["note"])
        self.assertEqual(env["checks"]["R0"]["status"], app["checks"]["R0"]["status"])

    def test_the_runtime_r0_entry_is_the_runner_cases_misread(self):
        """the calc base's adapter reads surefire 2's summary line, as ci-doctor-repair-java-runner's does (its replay
        test shows surefire 3's output misread there): the same entry"""
        data, entries = self.result("mech.json")
        with open(os.path.join(case_dir("ci-doctor-repair-java-runner"), "setup.sh"), encoding="utf-8") as f:
            runner = json.loads(re.search(r"<<'JSON'\n(.*?)\nJSON\n", f.read(), re.S).group(1))
        self.assertEntry(entries["R0-00e0bfc4"], next(e for e in runner["entries"] if e["id"] == "R0-00e0bfc4"))
        self.assertIn(OLD, self.git("show", f"{data['base']}:{ADAPTER}"))
        self.assertNotIn(OLD, self.git("show", f"main~1:{ADAPTER}"))

    def test_the_held_r2_entry_is_r2_at_the_calc_head(self):
        data, entries = self.result("mech.json")
        _, env = self.kit("r2", "--base", data["base"], "--head", data["head"], "--stack", "maven", "--project-dir", ".",
                          "--test-paths", "src/test/**")
        self.assertEqual([e["id"] for e in env["entries"]], ["R2-0734ae9c"])
        self.assertEntry(env["entries"][0], entries["R2-0734ae9c"])
        self.assertEqual(data["checks"]["R2"]["before"], env["checks"]["R2"])
        cause = "; ".join(entries[i]["problem"] for i in ("R0-6d261a04", "R0-00e0bfc4"))  # both halves failed
        for check in ("R1", "R2", "R4"):
            self.assertEqual(data["checks"][check]["note"], f"blocked: R0 failed ({cause})", check)


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
