"""scripts/ci-local.py (#84): what CI runs on ekit's own PRs, on this machine, as one command.

main(argv, run=...) in this process; the fake `run` stands for every command (git, the engine, uv, r3-local, the
scenario runner), so no step really runs here, except where a test hands the scenario runner a fixture repo of its own
(#115): there the real runner runs it. Each test asserts the exit code and the printed lines, as the r3-local tests do."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _kit

ci = _kit.load("ci-local")
SELF = os.path.join(_kit.ROOT, ".github", "workflows", "mech-review-self.yml")
CALLED = os.path.join(_kit.ROOT, ".github", "workflows", "mech-review.yml")
ENGINE = os.path.join(_kit.ROOT, "scripts", "mech-review.py")
R3_LOCAL = os.path.join(_kit.ROOT, "scripts", "r3-local.py")
RUNNER = os.path.join(_kit.ROOT, "scripts", "scenarios.py")
BASE, HEAD = "b" * 40, "a" * 40
SUITE = ["uv", "run", "--no-project", "--python", "3.14", "python", "-m", "unittest", "discover", "-s", "tests/py"]


def envelope(summary, checks=None, entries=()):
    checks = checks or {c: {"status": "pass", "note": "ok"} for c in ("R1", "R2", "R4")}
    checks.setdefault("R3", {"status": "skipped", "note": "not run by all"})
    return json.dumps({"ekit": "t", "base": BASE, "head": HEAD, "checks": checks, "entries": list(entries),
                       "summary": summary})


class Fake:
    """Answers each command by its kind; records (argv, cwd). Each step's answer is (rc, stdout, stderr)."""

    def __init__(self, mech=None, probe=None, suite=None, r3=None, scenarios=None, dirty="", branch="claude/x",
                 leave=()):
        self.calls = []
        self.kinds = []  # the step command each call was, in order: mech, probe, suite, r3, scenarios
        self.r0_dir = self.r0_dir_was = None  # the engine's --r0 dir, and what it was when the engine ran
        self.mech = mech or (0, envelope(f"all pass {HEAD}"), "")
        self.probe = probe or (0, "3.14\n", "")
        self.suite = suite or (0, "", "....\n----\nRan 4 tests in 0.1s\n\nOK\n")
        self.r3 = r3 or (0, f"all pass {HEAD}\nR3 pass (3/3 tested)\nmerged: not kept\n", "")
        # "real": the scenario runner really runs (on a fixture repo the test made)
        self.scenarios = scenarios or (0, "PASS a\nPASS a/b\nPASS: 2/2 scenarios\n", "")
        self.dirty, self.branch, self.leave = dirty, branch, leave

    def __call__(self, argv, cwd=None):
        self.calls.append((list(argv), cwd))
        if argv[:2] == ["git", "-C"] and argv[3] == "rev-parse":
            if "--abbrev-ref" in argv:
                return 0, self.branch + "\n", ""
            ref = argv[-1].split("^")[0]
            known = {"main": BASE, "HEAD": HEAD}
            return (0, known[ref] + "\n", "") if ref in known else (128, "", f"fatal: bad revision '{ref}'\n")
        if argv[:2] == ["git", "-C"] and argv[3] == "status":
            return 0, self.dirty, ""
        if argv[1:3] == ["-I", ENGINE]:
            self.kinds.append("mech")
            if "--r0" in argv:
                self.r0_dir = argv[argv.index("--r0") + 1]
                self.r0_dir_was = "an empty dir" if os.path.isdir(self.r0_dir) and not os.listdir(self.r0_dir) \
                    else "not an empty dir"
            return self.mech
        if argv[:5] == ["uv", "run", "--no-project", "--python", "3.14"] and "-c" in argv:
            self.kinds.append("probe")
            return self.probe
        if argv == SUITE:
            self.kinds.append("suite")
            for name in self.leave:  # what a careless uv run would leave in the repo
                p = os.path.join(cwd, name)
                os.makedirs(p) if name.endswith("venv") else open(p, "w").close()
            return self.suite
        if argv[1:3] == ["-I", R3_LOCAL]:
            self.kinds.append("r3")
            return self.r3
        if argv[1:3] == ["-I", RUNNER]:
            self.kinds.append("scenarios")
            return ci.run_cmd(argv, cwd) if self.scenarios == "real" else self.scenarios
        raise AssertionError(f"unexpected command {argv}")

    def step(self, which):
        """the calls of one step: mech (the engine), suite (uv), r3 (r3-local), scenarios (the scenario runner)"""
        test = {"mech": lambda a: a[1:3] == ["-I", ENGINE], "suite": lambda a: a[0] == "uv",
                "r3": lambda a: a[1:3] == ["-I", R3_LOCAL], "scenarios": lambda a: a[1:3] == ["-I", RUNNER]}[which]
        return [(a, cwd) for a, cwd in self.calls if test(a)]


