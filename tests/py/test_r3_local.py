"""scripts/r3-local.py (#35): the workflow's R3 jobs on this machine, the tool pinned as CI pins it.

main(argv, run=...) in this process; the fake `run` stands for every command (git, venv, pip, the engine), so no tool is
installed and no test of the PR is run here. One real run is in the PR's evidence, not in the suite."""
import json
import os
import re
import shlex
import tempfile
import threading
import time
import unittest

import _kit
from scripts.mech_review import stack

r3 = _kit.load("r3-local")
WORKFLOW = os.path.join(_kit.ROOT, ".github", "workflows", "mech-review.yml")
BASE, HEAD = "b" * 40, "a" * 40


def env(note, status="fail", entries=(), **extra):
    checks = {c: {"status": "skipped", "note": "x"} for c in ("R1", "R2", "R3", "R4")}
    checks["R3"] = dict({"status": status, "note": note}, **extra)
    return {"ekit": "t", "base": BASE, "head": HEAD, "checks": checks, "entries": list(entries),
            "summary": f"{status} {HEAD} (summary)"}


def fail(file, line, problem):
    return {"id": f"R3-{line:08d}", "check": "R3", "class": "agent-fixable", "severity": "fail", "file": file,
            "line": line, "problem": problem, "hint": "h", "forbidden": "f"}


class Fake:
    """Answers each command by its kind; records (argv, env, cwd)."""

    def __init__(self, plan=True, count=2, timeout=None, shard_rc=None, merge_rc=1, base_rc=0, fails=None,
                 dirty="", merged=None, reqs=None, plan_out=None, base_out=None):
        self.calls, self.lock = [], threading.Lock()
        self.reqs = reqs or {}  # repo path -> text, at head
        self.plan_out, self.base_out = plan_out, base_out
        self.plan, self.count, self.timeout = plan, count, timeout
        self.shard_rc = shard_rc or {}
        self.merge_rc, self.base_rc, self.fails, self.dirty = merge_rc, base_rc, fails or {}, dirty
        self.merged = merged or env("shard 0/2: one; shard 1/2: two", entries=[fail("src/a.py", 3, "missed `+`")])

    def __call__(self, argv, env_=None, cwd=None):
        with self.lock:
            self.calls.append((list(argv), env_, cwd))
        if argv[:2] == ["git", "-C"] and argv[3] == "rev-parse":
            return 0, {"main": BASE, "HEAD": HEAD}.get(argv[-1].split("^")[0], "c" * 40) + "\n", ""
        if argv[:2] == ["git", "-C"] and argv[3] == "status":
            return 0, self.dirty, ""
        if argv[:2] == ["git", "-C"] and argv[3] == "ls-tree":
            tree = argv[-1]
            d = tree.split(":", 1)[1] if ":" in tree else ""
            names = [p[len(d) + 1:] if d else p for p in self.reqs if (os.path.dirname(p) == d)]
            return 0, "".join(n + "\n" for n in names + ["setup.py"]), ""
        if argv[:2] == ["git", "-C"] and argv[3] == "show":
            sha, path = argv[-1].split(":", 1)
            return (0, self.reqs[path], "") if sha == HEAD and path in self.reqs else (128, "", "fatal: no such path\n")
        if argv[0] in self.fails:
            return 1, "", f"{argv[0]} broke\n"
        if len(argv) > 3 and argv[2].endswith("mech-review.py"):
            sub = argv[3]
            if sub == "plan" and self.plan_out is not None:
                return 0, self.plan_out, ""
            if sub == "baseline" and self.base_out is not None:
                return 0, self.base_out, ""
            if sub == "plan":
                return (2, "", "mech-review: git broke\n") if self.plan is None else (0, json.dumps({"run": self.plan}), "")
            if sub == "baseline":
                b = env(f"files in {self.count} shard(s)", status="skipped")
                b.update(run=self.count > 0, count=self.count, mutants=None, timeout=self.timeout)
                return self.base_rc, json.dumps(b), "baseline log\n"
            if sub == "mutants":
                k = int(argv[argv.index("--shard") + 1].split("/")[0])
                rc = self.shard_rc.get(k, 1)
                if rc > 1:
                    return rc, "", "usage\n"
                return rc, json.dumps(env(f"note of shard {k}", timing={"wall_s": 10.0 + k})), ""
            if sub == "merge":
                return self.merge_rc, json.dumps(self.merged), ""
        return 0, "", ""

    def engine(self, sub):
        return [a for a, _, _ in self.calls if len(a) > 3 and a[2].endswith("mech-review.py") and a[3] == sub]

    def opt(self, argv, flag):
        return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


