"""scripts/r3-local.py (#35): the workflow's R3 jobs on this machine, the tool pinned as CI pins it.

main(argv, run=...) in this process; the fake `run` stands for every command (git, venv, pip, the engine), so no tool is
installed and no test of the PR is run here. One real run is in the PR's evidence, not in the suite."""
import io
import json
import os
import re
import shlex
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock
import warnings

import _kit
from scripts.mech_review import stack

r3 = _kit.load("r3-local")
DEFAULT_MACHINE_LOCK = r3.MACHINE_LOCK  # read before setUpModule points it away


def setUpModule():
    """No test here takes the real machine lock: a real R3 run holds it (and runs this suite in its mutants), so a
    test that took it would wait for that run. A call without machine_lock gets this module's own temp file."""
    t = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(t.cleanup)
    r3.MACHINE_LOCK = os.path.join(t.name, "machine.lock")
    unittest.addModuleCleanup(setattr, r3, "MACHINE_LOCK", DEFAULT_MACHINE_LOCK)
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
        if argv[:2] == ["git", "-C"] and argv[3] == "archive":
            with tarfile.open(argv[argv.index("-o") + 1], "w") as tar:
                for path, text in self.reqs.items():
                    data = text.encode()
                    info = tarfile.TarInfo(path)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            return 0, "", ""
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
        self.machine = os.path.join(self.tmp, "machine.lock")  # never the real one: a run on this machine holds it

    def main(self, fake, *extra, stack_name="python"):
        argv = ["--repo", self.tmp, "--base", "main", "--stack", stack_name, "--env-dir", self.envdir, *extra]
        return _kit.run_cli(argv, main=lambda a: r3.main(a, run=fake, os_name="posix", machine_lock=self.machine))


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
        src = os.path.join(self.envdir, "head")
        setup = [(a, cwd) for a, _, cwd in fake.calls if a[0] in ("python3", py)][:4]
        self.assertEqual(setup, [
            (["python3", "-m", "venv", venv], None),
            ([py, "-m", "pip", "install", "--quiet", "pytest==9.2.0", "mutmut==3.8.1"], None),
            ([py, "-m", "pip", "install", "--quiet", "-r", "requirements-dev.txt"], src),
            ([py, "-m", "pip", "install", "--quiet", "-r", "requirements.txt"], src),
        ])
        self.assertIn(["git", "-C", self.tmp, "archive", "--format=tar", "-o", os.path.join(self.envdir, "head.tar"),
                       HEAD], [a for a, _, _ in fake.calls])
        with open(os.path.join(src, "requirements-dev.txt")) as f:
            self.assertEqual(f.read(), "attrs\n")
        # the engine runs with the venv first on PATH, as CI puts it on GITHUB_PATH
        _, e, _ = [c for c in fake.calls if c[0][0] == "python3" and c[0][1] == "-I"][0]
        self.assertTrue(e["PATH"].startswith(os.path.join(venv, "bin") + os.pathsep), e["PATH"])

    def test_requirements_are_read_in_the_project_dir(self):
        fake = Fake(reqs={"app/requirements.txt": "six\n", "requirements.txt": "attrs\n"})
        self.main(fake, "--project-dir", "app")
        self.assertEqual([(a[-1], cwd) for a, _, cwd in fake.calls if "-r" in a],
                         [("requirements.txt", os.path.join(self.envdir, "head", "app"))])

    def test_a_project_dir_with_a_trailing_slash_is_the_same_dir(self):
        fake = Fake(count=1, reqs={"app/requirements.txt": "six\n"})
        r = self.main(fake, "--project-dir", "app/")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual([cwd for a, _, cwd in fake.calls if "-r" in a], [os.path.join(self.envdir, "head", "app")])
        (argv,) = fake.engine("mutants")
        self.assertEqual(fake.opt(argv, "--project-dir"), ["app"])

    def test_relative_lines_in_requirements_resolve_in_the_head_checkout(self):
        """-c constraints.txt, -r ../x.txt and -e . are relative to the file or cwd: pip runs in the project dir."""
        fake = Fake(reqs={"app/requirements.txt": "-c constraints.txt\n-r ../base.txt\n-e .\n",
                          "app/constraints.txt": "six==1\n", "base.txt": "attrs\n", "app/setup.py": ""})
        self.main(fake, "--project-dir", "app")
        (cwd,) = [cwd for a, _, cwd in fake.calls if "-r" in a]
        for rel in ("constraints.txt", os.path.join("..", "base.txt"), "setup.py"):
            self.assertTrue(os.path.isfile(os.path.join(cwd, rel)), rel)

    def test_a_stale_checkout_is_replaced(self):
        self.main(Fake(reqs={"requirements.txt": "six\n", "old.txt": "x"}))
        self.main(Fake(reqs={"requirements.txt": "six\n"}))
        self.assertFalse(os.path.exists(os.path.join(self.envdir, "head", "old.txt")))

    def test_a_failed_archive_is_exit_2(self):
        def run(argv, env_=None, cwd=None):
            return (128, "", "fatal: bad tree\n") if "archive" in argv else Fake()(argv, env_, cwd)

        r = self.main(run)
        self.assertEqual(r.returncode, 2)
        self.assertIn("r3-local: git archive: fatal: bad tree", r.stderr)

    def archive(self, *members):
        """A run whose `git archive` writes these members: (name, text) a file, (name, None, target) a symlink, or a
        TarInfo; every other command is Fake's."""
        fake = Fake()

        def run(argv, env_=None, cwd=None):
            if "archive" not in argv:
                return fake(argv, env_, cwd)
            with tarfile.open(argv[argv.index("-o") + 1], "w") as tar:
                for m in members:
                    if isinstance(m, tarfile.TarInfo):
                        tar.addfile(m)
                        continue
                    info, data = tarfile.TarInfo(m[0]), (m[1] or "").encode()
                    if m[1] is None:
                        info.type, info.linkname = tarfile.SYMTYPE, m[2]
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            return 0, "", ""

        return fake, run

    def test_a_link_out_of_the_checkout_is_left_out_and_named_and_the_requirements_install(self):
        """CI's checkout keeps such a link and never follows it; here it is not extracted (#35)."""
        fake, run = self.archive(("link", None, "../../etc"), ("requirements.txt", "six\n"))
        r = self.main(run)
        self.assertEqual(r.returncode, 1, r.stderr)
        src = os.path.join(self.envdir, "head")
        self.assertEqual([(a[-1], cwd) for a, _, cwd in fake.calls if "-r" in a], [("requirements.txt", src)])
        self.assertFalse(os.path.lexists(os.path.join(src, "link")))
        self.assertIn("r3-local: head checkout: left out link -> ../../etc (outside the checkout)\n", r.stderr)
        self.assertNotIn("requirements.txt", r.stderr)

    def test_a_link_is_judged_from_its_own_dir(self):
        fake, run = self.archive(("base.txt", "attrs\n"), ("app/ok", None, "../base.txt"), ("app/up", None, "../../x"),
                                 ("app/requirements.txt", "six\n"))
        r = self.main(run, "--project-dir", "app")
        self.assertEqual(r.returncode, 1, r.stderr)
        app = os.path.join(self.envdir, "head", "app")
        # Windows keeps a link's target with its own separator: ..\base.txt
        self.assertEqual(os.path.normpath(os.readlink(os.path.join(app, "ok"))), os.path.normpath("../base.txt"))
        self.assertFalse(os.path.lexists(os.path.join(app, "up")))
        self.assertEqual([l for l in r.stderr.splitlines() if "left out" in l],
                         ["r3-local: head checkout: left out app/up -> ../../x (outside the checkout)"])

    def test_an_absolute_link_is_left_out_even_into_the_checkout(self):
        inside = os.path.join(os.path.realpath(self.envdir), "head", "requirements.txt")
        fake, run = self.archive(("requirements.txt", "six\n"), ("abs", None, inside))
        r = self.main(run)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertFalse(os.path.lexists(os.path.join(self.envdir, "head", "abs")))
        self.assertIn(f"left out abs -> {inside} (outside the checkout)", r.stderr)

    def test_a_member_path_out_of_the_checkout_is_left_out(self):
        fake, run = self.archive(("../up.txt", "x"), (os.path.join(self.tmp, "abs.txt"), "x"),
                                 ("requirements.txt", "six\n"))
        r = self.main(run)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.envdir, "up.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "abs.txt")))
        self.assertEqual(len([l for l in r.stderr.splitlines() if "left out" in l]), 2, r.stderr)
        self.assertEqual(len([a for a, _, _ in fake.calls if "-r" in a]), 1)

    def test_a_member_that_is_no_file_dir_or_link_is_left_out(self):
        fifo, d = tarfile.TarInfo("pipe"), tarfile.TarInfo("app")
        fifo.type, d.type, d.mode = tarfile.FIFOTYPE, tarfile.DIRTYPE, 0o755
        fake, run = self.archive(fifo, d, ("requirements.txt", "six\n"))
        r = self.main(run)
        self.assertEqual(r.returncode, 1, r.stderr)
        src = os.path.join(self.envdir, "head")
        self.assertFalse(os.path.lexists(os.path.join(src, "pipe")))
        self.assertTrue(os.path.isdir(os.path.join(src, "app")))
        self.assertEqual([l for l in r.stderr.splitlines() if "left out" in l],
                         ["r3-local: head checkout: left out pipe (not a file, dir or link)"])

    def test_a_python_without_the_data_filter_leaves_the_same_members_out(self):
        """r3-local's own seam stands for an old python; tarfile itself is never patched (3.14 reads its globals)."""
        for takes_filter in (True, False):
            with self.subTest(takes_filter=takes_filter),                     mock.patch.object(r3, "HAS_DATA_FILTER", False),                     mock.patch.object(r3, "EXTRACT_TAKES_FILTER", takes_filter and r3.EXTRACT_TAKES_FILTER):
                self.envdir = os.path.join(self.tmp, f"env-{takes_filter}")
                self.no_filter_run()

    def no_filter_run(self):
        fake, run = self.archive(("link", None, "../../etc"), ("base.txt", "attrs\n"), ("ok", None, "base.txt"),
                                 ("requirements.txt", "six\n"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)  # 3.12 and 3.13: extract() with no filter
            r = self.main(run)
        self.assertEqual(r.returncode, 1, r.stderr)
        src = os.path.join(self.envdir, "head")
        self.assertFalse(os.path.lexists(os.path.join(src, "link")))
        self.assertEqual(os.readlink(os.path.join(src, "ok")), "base.txt")
        self.assertEqual([(a[-1], cwd) for a, _, cwd in fake.calls if "-r" in a], [("requirements.txt", src)])
        self.assertIn("left out link -> ../../etc (outside the checkout)", r.stderr)

    def test_an_archive_that_is_no_tar_is_exit_2(self):
        def run(argv, env_=None, cwd=None):
            if "archive" not in argv:
                return Fake()(argv, env_, cwd)
            with open(argv[argv.index("-o") + 1], "wb") as f:
                f.write(b"not a tar " * 200)
            return 0, "", ""

        r = self.main(run)
        self.assertEqual(r.returncode, 2)
        self.assertRegex(r.stderr, r"(?s)^r3-local: head checkout: no usable archive \(ReadError: .+\)\n$")

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
                     main=lambda a: r3.main(a, run=fake, os_name="posix", machine_lock=self.machine))
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
        r = _kit.run_cli(["--repo", self.tmp, "--base", "main", "--stack", "nope"],
                         main=lambda a: r3.main(a, run=Fake(), os_name="posix", machine_lock=self.machine))
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

    def test_an_unconfirmed_survivor_is_printed_and_is_exit_1(self):
        # #79: a survivor whose whole-suite retry did not run is a missed mutant until a test kills it
        survivor = dict(fail("calc.py", 6, "R3 unconfirmed survivor calc.py:6: c = a - b -> c = a + b"),
                        severity="confirm", unconfirmed=True)
        partial = dict(fail("", 0, "R3 partial: 2/2 mutants untested: budget hit; 1 unconfirmed survivor"),
                       severity="confirm")
        merged = env("n", status="partial", tested=0, total=2, entries=[survivor, partial])
        r = self.main(Fake(count=1, merge_rc=0, merged=merged))
        self.assertEqual(r.returncode, 1, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[lines.index(f"partial {HEAD} (summary)"):], [  # the partial entry is not a survivor
            f"partial {HEAD} (summary)",
            "R3 partial (0/2 tested)",
            "shard 0/1: note of shard 0 (wall 10.0 s)",
            "unconfirmed R3-00000006 calc.py:6 R3 unconfirmed survivor calc.py:6: c = a - b -> c = a + b",
            "merged: " + os.path.join(self.envdir, "out", "mech-review-mutants-merged.json"),
        ])

    def test_a_partial_with_no_unconfirmed_survivor_is_exit_0(self):
        partial = dict(fail("", 0, "R3 partial: 1/2 mutants untested: past the cap"), severity="confirm")
        r = self.main(Fake(count=1, merge_rc=0, merged=env("n", status="partial", tested=1, total=2, entries=[partial])))
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[lines.index(f"partial {HEAD} (summary)"):], [
            f"partial {HEAD} (summary)",
            "R3 partial (1/2 tested)",
            "shard 0/1: note of shard 0 (wall 10.0 s)",
            "merged: " + os.path.join(self.envdir, "out", "mech-review-mutants-merged.json"),
        ])

    def test_help_names_the_exit_codes(self):
        r = _kit.run_cli(["--help"], main=lambda a: r3.main(a, run=Fake(), os_name="posix"))
        self.assertIn("1 a fail entry or an unconfirmed survivor", " ".join(r.stdout.split()))

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
                         main=lambda a: r3.main(a, run=Fake(count=1), os_name="posix", machine_lock=self.machine))
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


