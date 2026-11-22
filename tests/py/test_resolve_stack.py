"""`stack: auto` (the reusable workflow's default): the stack and project dir found from the tracked tree, git only.

resolve.pick(paths, stack, project_dir) settles one tree; resolve.pick_pr settles a PR, base and head both; the `resolve`
subcommand reads the trees with git and prints the result the workflow's `stack` job turns into its outputs."""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest

import _kit
from scripts.mech_review import cli, doctor, resolve


class TestPick(unittest.TestCase):
    def test_an_explicit_stack_is_used_as_given_and_nothing_is_read(self):
        got = resolve.pick(["package.json"], "rust", ".")
        self.assertEqual(got, {"stack": "rust", "project_dir": ".", "error": None})

    def test_an_explicit_stack_keeps_the_callers_project_dir(self):
        self.assertEqual(resolve.pick([], "python", "pkg"), {"stack": "python", "project_dir": "pkg", "error": None})

    def test_auto_finds_the_one_project_at_the_root(self):
        got = resolve.pick(["Cargo.toml", "src/lib.rs", "tests/a.rs"], "auto", ".")
        self.assertEqual(got, {"stack": "rust", "project_dir": ".", "error": None})

    def test_auto_finds_a_project_in_a_subdir_when_project_dir_is_the_default(self):
        got = resolve.pick(["README.md", "pkg/pyproject.toml", "pkg/src/x.py"], "auto", ".")
        self.assertEqual(got, {"stack": "python", "project_dir": "pkg", "error": None})

    def test_auto_reads_doctor_candidates_so_fixture_dirs_do_not_count(self):
        got = resolve.pick(["package.json", "tests/fixtures/crate/Cargo.toml"], "auto", ".")
        self.assertEqual(got["stack"], "ts")

    def test_auto_never_guesses_between_several_projects(self):
        got = resolve.pick(["a/Cargo.toml", "b/pyproject.toml"], "auto", ".")
        self.assertIsNone(got["stack"])
        self.assertIn("several projects: python in b, rust in a", got["error"])
        self.assertIn("set the stack and project-dir inputs", got["error"])

    def test_two_stacks_in_one_dir_are_ambiguous(self):
        got = resolve.pick(["Cargo.toml", "package.json"], "auto", ".")
        self.assertIsNone(got["stack"])
        self.assertIn("rust in ., ts in .", got["error"])

    def test_no_project_names_the_manifests_looked_for(self):
        got = resolve.pick(["README.md"], "auto", ".")
        self.assertIsNone(got["stack"])
        self.assertIn("no project found", got["error"])
        self.assertIn("Cargo.toml", got["error"])
        self.assertIn("package.json", got["error"])
        self.assertIn("set the stack and project-dir inputs", got["error"])

    def test_a_set_project_dir_is_never_overridden(self):
        got = resolve.pick(["Cargo.toml", "web/package.json"], "auto", "web")
        self.assertEqual(got, {"stack": "ts", "project_dir": "web", "error": None})

    def test_a_set_project_dir_below_the_shallowest_manifest_is_still_read(self):
        got = resolve.pick(["Cargo.toml", "crates/app/Cargo.toml"], "auto", "crates/app")
        self.assertEqual(got, {"stack": "rust", "project_dir": "crates/app", "error": None})

    def test_a_set_project_dir_with_no_manifest_fails_and_names_the_projects_found(self):
        got = resolve.pick(["Cargo.toml"], "auto", "web")
        self.assertIsNone(got["stack"])
        self.assertEqual(got["project_dir"], "web")
        self.assertIn("no project found in web", got["error"])
        self.assertIn("rust in .", got["error"])

    def test_an_unknown_stack_is_an_error_not_a_guess(self):
        got = resolve.pick(["Cargo.toml"], "go", ".")
        self.assertIsNone(got["stack"])
        self.assertIn("stack go: want auto, python, rust or ts", got["error"])

    def test_a_dir_name_that_cannot_be_an_output_value_is_an_error(self):
        got = resolve.pick(["a\nb/Cargo.toml"], "auto", ".")
        self.assertIsNone(got["stack"])
        self.assertNotIn("\n", got["error"])
        self.assertIn("control character", got["error"])


class TestPickPr(unittest.TestCase):
    def test_base_and_head_agree(self):
        got = resolve.pick_pr(["Cargo.toml"], ["Cargo.toml", "src/x.rs"], "auto", ".")
        self.assertEqual(got, {"stack": "rust", "project_dir": ".", "error": None})

    def test_a_pr_that_changes_what_auto_finds_fails_instead_of_switching_the_stack(self):
        got = resolve.pick_pr(["Cargo.toml"], ["package.json"], "auto", ".")
        self.assertIsNone(got["stack"])
        self.assertIn("base finds rust in ., head finds ts in .", got["error"])
        self.assertIn("set the stack and project-dir inputs", got["error"])

    def test_an_error_at_head_is_reported(self):
        got = resolve.pick_pr(["a/Cargo.toml"], ["a/Cargo.toml", "b/package.json"], "auto", ".")
        self.assertIsNone(got["stack"])
        self.assertIn("head: several projects", got["error"])

    def test_an_explicit_stack_reads_neither_tree(self):
        got = resolve.pick_pr(["Cargo.toml"], ["package.json"], "python", ".")
        self.assertEqual(got, {"stack": "python", "project_dir": ".", "error": None})


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True)