class Tmp(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = t.name

    def main(self, fake, *extra):
        argv = ["--repo", self.tmp, "--base", "main", *extra]
        return _kit.run_cli(argv, main=lambda a: ci.main(a, run=fake))

    def verdicts(self, r):
        return [l for l in r.stdout.splitlines() if l.split(":")[0] in ("mech", "suite", "r3", "scenarios")]


class AllPass(Tmp):
    def test_four_steps_pass_in_ci_order_then_the_scenarios_and_the_command_exits_0(self):
        fake = Fake()
        r = self.main(fake)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.verdicts(r), [
            f"mech: passed: all pass {HEAD}",
            "suite: passed: Ran 4 tests in 0.1s (Python 3.14)",
            f"r3: passed: all pass {HEAD}",
            "scenarios: passed: 2/2 scenarios",
        ])
        self.assertEqual(fake.kinds, ["mech", "probe", "suite", "r3", "scenarios"])
        self.assertIn("PASS a/b\n", r.stdout)  # the runner's own lines are shown


class Inputs(Tmp):
    """The steps run what CI runs: this checkout's engine and r3-local, with ekit's caller inputs."""

    def test_the_caller_inputs_are_the_workflows(self):
        with open(SELF, encoding="utf-8") as f:
            wf = f.read()
        self.assertIn("stack: python\n", wf)
        self.assertIn("test-paths: |\n        tests/**\n        .ekit/scenarios/**\n      protected-paths", wf)
        self.assertIn("protected-paths: '.github/**'\n", wf)
        self.assertIn("mutation-budget: '20'\n", wf)

    def test_the_red_first_job_runs_r0s_runtime_half(self):
        with open(CALLED, encoding="utf-8") as f:
            wf = f.read()
        self.assertIn('args+=(--r0 "$HOME/.cache/ekit-r0")  # R0\'s runtime half, run part (#21)\n', wf)

    def test_the_mech_step_runs_the_checkouts_engine_on_the_base_and_head_commits(self):
        fake = Fake(branch="worktree-agent-1")
        self.main(fake)
        (argv, _), = fake.step("mech")
        self.assertEqual(argv, [sys.executable, "-I", ENGINE, "all", "--repo", self.tmp, "--base", BASE, "--head", HEAD,
                                "--stack", "python", "--test-paths", "tests/**", "--test-paths", ".ekit/scenarios/**",
                                "--head-branch", "worktree-agent-1", "--agent-prefix", "*",
                                "--protected-paths", ".github/**", "--r0", fake.r0_dir])

    def test_the_mech_step_proves_r0s_runtime_half_in_a_fresh_dir_as_a_ci_cache_miss_does(self):
        fake = Fake()
        self.main(fake)
        self.assertEqual(fake.r0_dir_was, "an empty dir")
        self.assertEqual(os.path.lexists(fake.r0_dir), False)  # removed after the step

    def test_a_detached_head_is_passed_as_head(self):
        fake = Fake(branch="")
        self.main(fake)
        (argv, _), = fake.step("mech")
        self.assertEqual(argv[argv.index("--head-branch") + 1], "HEAD")

    def test_a_named_head_branch_is_passed_as_is(self):
        fake = Fake()
        self.main(fake, "--head-branch", "claude/pr")
        (argv, _), = fake.step("mech")
        self.assertEqual(argv[argv.index("--head-branch") + 1], "claude/pr")
        self.assertNotIn("--abbrev-ref", [x for a, _ in fake.calls for x in a])

    def test_the_suite_runs_on_ci_python_through_uv_without_a_project_in_the_repo(self):
        fake = Fake()
        self.main(fake)
        probe, run = fake.step("suite")
        self.assertEqual(probe, (["uv", "run", "--no-project", "--python", "3.14", "python", "-I", "-c",
                                  "import sys; print('%d.%d' % sys.version_info[:2])"], self.tmp))
        self.assertEqual(run, (SUITE, self.tmp))

    def test_the_r3_step_is_r3_local_with_the_callers_inputs(self):
        fake = Fake()
        self.main(fake, "--r3-env-dir", "/x/env")
        (argv, _), = fake.step("r3")
        self.assertEqual(argv, [sys.executable, "-I", R3_LOCAL, "--repo", self.tmp, "--base", BASE, "--head", HEAD,
                                "--stack", "python", "--test-paths", "tests/**", "--test-paths", ".ekit/scenarios/**",
                                "--mutation-budget", "20", "--env-dir", "/x/env"])

    def test_without_an_env_dir_r3_local_uses_its_own_temp_dir(self):
        fake = Fake()
        self.main(fake)
        (argv, _), = fake.step("r3")
        self.assertNotIn("--env-dir", argv)

    def test_the_scenarios_step_runs_every_scenario_with_the_checkouts_runner(self):
        fake = Fake()
        self.main(fake)
        (argv, _), = fake.step("scenarios")
        self.assertEqual(argv, [sys.executable, "-I", RUNNER, "--repo", self.tmp, "run"])

    def test_the_default_repo_and_base_are_this_checkout_and_origin_main(self):
        a = ci.parse([])
        self.assertEqual((a.repo, a.base, a.head_branch, a.r3_env_dir), (_kit.ROOT, "origin/main", None, None))

    def test_help_names_the_exit_codes(self):
        r = _kit.run_cli(["--help"], main=lambda a: ci.main(a, run=Fake()))
        self.assertEqual(r.returncode, 0)
        self.assertIn("exit: 0 every step passed; 1 a step failed or could not run here;", " ".join(r.stdout.split()))