class Tmp(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = t.name
        self.envdir = os.path.join(self.tmp, "env")

    def main(self, fake, *extra, stack_name="python"):
        argv = ["--repo", self.tmp, "--base", "main", "--stack", stack_name, "--env-dir", self.envdir, *extra]
        return _kit.run_cli(argv, main=lambda a: r3.main(a, run=fake, os_name="posix"))


class Pins(unittest.TestCase):
    """The pins and settings come from the adapter; the workflow installs the same ones."""

    def setUp(self):
        with open(WORKFLOW, encoding="utf-8") as f:
            self.wf = f.read()

    def test_python_pins_are_the_workflows(self):
        t = stack.PythonAdapter.r3_tool
        self.assertEqual((t.kind, t.packages), ("venv", ("pytest==9.2.0", "mutmut==3.8.1")))
        self.assertIn("pip install --quiet " + " ".join(f'"{p}"' for p in t.packages), self.wf)

    def test_ts_pins_are_the_workflows(self):
        t = stack.TsAdapter.r3_tool
        self.assertEqual(t.kind, "npm")
        self.assertIn("--legacy-peer-deps " + " ".join(f'"{p}"' for p in t.packages), self.wf)
        self.assertIn("/stryker/" + t.mutants_cmd, self.wf)

    def test_rust_pins_and_env_are_the_workflows(self):
        t = stack.RustAdapter.r3_tool
        self.assertEqual((t.kind, t.packages), ("cargo", ("cargo-mutants@27.1.0",)))
        self.assertIn("tool: cargo-mutants@27.1.0", self.wf)
        self.assertEqual(t.env, {"CARGO_INCREMENTAL": "1", "CARGO_PROFILE_DEV_DEBUG": "0", "CARGO_PROFILE_TEST_DEBUG": "0"})
        self.assertIn("export CARGO_INCREMENTAL=1", self.wf)
        self.assertIn("export CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0", self.wf)

    def test_the_base_adapter_has_no_r3_tool(self):
        self.assertIsNone(stack.Adapter.r3_tool)


class Steps(Tmp):
    def test_python_env_is_a_venv_with_the_pins_and_the_requirements_files_at_head(self):
        open(os.path.join(self.tmp, "requirements-local.txt"), "w").close()  # in the working tree only: not read
        fake = Fake(reqs={"requirements.txt": "six\n", "requirements-dev.txt": "attrs\n", "other.txt": "x\n"})
        r = self.main(fake)
        self.assertEqual(r.returncode, 1, r.stderr)
        venv = os.path.join(self.envdir, "venv")
        py = os.path.join(venv, "bin", "python")
        req = os.path.join(self.envdir, "requirements")
        setup = [a for a, _, _ in fake.calls if a[0] in ("python3", py)][:4]
        self.assertEqual(setup, [
            ["python3", "-m", "venv", venv],
            [py, "-m", "pip", "install", "--quiet", "pytest==9.2.0", "mutmut==3.8.1"],
            [py, "-m", "pip", "install", "--quiet", "-r", os.path.join(req, "requirements-dev.txt")],
            [py, "-m", "pip", "install", "--quiet", "-r", os.path.join(req, "requirements.txt")],
        ])
        self.assertIn(["git", "-C", self.tmp, "ls-tree", "--name-only", HEAD], [a for a, _, _ in fake.calls])
        with open(os.path.join(req, "requirements-dev.txt")) as f:
            self.assertEqual(f.read(), "attrs\n")
        # the engine runs with the venv first on PATH, as CI puts it on GITHUB_PATH
        _, e, _ = [c for c in fake.calls if c[0][0] == "python3" and c[0][1] == "-I"][0]
        self.assertTrue(e["PATH"].startswith(os.path.join(venv, "bin") + os.pathsep), e["PATH"])

    def test_requirements_are_read_in_the_project_dir(self):
        fake = Fake(reqs={"app/requirements.txt": "six\n", "requirements.txt": "attrs\n"})
        self.main(fake, "--project-dir", "app")
        self.assertIn(["git", "-C", self.tmp, "ls-tree", "--name-only", f"{HEAD}:app"], [a for a, _, _ in fake.calls])
        self.assertEqual([a[-1] for a, _, _ in fake.calls if "-r" in a],
                         [os.path.join(self.envdir, "requirements", "requirements.txt")])
        with open(os.path.join(self.envdir, "requirements", "requirements.txt")) as f:
            self.assertEqual(f.read(), "six\n")

    def test_changed_requirements_set_the_env_up_again(self):
        self.main(Fake(reqs={"requirements.txt": "six\n"}))
        fake = Fake(reqs={"requirements.txt": "six==1.17.0\n"})
        self.main(fake)
        self.assertIn(["python3", "-m", "venv", os.path.join(self.envdir, "venv")], [a for a, _, _ in fake.calls])
        fake = Fake(reqs={"requirements.txt": "six==1.17.0\n"})
        self.main(fake)
        self.assertEqual([a for a, _, _ in fake.calls if "venv" in a], [])

    def test_a_relative_env_dir_is_made_absolute(self):
        fake = Fake(count=1)
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)
        _kit.run_cli(["--repo", self.tmp, "--base", "main", "--stack", "python", "--env-dir", "rel"],
                     main=lambda a: r3.main(a, run=fake, os_name="posix"))
        venv = os.path.join(os.path.realpath(self.tmp), "rel", "venv")
        self.assertIn(["python3", "-m", "venv", venv], [a for a, _, _ in fake.calls])
        _, e, _ = [c for c in fake.calls if c[0][:2] == ["python3", "-I"]][0]
        self.assertTrue(e["PATH"].startswith(os.path.join(venv, "bin") + os.pathsep), e["PATH"])

    def test_the_tools_get_no_pythonpath_or_pytest_addopts(self):
        os.environ["PYTHONPATH"], os.environ["PYTEST_ADDOPTS"] = "/x", "-k nothing"
        self.addCleanup(os.environ.pop, "PYTHONPATH")
        self.addCleanup(os.environ.pop, "PYTEST_ADDOPTS")
        fake = Fake(count=1)
        self.main(fake)
        for argv, e, _ in fake.calls:
            if argv[:2] == ["python3", "-I"]:
                self.assertNotIn("PYTHONPATH", e)
                self.assertNotIn("PYTEST_ADDOPTS", e)

    def test_native_windows_is_exit_2(self):
        fake = Fake()
        r = _kit.run_cli(["--repo", self.tmp, "--base", "main", "--stack", "python"],
                         main=lambda a: r3.main(a, run=fake, os_name="nt"))
        self.assertEqual((r.returncode, fake.calls), (2, []))
        self.assertIn("r3-local: POSIX only (on Windows run it in WSL)", r.stderr)

    def test_help_says_posix_only(self):
        r = _kit.run_cli(["--help"], main=lambda a: r3.main(a, run=Fake(), os_name="posix"))
        self.assertEqual(r.returncode, 0)
        self.assertIn("POSIX only", r.stdout)

    def test_a_ready_env_is_reused(self):
        self.main(Fake())
        fake = Fake()
        r = self.main(fake)
        self.assertEqual([a for a, _, _ in fake.calls if "venv" in a or "pip" in a], [])
        self.assertIn("r3-local: env ready in " + self.envdir, r.stdout)

    def test_an_env_for_other_pins_is_set_up_again(self):
        os.makedirs(self.envdir)
        with open(os.path.join(self.envdir, r3.MARKER), "w") as f:
            f.write('{"kind": "venv", "packages": ["mutmut==3.0.0"]}')
        fake = Fake()
        self.main(fake)
        self.assertIn(["python3", "-m", "venv", os.path.join(self.envdir, "venv")], [a for a, _, _ in fake.calls])

    def test_a_failed_setup_step_stops_with_exit_2_naming_it(self):
        fake = Fake(fails={"python3"})
        r = self.main(fake)
        self.assertEqual(r.returncode, 2)
        self.assertIn("r3-local: setup failed: python3 -m venv", r.stderr)
        self.assertIn("python3 broke", r.stderr)
        self.assertEqual(fake.engine("plan"), [])
        self.assertFalse(os.path.exists(os.path.join(self.envdir, r3.MARKER)))

    def test_ts_env_is_stryker_in_its_own_prefix_and_its_bin_is_the_mutants_cmd(self):
        fake = Fake()
        self.main(fake, stack_name="ts")
        prefix = os.path.join(self.envdir, "stryker")
        self.assertEqual([a for a, _, _ in fake.calls if a[0] == "npm"], [
            ["npm", "install", "--prefix", prefix, "--no-audit", "--no-fund", "--legacy-peer-deps",
             "@stryker-mutator/core@10.0.0", "@stryker-mutator/jest-runner@10.0.0"]])
        for argv in fake.engine("mutants"):
            self.assertEqual([shlex.split(c) for c in fake.opt(argv, "--mutants-cmd")],
                             [[os.path.join(prefix, "node_modules", ".bin", "stryker")]])
        self.assertEqual([fake.opt(a, "--mutants-cmd") for a in fake.engine("baseline")], [[]])

    def test_ts_mutants_cmd_is_quoted_for_the_engines_split(self):
        self.envdir = os.path.join(self.tmp, "my env")
        fake = Fake(count=1)
        self.main(fake, stack_name="ts")
        (argv,) = fake.engine("mutants")
        (cmd,) = fake.opt(argv, "--mutants-cmd")
        self.assertEqual(shlex.split(cmd), [os.path.join(self.envdir, "stryker", "node_modules", ".bin", "stryker")])

    def test_rust_env_installs_cargo_mutants_and_sets_the_build_env(self):
        fake = Fake()
        self.main(fake, stack_name="rust")
        root = os.path.join(self.envdir, "cargo")
        self.assertEqual([a for a, _, _ in fake.calls if a[0] == "cargo"], [
            ["cargo", "install", "--locked", "--root", root, "cargo-mutants", "--version", "27.1.0"]])
        _, e, _ = [c for c in fake.calls if c[0][:2] == ["python3", "-I"]][0]
        self.assertTrue(e["PATH"].startswith(os.path.join(root, "bin") + os.pathsep))
        self.assertEqual((e["CARGO_INCREMENTAL"], e["CARGO_PROFILE_DEV_DEBUG"], e["CARGO_PROFILE_TEST_DEBUG"]),
                         ("1", "0", "0"))
        self.assertEqual([fake.opt(a, "--mutants-cmd") for a in fake.engine("mutants")], [[], []])

    def test_a_stack_without_an_r3_tool_is_exit_2(self):
        r = _kit.run_cli(["--repo", self.tmp, "--base", "main", "--stack", "nope"], main=lambda a: r3.main(a, run=Fake(), os_name="posix"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("no R3 tool for stack nope", r.stderr)

    def test_engine_steps_take_the_ci_inputs(self):
        fake = Fake(count=3, timeout=42)
        self.main(fake, "--test-paths", "tests/**", "--test-paths", "e2e/**", "--mutation-budget", "20",
                  "--max-mutants", "7", "--project-dir", "app")
        common = ["--repo", self.tmp, "--base", BASE, "--head", HEAD, "--stack", "python"]
        tp = ["--test-paths", "tests/**", "--test-paths", "e2e/**"]
        (plan,) = fake.engine("plan")
        self.assertEqual(plan[4:], common + tp)
        (base,) = fake.engine("baseline")
        self.assertEqual(base[4:], common + ["--mutation-budget", "20", "--max-mutants", "7", "--project-dir", "app",
                                             "--shards", "4"] + tp)
        shards = sorted(fake.engine("mutants"), key=lambda a: a[a.index("--shard") + 1])
        self.assertEqual([a[4:] for a in shards], [
            common + ["--shard", f"{k}/3", "--mutation-budget", "20", "--max-mutants", "7", "--project-dir", "app",
                      "--mutant-timeout", "42"] + tp for k in range(3)])
        (merge,) = fake.engine("merge")
        out = os.path.join(self.envdir, "out")
        self.assertEqual(merge[4:], common + ["--shards", "3", "--baseline", os.path.join(out, "mech-review-baseline.json")]
                         + [x for k in range(3) for x in ("--envelope", f"{k}={os.path.join(out, f'mech-review-mutants-{k}.json')}")])
        self.assertTrue(os.path.isfile(os.path.join(out, "mech-review-mutants-2.json")))

    def test_defaults_are_the_workflows(self):
        fake = Fake(count=1)
        self.main(fake)
        (argv,) = fake.engine("mutants")
        self.assertEqual((fake.opt(argv, "--mutation-budget"), fake.opt(argv, "--max-mutants"),
                          fake.opt(argv, "--project-dir"), fake.opt(argv, "--mutant-timeout"), fake.opt(argv, "--head"),
                          fake.opt(argv, "--test-paths")),
                         (["10"], ["40"], ["."], [], [HEAD], ["tests/**"]))
        (plan,) = fake.engine("plan")
        self.assertEqual(fake.opt(plan, "--test-paths"), ["tests/**"])

    def test_a_set_mutant_timeout_wins_over_the_baselines(self):
        fake = Fake(count=1, timeout=42)
        self.main(fake, "--mutant-timeout", "7")
        (argv,) = fake.engine("mutants")
        self.assertEqual(fake.opt(argv, "--mutant-timeout"), ["7"])
        self.assertEqual(fake.opt(fake.engine("baseline")[0], "--mutant-timeout"), [])

    def test_the_engine_is_the_one_beside_this_script(self):
        fake = Fake(count=1)
        self.main(fake)
        self.assertEqual({a[2] for a in fake.engine("mutants") + fake.engine("plan")},
                         {os.path.join(_kit.SCRIPTS, "mech-review.py")})


class Shards(Tmp):
    def test_shards_run_at_the_same_time(self):
        seen, peak, lock = [0], [0], threading.Lock()
        inner = Fake(count=4)

        def run(argv, env=None, cwd=None):
            if "--shard" not in argv:
                return inner(argv, env, cwd)
            with lock:
                seen[0] += 1
                peak[0] = max(peak[0], seen[0])
            time.sleep(0.2)
            with lock:
                seen[0] -= 1
            return inner(argv, env, cwd)

        self.main(run)
        self.assertEqual(peak[0], 4)

    def test_a_shard_with_no_result_is_left_out_of_the_merge_and_named(self):
        fake = Fake(count=2, shard_rc={1: 2})
        r = self.main(fake)
        (merge,) = fake.engine("merge")
        self.assertEqual([x.split("=")[0] for x in fake.opt(merge, "--envelope")], ["0"])
        self.assertIn("shard 1/2: no result (exit 2)", r.stdout)

    def test_a_shard_that_passes_is_kept(self):
        fake = Fake(count=2, shard_rc={0: 0})
        self.main(fake)
        (merge,) = fake.engine("merge")
        self.assertEqual([x.split("=")[0] for x in fake.opt(merge, "--envelope")], ["0", "1"])


class Output(Tmp):
    def test_prints_merged_summary_r3_status_per_shard_notes_and_fails(self):
        r = self.main(Fake(count=2))
        self.assertEqual(r.returncode, 1)
        lines = r.stdout.splitlines()
        i = lines.index(f"fail {HEAD} (summary)")
        self.assertEqual(lines[i:], [
            f"fail {HEAD} (summary)",
            "R3 fail",
            "shard 0/2: note of shard 0 (wall 10.0 s)",
            "shard 1/2: note of shard 1 (wall 11.0 s)",
            "fail R3-00000003 src/a.py:3 missed `+`",
            "merged: " + os.path.join(self.envdir, "out", "mech-review-mutants-merged.json"),
        ])
        with open(os.path.join(self.envdir, "out", "mech-review-mutants-merged.json")) as f:
            self.assertEqual(json.load(f)["summary"], f"fail {HEAD} (summary)")

    def test_tested_over_total_is_shown_when_known(self):
        merged = env("n", status="partial", tested=40, total=90)
        r = self.main(Fake(count=1, merge_rc=0, merged=merged))
        self.assertEqual(r.returncode, 0)
        self.assertIn("R3 partial (40/90 tested)", r.stdout.splitlines())

    def test_unknown_total_is_a_question_mark(self):
        merged = env("n", status="partial", tested=3, total=None)
        r = self.main(Fake(count=1, merge_rc=0, merged=merged))
        self.assertIn("R3 partial (3/? tested)", r.stdout.splitlines())

    def test_a_shard_with_no_wall_time_has_no_wall_note(self):
        inner = Fake(count=1)

        def run(argv, env_=None, cwd=None):
            rc, out, err = inner(argv, env_, cwd)
            if "--shard" in argv:
                out = json.dumps(env("bare"))
            return rc, out, err

        r = self.main(run)
        self.assertIn("shard 0/1: bare", r.stdout.splitlines())

    def test_the_plan_says_no_run(self):
        fake = Fake(plan=False)
        r = self.main(fake)
        self.assertEqual(r.returncode, 0)
        self.assertIn("R3 not run: no production file changed in scope (plan)", r.stdout)
        self.assertEqual(fake.engine("baseline"), [])

    def test_a_baseline_that_does_not_run_the_shards_is_merged_alone(self):
        fake = Fake(count=0, merge_rc=0, merged=env("baseline note", status="n/a"))
        r = self.main(fake)
        self.assertEqual((r.returncode, fake.engine("mutants")), (0, []))
        (merge,) = fake.engine("merge")
        self.assertEqual((fake.opt(merge, "--shards"), fake.opt(merge, "--envelope")), (["0"], []))
        self.assertIn("R3 n/a: baseline note", r.stdout.splitlines())

    def test_a_plan_error_is_exit_2(self):
        fake = Fake(plan=None)
        r = self.main(fake)
        self.assertEqual((r.returncode, fake.engine("baseline")), (2, []))
        self.assertIn("r3-local: plan exit 2: no result\nmech-review: git broke", r.stderr)

    def test_a_baseline_usage_error_is_exit_2(self):
        fake = Fake(base_rc=2)
        r = self.main(fake)
        self.assertEqual((r.returncode, fake.engine("mutants")), (2, []))
        self.assertIn("r3-local: baseline exit 2: no result", r.stderr)
        self.assertIn("baseline log", r.stderr)

    def test_a_plan_that_is_not_json_is_exit_2(self):
        r = self.main(Fake(plan_out="Traceback ..."))
        self.assertEqual(r.returncode, 2)
        self.assertIn("r3-local: plan: no usable result (", r.stderr)

    def test_a_baseline_with_missing_keys_is_exit_2(self):
        fake = Fake(base_out=json.dumps({"run": True}))
        r = self.main(fake)
        self.assertEqual((r.returncode, fake.engine("mutants")), (2, []))
        self.assertIn("r3-local: baseline: no usable result (", r.stderr)

    def test_a_shard_that_is_not_json_is_no_result(self):
        inner = Fake(count=2)

        def run(argv, env_=None, cwd=None):
            rc, out, err = inner(argv, env_, cwd)
            return (rc, "{oops", err) if "0/2" in argv else (rc, out, err)

        r = self.main(run)
        self.assertIn("shard 0/2: no usable result", r.stdout.splitlines())
        (merge,) = inner.engine("merge")
        self.assertEqual([x.split("=")[0] for x in inner.opt(merge, "--envelope")], ["1"])

    def test_a_merge_that_is_not_json_is_exit_2(self):
        inner = Fake(count=1)

        def run(argv, env_=None, cwd=None):
            rc, out, err = inner(argv, env_, cwd)
            return (rc, "", err) if "merge" in argv else (rc, out, err)

        r = self.main(run)
        self.assertEqual(r.returncode, 2)
        self.assertIn("r3-local: merge: no usable result (", r.stderr)

    def test_without_env_dir_the_merged_json_is_said_not_kept(self):
        r = _kit.run_cli(["--repo", self.tmp, "--base", "main", "--stack", "python"],
                         main=lambda a: r3.main(a, run=Fake(count=1), os_name="posix"))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout.splitlines()[-1], "merged: not kept (temp dir removed; pass --env-dir to keep it)")

    def test_a_merge_usage_error_is_exit_2(self):
        r = self.main(Fake(merge_rc=2))
        self.assertEqual(r.returncode, 2)
        self.assertIn("r3-local: merge exit 2: no result", r.stderr)

    def test_uncommitted_changes_are_named_as_not_in_the_run(self):
        r = self.main(Fake(dirty=" M src/a.py\n"))
        self.assertIn(f"r3-local: uncommitted changes are not in the run (it tests {HEAD})", r.stderr)
        r = self.main(Fake(dirty=""))
        self.assertNotIn("uncommitted", r.stderr)

    def test_a_bad_ref_is_exit_2(self):
        def run(argv, env=None, cwd=None):
            if "rev-parse" in argv:
                return 128, "", "fatal: bad ref\n"
            return 0, "", ""

        r = self.main(run)
        self.assertEqual(r.returncode, 2)
        self.assertIn("r3-local: main: fatal: bad ref", r.stderr)

    def test_head_defaults_to_HEAD_and_takes_a_ref(self):
        fake = Fake(count=1)
        self.main(fake, "--head", "topic")
        (plan,) = fake.engine("plan")
        self.assertEqual(fake.opt(plan, "--head"), ["c" * 40])


class RealRun(unittest.TestCase):
    """The default runner: a real command, its exit code and output."""

    def test_runs_a_command(self):
        rc, out, err = r3.run_cmd(["git", "--version"])
        self.assertEqual(rc, 0)
        self.assertTrue(re.match(r"git version \d", out), out)

    def test_a_missing_executable_is_127(self):
        rc, out, err = r3.run_cmd(["ekit-no-such-tool-xyz"])
        self.assertEqual((rc, out), (127, ""))
        self.assertIn("ekit-no-such-tool-xyz", err)


if __name__ == "__main__":
    unittest.main()