class TestResolveCli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name
        git(self.repo, "init", "-q")
        self.write("pkg/pyproject.toml", "[project]\nname='x'\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["resolve", "--repo", self.repo, "--base", "HEAD", "--head", "HEAD", *args])
        return rc, json.loads(out.getvalue()) if out.getvalue() else None

    def test_auto_prints_the_stack_and_dir_found(self):
        rc, got = self.run_cli("--stack", "auto")
        self.assertEqual(rc, 0)
        self.assertEqual((got["stack"], got["project_dir"], got["error"]), ("python", "pkg", None))

    def test_auto_is_the_default(self):
        rc, got = self.run_cli()
        self.assertEqual((rc, got["stack"]), (0, "python"))

    def test_an_ambiguous_tree_exits_1_with_the_message(self):
        self.write("web/package.json", "{}")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "two")
        rc, got = self.run_cli("--stack", "auto")
        self.assertEqual(rc, 1)
        self.assertIsNone(got["stack"])
        self.assertIn("python in pkg, ts in web", got["error"])

    def test_untracked_files_do_not_count(self):
        self.write("web/package.json", "{}")
        rc, got = self.run_cli()
        self.assertEqual((rc, got["stack"]), (0, "python"))

    def test_an_unknown_ref_exits_2(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["resolve", "--repo", self.repo, "--base", "nosuch", "--head", "HEAD"])
        self.assertEqual(rc, 2)

    def test_a_project_dir_that_escapes_the_repo_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            cli.main(["resolve", "--repo", self.repo, "--base", "HEAD", "--head", "HEAD", "--project-dir", "../x"])
        self.assertEqual(cm.exception.code, 2)


MINI = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.toml")


class TestResolveTargetOs(unittest.TestCase):
    """#58: the stack job's output carries the OS the stack's tests run on; the workflow maps it to a fixed runner."""

    setUp, write, run_cli = TestResolveCli.setUp, TestResolveCli.write, TestResolveCli.run_cli

    def adapter(self, target_os=None):
        with open(MINI) as f:
            text = f.read()
        if target_os is not None:
            text = text.replace('name = "mini"\n', f'name = "mini"\ntarget-os = "{target_os}"\n')
        path = os.path.join(self.repo, "..", os.path.basename(self.repo) + "-mini.toml")
        with open(path, "w") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_auto_gives_linux_for_the_built_in_stack_it_finds(self):
        rc, got = self.run_cli("--stack", "auto")
        self.assertEqual((rc, got["stack"], got["target_os"]), (0, "python", "linux"))

    def test_each_built_in_stack_gives_linux(self):
        for stack in ("rust", "python", "ts"):
            with self.subTest(stack):
                rc, got = self.run_cli("--stack", stack)
                self.assertEqual((rc, got), (0, {"stack": stack, "project_dir": ".", "error": None, "target_os": "linux"}))

    def test_an_adapter_file_with_target_os_macos_gives_macos(self):
        rc, got = self.run_cli("--stack", "mini", "--adapter", self.adapter("macos"))
        self.assertEqual((rc, got), (0, {"stack": "mini", "project_dir": ".", "error": None, "target_os": "macos"}))

    def test_an_adapter_file_without_target_os_gives_linux(self):
        rc, got = self.run_cli("--stack", "mini", "--adapter", self.adapter())
        self.assertEqual((rc, got["stack"], got["target_os"]), (0, "mini", "linux"))

    def test_no_stack_gives_no_target_os(self):
        self.write("web/package.json", "{}")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "two")
        rc, got = self.run_cli()
        self.assertEqual((rc, got["stack"], got["target_os"]), (1, None, None))

    def test_a_bad_target_os_is_a_usage_error_naming_the_field(self):
        r = _kit.run_cli(["resolve", "--repo", self.repo, "--base", "HEAD", "--head", "HEAD", "--stack", "mini",
                          "--adapter", self.adapter("solaris")])
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("target-os: `solaris`: want linux, macos or windows", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_the_stack_must_be_the_adapter_files_name(self):
        r = _kit.run_cli(["resolve", "--repo", self.repo, "--base", "HEAD", "--head", "HEAD", "--stack", "ts",
                          "--adapter", self.adapter("macos")])
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("describes stack `mini`, not `ts`", r.stderr)


class TestDoctorWithAuto(unittest.TestCase):
    """Doctor asks a caller for `stack` / `project-dir` only when `stack: auto` would not find them."""

    def test_no_stack_input_is_fine_when_auto_finds_the_same(self):
        self.assertFalse(doctor._missing("stack", "python", {}, ["pyproject.toml"]))

    def test_no_stack_input_is_missing_when_auto_would_fail(self):
        self.assertTrue(doctor._missing("stack", "rust", {}, ["a/Cargo.toml", "b/package.json"]))

    def test_no_project_dir_input_is_fine_when_auto_finds_the_dir(self):
        self.assertFalse(doctor._missing("project-dir", "pkg", {}, ["pkg/pyproject.toml"]))

    def test_project_dir_is_missing_when_the_caller_pins_the_stack(self):
        self.assertTrue(doctor._missing("project-dir", "pkg", {"stack": "python"}, ["pkg/pyproject.toml"]))

    def test_rust_is_no_longer_assumed_when_auto_finds_another_stack(self):
        self.assertTrue(doctor._missing("stack", "rust", {}, ["package.json"]))


if __name__ == "__main__":
    unittest.main()