class Failed(Tmp):
    """Any step that did not pass fails the command; the others still run and report."""

    def test_mech_fail_entries_fail_the_step(self):
        entry = {"id": "R2-1", "check": "R2", "severity": "fail", "file": "tests/py/t.py", "line": 3,
                 "problem": "assert removed"}
        fake = Fake(mech=(1, envelope(f"fail {HEAD} (1 fail, 0 confirm; ran: R1 R2 R4)", entries=[entry]), ""))
        r = self.main(fake)
        self.assertEqual(r.returncode, 1)
        self.assertIn("fail R2-1 tests/py/t.py:3 assert removed\n", r.stdout)
        self.assertEqual(self.verdicts(r), [f"mech: failed: fail {HEAD} (1 fail, 0 confirm; ran: R1 R2 R4)",
                                            "suite: passed: Ran 4 tests in 0.1s (Python 3.14)",
                                            f"r3: passed: all pass {HEAD}",
                                            "scenarios: passed: 2/2 scenarios"])

    def test_confirm_entries_are_printed_and_do_not_fail_the_step(self):
        entry = {"id": "R2-2", "check": "R2", "severity": "confirm", "file": "tests/py/t.py", "line": 5,
                 "problem": "test renamed"}
        summary = f"pass {HEAD} (0 fail, 1 confirm; ran: R1 R2 R4)"
        r = self.main(Fake(mech=(0, envelope(summary, entries=[entry]), "")))
        self.assertEqual(r.returncode, 0)
        self.assertIn("confirm R2-2 tests/py/t.py:5 test renamed\n", r.stdout)
        self.assertEqual(self.verdicts(r)[0], f"mech: passed: {summary}")

    def test_a_failing_suite_fails_the_step(self):
        fake = Fake(suite=(1, "", "F...\nRan 4 tests in 0.1s\n\nFAILED (failures=1)\n"))
        r = self.main(fake)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[1], "suite: failed: Ran 4 tests in 0.1s, FAILED (failures=1) (Python 3.14)")
        self.assertIn("FAILED (failures=1)", r.stderr)

    def test_a_lock_file_or_env_dir_left_in_the_repo_fails_the_suite_step(self):
        r = self.main(Fake(leave=("uv.lock", ".venv")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[1],
                         "suite: failed: left uv.lock and .venv in the repo (want uv run --no-project)")

    def test_a_lock_file_there_before_the_run_is_not_the_runs(self):
        open(os.path.join(self.tmp, "uv.lock"), "w").close()
        r = self.main(Fake())
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_an_r3_fail_or_unconfirmed_survivor_fails_the_step_and_is_printed(self):
        out = (f"fail {HEAD} (1 fail, 1 confirm; ran: R3)\nR3 fail (3/9 tested)\n"
               "fail R3-1 scripts/x.py:4 missed `+`\nunconfirmed R3-2 scripts/x.py:9 survived `<`\nmerged: m\n")
        r = self.main(Fake(r3=(1, out, "")))
        self.assertEqual(r.returncode, 1)
        self.assertIn("unconfirmed R3-2 scripts/x.py:9 survived `<`\n", r.stdout)
        self.assertEqual(self.verdicts(r)[2],
                         f"r3: failed: fail {HEAD} (1 fail, 1 confirm; ran: R3) (2 fail or unconfirmed entries)")

    def test_one_unconfirmed_survivor_alone_fails_the_step(self):
        out = f"pass {HEAD} (0 fail, 1 confirm; ran: R3)\nunconfirmed R3-2 scripts/x.py:9 survived `<`\n"
        r = self.main(Fake(r3=(1, out, "")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[2],
                         f"r3: failed: pass {HEAD} (0 fail, 1 confirm; ran: R3) (1 fail or unconfirmed entry)")

    def test_r3_with_nothing_to_mutate_passes(self):
        r = self.main(Fake(r3=(0, "", "")))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.verdicts(r)[2], "r3: passed: no production file changed in scope")


class NotRun(Tmp):
    """A step that could not run on this machine is named with its reason, and is not a pass."""

    def test_no_uv_is_not_run_here_and_the_other_steps_still_run(self):
        r = self.main(Fake(probe=(127, "", "uv: [Errno 2] No such file or directory: 'uv'\n")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r), [
            f"mech: passed: all pass {HEAD}",
            "suite: not run here: uv not found (uv: [Errno 2] No such file or directory: 'uv'): CI's Python 3.14 "
            "comes through uv",
            f"r3: passed: all pass {HEAD}",
            "scenarios: passed: 2/2 scenarios",
        ])

    def test_no_python_314_for_uv_is_not_run_here(self):
        fake = Fake(probe=(2, "", "error: No interpreter found for Python 3.14 in managed installations\n"))
        r = self.main(fake)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[1], "suite: not run here: uv has no Python 3.14 here: error: No interpreter "
                                              "found for Python 3.14 in managed installations")
        self.assertEqual(len(fake.step("suite")), 1)  # the suite itself never ran

    def test_another_python_from_uv_is_not_run_here(self):
        r = self.main(Fake(probe=(0, "3.12\n", "")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[1], "suite: not run here: uv ran Python 3.12, not 3.14")

    def test_an_engine_error_is_not_run_here(self):
        r = self.main(Fake(mech=(2, "", "mech-review: bad revision\n")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[0],
                         "mech: not run here: mech-review.py all exit 2: mech-review: bad revision")
        self.assertIn("mech-review: bad revision\n", r.stderr)

    def test_an_engine_error_with_nothing_on_stderr_says_no_result(self):
        r = self.main(Fake(mech=(2, "", "")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[0], "mech: not run here: mech-review.py all exit 2: no result")

    def test_an_unreadable_engine_result_is_not_run_here(self):
        r = self.main(Fake(mech=(0, "{", "")))
        self.assertEqual(r.returncode, 1)
        self.assertRegex(self.verdicts(r)[0], r"^mech: not run here: mech-review.py all exit 0: no usable result "
                                              r"\(JSONDecodeError: ")

    def test_a_check_with_no_toolchain_here_is_not_a_pass(self):
        checks = {"R1": {"status": "n/a", "note": "pytest not installed (env)"},
                  "R2": {"status": "pass", "note": "ok"}, "R4": {"status": "n/a", "note": "pytest not installed (env)"}}
        r = self.main(Fake(mech=(0, envelope(f"pass {HEAD} (0 fail, 0 confirm; ran: R2; n/a: R1 R4)", checks), "")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[0], "mech: not run here: R1 n/a (pytest not installed (env)); "
                                              "R4 n/a (pytest not installed (env))")

    def test_r3_local_setup_failure_is_not_run_here(self):
        r = self.main(Fake(r3=(2, "", "r3-local: setup failed: python3 -m venv\npython3 broke\n")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[2], "r3: not run here: r3-local.py exit 2: python3 broke")

    def test_a_base_that_is_not_a_commit_runs_no_step(self):
        fake = Fake()
        r = _kit.run_cli(["--repo", self.tmp, "--base", "nope"], main=lambda a: ci.main(a, run=fake))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stderr, "ci-local: nope: not a commit (fatal: bad revision 'nope')\n")
        self.assertEqual(self.verdicts(r), [])
        self.assertEqual([s for w in ("mech", "suite", "r3", "scenarios") for s in fake.step(w)], [])


class Scenarios(Tmp):
    """The scenarios step (#115): every .ekit/scenarios scenario through the real runner, on a fixture repo of the
    test's own. A FAIL fails the step, named; a scenario this machine cannot run is `not run here`, naming it and
    what is missing; neither is a pass."""

    def setUp(self):
        super().setUp()
        # every real run keeps its evidence in a store of the test's own, outside the fixture repo: never the
        # caller's EKIT_STATE (an ekit session's live store)
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state = state.name
        patch = mock.patch.dict(os.environ, EKIT_STATE=self.state)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("EK_STATE", None)

    def scenario(self, sid, body, fields=""):
        d = os.path.join(self.tmp, ".ekit", "scenarios", sid)
        os.makedirs(d)
        with open(os.path.join(d, "SCENARIO.md"), "w") as f:
            f.write(f"# {sid}\n- story: s\n- covers: c\n- steps: x\n- expected: y\n{fields}")
        with open(os.path.join(d, "run.sh"), "w") as f:
            f.write("#!/bin/bash\n" + body + "\n")

    def commit(self):
        for argv in (["init", "-q", "-b", "main"], ["add", "-A"],
                     ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "scenarios"]):
            subprocess.run(["git", "-C", self.tmp] + argv, check=True, capture_output=True)

    def run_scenarios(self):
        self.commit()
        r = self.main(Fake(scenarios="real"))
        return r, self.verdicts(r)[3]

    def test_a_failing_scenario_fails_the_step_and_the_command_naming_it(self):
        self.scenario("good", "exit 0")
        self.scenario("bad", 'echo "ASSERT FAILED: plan lines: expected [a] got [b]" >&2; exit 1')
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 2 failed: bad (exit 1)")
        self.assertIn("FAIL bad: exit 1\n", r.stdout)

    def test_scenarios_that_mark_a_feature_pass_though_the_runner_prints_a_features_line_last(self):
        self.scenario("good", "exit 0", "- feature: plan\n")
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 of 1 features working\n", r.stdout)
        self.assertEqual(line, "scenarios: passed: 1/1 scenarios")

    def test_a_failing_scenario_that_marks_a_feature_fails_the_step(self):
        self.scenario("good", "exit 0", "- feature: plan\n")
        self.scenario("bad", "exit 1", "- feature: plan\n")
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 2 failed: bad (exit 1)")

    def test_a_real_run_keeps_its_evidence_in_the_tests_own_store_never_the_callers(self):
        # an ekit session sets EKIT_STATE: a real run there must not write into that live store
        self.scenario("good", "exit 0")
        self.run_scenarios()
        stored = [os.path.join(d, f) for d, _, fs in os.walk(self.state) for f in fs if f == "results.json"]
        self.assertEqual(len(stored), 1, stored)

    def test_a_scenario_that_says_it_cannot_run_here_is_not_run_here_naming_it_and_the_tool(self):
        # lib.sh's fail, as stack-plan/session-start uses it: `fail "unrunnable here: <what is missing>"`
        self.scenario("good", "exit 0")
        self.scenario("traced", 'echo "ASSERT FAILED: unrunnable here: strace is missing (the git-only check needs '
                                'it)" >&2; exit 1')
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: not run here: traced: strace is missing (the git-only check needs it)")

    def test_a_failure_beside_an_unrunnable_scenario_fails_the_step_and_still_names_the_unrunnable_one(self):
        self.scenario("bad", "exit 3")
        self.scenario("isolated", 'echo "ASSERT FAILED: unrunnable here: unshare -n is not permitted" >&2; exit 1')
        self.scenario("good", "exit 0")
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 3 failed: bad (exit 3); "
                               "not run here: isolated: unshare -n is not permitted")

    def test_unrunnable_only_counts_as_the_last_line_the_scenario_wrote(self):
        # the tool was there after all: what failed later is a FAIL, not a missing tool
        self.scenario("later", 'echo "unrunnable here: strace is missing" >&2; echo "ASSERT FAILED: trace: '
                               'expected [git] got [npm]" >&2; exit 1')
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 1 failed: later (exit 1)")

    def test_an_assertion_whose_captured_output_ends_in_an_unrunnable_line_is_a_failure(self):
        # lib.sh: fail "has: expected [PASS] got [$out]", $out two lines: the tail is captured text, not the message
        self.scenario("quoted", 'echo "ASSERT FAILED: has: expected [PASS] got [x" >&2; '
                                'echo "unrunnable here: strace is missing]" >&2; exit 1')
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 1 failed: quoted (exit 1)")

    def test_an_assertion_that_quotes_an_unrunnable_line_is_a_failure(self):
        self.scenario("inline", 'echo "ASSERT FAILED: has: got [unrunnable here: strace is missing]" >&2; exit 1')
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 1 failed: inline (exit 1)")

    def test_a_captured_unrunnable_assertion_after_the_scenarios_own_is_a_failure(self):
        # a scenario of the runner quotes a nested scenario's transcript in its own failure
        self.scenario("nested", 'echo "ASSERT FAILED: transcript: got [" >&2; '
                                'echo "ASSERT FAILED: unrunnable here: strace is missing" >&2; exit 1')
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 1 failed: nested (exit 1)")

    def test_an_unrunnable_line_on_stdout_is_no_fail_message(self):
        self.scenario("loud", 'echo "ASSERT FAILED: unrunnable here: strace is missing"; exit 1')
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 1 failed: loud (exit 1)")

    def test_a_timeout_is_the_runners_failure_whatever_the_scenario_said_before(self):
        os.environ["EKIT_SCENARIO_TIMEOUT"] = "1"  # setUp's patch restores it
        self.scenario("slow", 'echo "ASSERT FAILED: unrunnable here: foo" >&2; sleep 5')
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 1 failed: slow (timeout after 1s)")

    def test_a_bad_feature_line_is_the_runners_failure_whatever_the_scenario_said(self):
        self.scenario("marked", 'echo "ASSERT FAILED: unrunnable here: foo" >&2; exit 1',
                      "- feature: a\n- feature: b\n")
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: 1 of 1 failed: marked (SCENARIO.md has more than one feature line "
                               "(a, b): keep one)")

    def test_a_run_that_modified_the_repo_fails_the_step(self):
        self.scenario("writer", 'touch "$EKIT_REPO/left-behind"; exit 0')
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: failed: scenarios modified the repo: run in the temp cwd")

    def evidence(self, doc):
        """results.json where the runner keeps it: <git dir>/ekit/ (no EKIT_STATE; setUp's patch restores it)"""
        self.commit()
        os.environ.pop("EKIT_STATE", None)
        if doc is not None:
            os.makedirs(os.path.join(self.tmp, ".git", "ekit"))
            with open(os.path.join(self.tmp, ".git", "ekit", "results.json"), "w") as f:
                json.dump(doc, f)

    def test_a_scenario_whose_shell_is_not_on_this_machine_is_not_run_here(self):
        # what the runner itself reads as not run here (env): run.ps1 with no PowerShell, run.sh with no bash
        log = os.path.join(self.tmp, "win.log")
        with open(log, "w") as f:
            f.write("command: powershell run.ps1\n--- stdout ---\n\n--- stderr ---\n\n--- exit: None ---\n")
        self.evidence({"verdict": "NOT-RUN", "scenarios": [
            {"id": "good", "exit": 0}, {"id": "win", "exit": None, "transcript": log,
                                        "reason": "PowerShell is not on this machine (env)"}]})
        out = "PASS good\nNOT-RUN win: PowerShell is not on this machine (env)\nNOT-RUN: 1/2 scenarios\n"
        r = self.main(Fake(scenarios=(1, out, "")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[3], "scenarios: not run here: win: PowerShell is not on this machine (env)")

    def test_a_verdict_with_no_readable_results_is_not_run_here(self):
        self.evidence(None)
        r = self.main(Fake(scenarios=(1, "FAIL bad: exit 1\nFAIL: 0/1 scenarios\n", "")))
        self.assertEqual(r.returncode, 1)
        self.assertRegex(self.verdicts(r)[3], r"^scenarios: not run here: FAIL: 0/1 scenarios, but no readable "
                                              r"results.json \(FileNotFoundError: ")

    def fail_with(self, doc):
        self.evidence(doc)
        r = self.main(Fake(scenarios=(1, "FAIL bad: exit 1\nFAIL: 0/1 scenarios\n", "")))
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        return self.verdicts(r)[3]

    def test_a_failed_row_with_no_transcript_is_not_run_here(self):
        line = self.fail_with({"scenarios": [{"id": "bad", "exit": 1, "reason": "exit 1"}]})
        self.assertEqual(line, "scenarios: not run here: FAIL: 0/1 scenarios, but no readable results.json "
                               "(KeyError: 'transcript')")

    def test_a_transcript_that_is_gone_is_not_run_here(self):
        gone = os.path.join(self.tmp, "gone.log")
        line = self.fail_with({"scenarios": [{"id": "bad", "exit": 1, "reason": "exit 1", "transcript": gone}]})
        self.assertRegex(line, r"^scenarios: not run here: FAIL: 0/1 scenarios, but no readable results.json "
                               r"\(FileNotFoundError: ")

    def test_scenarios_that_are_not_a_list_of_rows_are_not_run_here(self):
        for doc in ({"scenarios": {"bad": {}}}, {"scenarios": ["bad"]}, ["bad"]):
            with self.subTest(doc=doc):
                self.assertRegex(self.fail_with(doc), r"^scenarios: not run here: FAIL: 0/1 scenarios, but no "
                                                      r"readable results.json \(\w+Error: ")
                os.remove(os.path.join(self.tmp, ".git", "ekit", "results.json"))
                os.rmdir(os.path.join(self.tmp, ".git", "ekit"))

    def test_a_fail_verdict_whose_results_name_no_failure_is_not_run_here(self):
        line = self.fail_with({"scenarios": []})
        self.assertEqual(line, "scenarios: not run here: FAIL: 0/1 scenarios, but results.json names no failed or "
                               "unrunnable scenario")

    def test_exit_0_with_a_fail_verdict_is_no_pass(self):
        self.evidence(None)
        r = self.main(Fake(scenarios=(0, "FAIL bad: exit 1\nFAIL: 0/1 scenarios\n", "")))
        self.assertEqual(r.returncode, 1)
        self.assertRegex(self.verdicts(r)[3], r"^scenarios: not run here: FAIL: 0/1 scenarios, but no readable ")

    def test_a_pass_verdict_short_of_every_scenario_is_no_pass(self):
        self.evidence(None)
        r = self.main(Fake(scenarios=(0, "PASS a\nPASS: 1/2 scenarios\n", "")))
        self.assertEqual(r.returncode, 1)
        self.assertRegex(self.verdicts(r)[3], r"^scenarios: not run here: PASS: 1/2 scenarios, but no readable ")

    def test_no_scenario_run_is_no_pass(self):
        r = self.main(Fake(scenarios=(0, "PASS: 0/0 scenarios\n", "")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[3], "scenarios: not run here: no scenario ran (PASS: 0/0 scenarios)")

    def test_a_repo_with_no_scenarios_is_not_run_here(self):
        os.makedirs(os.path.join(self.tmp, "src"))
        open(os.path.join(self.tmp, "src", "x.py"), "w").close()
        r, line = self.run_scenarios()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(line, "scenarios: not run here: scenarios.py run exit 2: no scenarios found. expected layout: "
                               ".ekit/scenarios/<slug>/SCENARIO.md + run.sh, run.py or run.ps1 (one of them)")

    def test_a_runner_that_ends_with_no_verdict_line_is_not_run_here(self):
        crash = (1, "PASS a\n", "Traceback (most recent call last):\nOSError: [Errno 28] No space left on device\n")
        r = self.main(Fake(scenarios=crash))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.verdicts(r)[3], "scenarios: not run here: scenarios.py run exit 1: "
                                              "OSError: [Errno 28] No space left on device")


class Dirty(Tmp):
    def test_uncommitted_changes_are_named_as_not_in_mech_and_r3(self):
        r = self.main(Fake(dirty=" M scripts/x.py\n"))
        self.assertEqual(r.returncode, 0)
        self.assertIn(f"ci-local: uncommitted changes are not in mech and r3 (they test {HEAD})\n", r.stderr)

    def test_a_clean_tree_has_no_such_line(self):
        r = self.main(Fake())
        self.assertNotIn("uncommitted", r.stderr)


if __name__ == "__main__":
    unittest.main()