class EnvDirLock(Tmp):
    """Two runs on one --env-dir: the second refuses, so neither overwrites the other's tool or results (spec #78's
    run: two agents shared one env dir). flock, as r3-local: POSIX only."""

    def held(self, pid):
        import fcntl
        os.makedirs(self.envdir, exist_ok=True)
        f = open(os.path.join(self.envdir, r3.LOCK), "w")
        self.addCleanup(f.close)
        f.write(pid)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_an_env_dir_another_live_run_holds_is_exit_2_and_runs_nothing(self):
        self.held("4242")
        fake = Fake()
        r = self.main(fake)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stderr, f"r3-local: {self.envdir} is in use by another r3-local run (pid 4242): "
                                   "wait for it, or pass another --env-dir\n")
        self.assertEqual(fake.calls, [])

    def test_a_holder_that_wrote_no_pid_is_named_as_unknown(self):
        self.held("")
        r = self.main(Fake())
        self.assertEqual(r.stderr, f"r3-local: {self.envdir} is in use by another r3-local run (pid ?): "
                                   "wait for it, or pass another --env-dir\n")

    def test_the_run_holds_the_lock_with_its_pid_until_it_ends(self):
        import fcntl
        seen = []
        fake = Fake(count=1)

        def run(argv, env=None, cwd=None):
            if not seen:
                with open(os.path.join(self.envdir, r3.LOCK)) as f:
                    try:
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        seen.append(("free", f.read()))
                    except OSError:
                        seen.append(("held", f.read()))
            return fake(argv, env, cwd)

        self.main(run)
        self.assertEqual(seen, [("held", str(os.getpid()))])
        with open(os.path.join(self.envdir, r3.LOCK)) as f:
            self.assertIsNone(fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB))

    def test_a_lock_file_left_by_a_killed_run_does_not_stop_the_next(self):
        os.makedirs(self.envdir)
        with open(os.path.join(self.envdir, r3.LOCK), "w") as f:
            f.write("4242")
        fake = Fake(count=1)
        r = self.main(fake)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(len(fake.engine("merge")), 1)

    def test_the_next_run_replaces_a_killed_runs_pid_with_its_own(self):
        os.makedirs(self.envdir)
        with open(os.path.join(self.envdir, r3.LOCK), "w") as f:
            f.write("4242")
        seen = []
        fake = Fake(count=1)

        def run(argv, env=None, cwd=None):
            if not seen:
                with open(os.path.join(self.envdir, r3.LOCK)) as f:
                    seen.append(f.read())
            return fake(argv, env, cwd)

        self.main(run)
        self.assertEqual(seen, [str(os.getpid())])

    def test_a_second_run_after_the_first_ends_reuses_the_env(self):
        self.main(Fake())
        r = self.main(Fake())
        self.assertIn("r3-local: env ready in " + self.envdir, r.stdout)

    def test_help_names_the_env_dir_in_use_as_exit_2(self):
        r = _kit.run_cli(["--help"], main=lambda a: r3.main(a, run=Fake(), os_name="posix"))
        self.assertIn("2 setup failed, usage, the env dir in use by another run, git error", flat(r.stdout))


class MachineLock(Tmp):
    """#120: one r3-local run at a time on this machine, whatever its env dir: two at once share the CPUs and each
    shard hits its budget (one run tested 0 of 204 mutants). A second run waits for the first, naming its pid."""

    def held(self, text):
        import fcntl
        f = open(self.machine, "w")
        self.addCleanup(f.close)
        f.write(text)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f

    def test_a_second_run_waits_for_the_first_naming_its_pid_then_runs(self):
        f = self.held("4242")
        freed = threading.Event()

        def free():
            f.close()
            freed.set()

        threading.Timer(0.3, free).start()
        fake, early = Fake(count=1), []

        def run(argv, env=None, cwd=None):
            early.append(not freed.is_set())
            return fake(argv, env, cwd)

        r = self.main(run, "--wait-limit", "1")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.count("waiting for"), 1, r.stderr)  # once, not once per try
        self.assertIn("r3-local: waiting for the r3-local run of pid 4242 (one run at a time on this machine: "
                      f"{self.machine}), up to 1 min\n", r.stderr)
        self.assertNotIn(True, early)
        self.assertEqual(len(fake.engine("merge")), 1)

    def test_a_wait_past_its_limit_is_exit_3_naming_why_and_runs_nothing(self):
        self.held("4242")
        fake = Fake()
        start = time.monotonic()
        r = self.main(fake, "--wait-limit", "0.005")  # 0.3 s
        self.assertGreaterEqual(time.monotonic() - start, 0.29)
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stderr.splitlines()[-1],
                         "r3-local: waited 0.005 min for the r3-local run of pid 4242: R3 not run; run it again when "
                         "that run ends, or pass a larger --wait-limit")
        self.assertEqual(fake.calls, [])

    def test_a_lock_file_holding_no_pid_names_the_holder_as_unknown(self):
        self.held("garbage\nmore")
        r = self.main(Fake(), "--wait-limit", "0.001")
        self.assertIn("waiting for the r3-local run of pid ? (", r.stderr)
        self.assertIn("waited 0.001 min for the r3-local run of pid ?: R3 not run", r.stderr)

    def test_a_killed_first_run_frees_the_machine_for_the_waiting_one(self):
        import subprocess
        import sys
        holder = subprocess.Popen(
            [sys.executable, "-c", "import fcntl, os, sys, time\n"
             "f = open(sys.argv[1], 'w'); f.write(str(os.getpid())); f.flush()\n"
             "fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); print('held', flush=True); time.sleep(60)",
             self.machine], stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline(), "held\n")
        threading.Timer(0.3, holder.kill).start()
        fake = Fake(count=1)
        r = self.main(fake, "--wait-limit", "0.5")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(f"waiting for the r3-local run of pid {holder.pid} (", r.stderr)
        self.assertEqual(len(fake.engine("merge")), 1)

    def test_a_lock_file_left_by_a_dead_run_does_not_make_the_next_wait(self):
        with open(self.machine, "w") as f:
            f.write("4242")
        fake = Fake(count=1)
        r = self.main(fake, "--wait-limit", "0.001")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertNotIn("waiting", r.stderr)
        self.assertEqual(len(fake.engine("merge")), 1)

    def test_the_run_holds_the_machine_with_its_pid_until_it_ends(self):
        import fcntl
        seen = []
        fake = Fake(count=1)

        def run(argv, env=None, cwd=None):
            if not seen:
                with open(self.machine) as f:
                    try:
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        seen.append(("free", f.read()))
                    except OSError:
                        seen.append(("held", f.read()))
            return fake(argv, env, cwd)

        with open(self.machine, "w") as f:
            f.write("4242424242")  # a longer pid of an earlier run: replaced, not overwritten in part
        self.main(run)
        self.assertEqual(seen, [("held", str(os.getpid()))])
        with open(self.machine) as f:
            self.assertIsNone(fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB))

    def test_the_lock_file_a_run_makes_is_writable_by_every_user(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        self.main(Fake(count=1))
        self.assertEqual(os.stat(self.machine).st_mode & 0o777, 0o666)

    def test_a_lock_file_this_user_may_not_write_still_locks(self):
        """Another user's file this one may only read (the suite runs as root here, so the refusal is simulated)."""
        with open(self.machine, "w") as f:
            f.write("4242")
        real = os.open

        def refusing(path, flags, *rest):
            if path == self.machine and flags & (os.O_RDWR | os.O_WRONLY):
                raise PermissionError(13, "Permission denied", path)
            return real(path, flags, *rest)

        held = self.held_by_other_once()
        fake = Fake(count=1)
        with mock.patch.object(r3.os, "open", refusing):
            r = self.main(fake, "--wait-limit", "1")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("waiting for the r3-local run of pid 4242 (", r.stderr)
        self.assertTrue(held.is_set())
        with open(self.machine) as f:
            self.assertEqual(f.read(), "4242")

    def held_by_other_once(self):
        """The machine lock held for 0.3 s by another open file, then freed: the event is set once it is free."""
        import fcntl
        f = open(self.machine)
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        freed = threading.Event()

        def free():
            f.close()
            freed.set()

        threading.Timer(0.3, free).start()
        return freed

    def test_an_env_dir_in_use_stops_at_once_without_waiting_for_the_machine(self):
        import fcntl
        self.held("4242")
        os.makedirs(self.envdir)
        g = open(os.path.join(self.envdir, r3.LOCK), "w")
        self.addCleanup(g.close)
        g.write("77")
        g.flush()
        fcntl.flock(g, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = self.main(Fake(), "--wait-limit", "1")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stderr, f"r3-local: {self.envdir} is in use by another r3-local run (pid 77): "
                                   "wait for it, or pass another --env-dir\n")

    def test_the_machine_lock_is_one_path_for_every_user_not_under_tmpdir(self):
        self.assertEqual(DEFAULT_MACHINE_LOCK, "/tmp/ekit-r3-local.lock")

    def test_a_run_given_no_lock_path_takes_the_modules_one(self):
        path = os.path.join(self.tmp, "module.lock")
        with mock.patch.object(r3, "MACHINE_LOCK", path):
            r = _kit.run_cli(["--repo", self.tmp, "--base", "main", "--stack", "python", "--env-dir", self.envdir],
                             main=lambda a: r3.main(a, run=Fake(count=1), os_name="posix"))
        self.assertEqual(r.returncode, 1, r.stderr)
        with open(path) as f:
            self.assertEqual(f.read(), str(os.getpid()))

    def test_no_test_here_reaches_the_real_machine_lock(self):
        self.assertNotEqual(r3.MACHINE_LOCK, DEFAULT_MACHINE_LOCK)
        self.assertTrue(r3.MACHINE_LOCK.startswith(tempfile.gettempdir()), r3.MACHINE_LOCK)

    def test_a_wait_limit_that_is_no_number_of_minutes_is_a_usage_error(self):
        for bad in ("nan", "inf", "-1", "x"):
            with self.subTest(bad=bad):
                fake = Fake()
                r = self.main(fake, "--wait-limit", bad)
                self.assertEqual((r.returncode, fake.calls), (2, []))
                self.assertIn("--wait-limit: want minutes, a number 0 or more", r.stderr)

    def test_help_names_the_wait_limit_and_its_exit_code(self):
        r = _kit.run_cli(["--help"], main=lambda a: r3.main(a, run=Fake(), os_name="posix"))
        t = flat(r.stdout)
        self.assertIn("minutes to wait for another run on this machine (default 90)", t)
        self.assertIn("3 waited past --wait-limit for another run on this machine (R3 not run)", t)


def flat(text):
    return re.sub(r"\s+", " ", text)


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
