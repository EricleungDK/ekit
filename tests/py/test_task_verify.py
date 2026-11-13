"""task-verify.py in-process: `run -- CMD` records a result for the tree, the TaskCreated/TaskCompleted hook reads it.
The repos are real: the tree hash is the scenario runner's own."""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import _kit

tv = _kit.load("task-verify")


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True)


class VerifyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(base, "repo")
        os.mkdir(self.repo)
        git(self.repo, "init", "-q")
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("a\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")
        p = mock.patch.object(tv, "STATE", os.path.join(base, "state"))
        p.start()
        self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in ("EKIT_STATE", "EK_STATE"):
            os.environ.pop(name, None)  # records go to the repo's git dir, as on a user's machine

    def call(self, argv, payload=None):
        """(exit code, stderr) of one task-verify.py invocation."""
        err = io.StringIO()
        stdin = io.StringIO(json.dumps(payload) if payload is not None else "")
        with mock.patch("sys.argv", ["task-verify.py", *argv]), mock.patch("sys.stdin", stdin), \
                contextlib.redirect_stderr(err):
            try:
                rc = tv.main()
            except SystemExit as e:
                rc = e.code
        return rc or 0, err.getvalue()

    def run_cmd(self, *cmd, repo=None):
        return self.call(["--repo", repo or self.repo, "run", "--", *cmd])[0]

    def hook(self, event, desc=None, task="t1", session="s1", cwd=None, **extra):
        data = dict({"hook_event_name": event, "session_id": session, "cwd": cwd or self.repo, "task_id": task,
                     "task_subject": "Unit auth"}, **extra)
        if desc is not None:
            data["task_description"] = desc
        return self.call(["--hook"], data)

    def complete(self, desc=None, **kw):
        return self.hook("TaskCompleted", desc, **kw)

    def edit(self, text="b\n", repo=None):
        with open(os.path.join(repo or self.repo, "a.txt"), "a") as f:
            f.write(text)


class Completion(VerifyCase):
    def test_task_without_a_verify_line_completes(self):
        self.assertEqual(self.complete("Add login and signup endpoints"), (0, ""))
        self.assertEqual(self.complete(None), (0, ""))

    def test_no_recorded_run_blocks_and_names_the_command(self):
        rc, err = self.complete("Build it.\nVerify: `true`")
        self.assertEqual(rc, 2)
        self.assertIn("no run recorded", err)
        self.assertIn("run -- true", err)
        self.assertIn("task-verify.py", err)
        self.assertIn("Unit auth", err)

    def test_passing_run_lets_the_task_complete(self):
        self.assertEqual(self.run_cmd("true"), 0)
        self.assertEqual(self.complete("Verify: `true`"), (0, ""))

    def test_failing_run_blocks_with_its_exit_code(self):
        self.assertEqual(self.run_cmd("exit 3"), 3)
        rc, err = self.complete("Verify: `exit 3`")
        self.assertEqual(rc, 2)
        self.assertIn("exited 3", err)

    def test_edit_after_the_pass_blocks_until_rerun(self):
        self.run_cmd("true")
        self.edit()
        rc, err = self.complete("Verify: `true`")
        self.assertEqual(rc, 2)
        self.assertIn("changed since", err)
        self.run_cmd("true")
        self.assertEqual(self.complete("Verify: `true`")[0], 0)

    def test_commit_after_the_pass_keeps_it(self):
        self.edit()
        self.run_cmd("true")
        git(self.repo, "commit", "-q", "-am", "work")
        self.assertEqual(self.complete("Verify: `true`")[0], 0)

    def test_a_pass_of_another_command_does_not_count(self):
        self.run_cmd("true")
        self.assertEqual(self.complete("Verify: `test -f a.txt`")[0], 2)

    def test_command_given_as_words_matches_the_declared_line(self):
        self.assertEqual(self.run_cmd("test", "-f", "a.txt"), 0)
        self.assertEqual(self.complete("Verify: `test  -f a.txt`")[0], 0)

    def test_run_executes_in_the_repo_root(self):
        os.mkdir(os.path.join(self.repo, "sub"))
        self.assertEqual(self.run_cmd("test -f a.txt", repo=os.path.join(self.repo, "sub")), 0)

    def test_outside_a_git_repo_is_silent(self):
        self.assertEqual(self.complete("Verify: `true`", cwd=os.path.realpath(self.tmp.name)), (0, ""))


class DeclaredAtCreation(VerifyCase):
    def test_creation_never_blocks(self):
        self.assertEqual(self.hook("TaskCreated", "Verify: `true`"), (0, ""))
        self.assertEqual(self.hook("TaskCreated", "no line"), (0, ""))

    def test_command_from_creation_wins_over_a_later_edit(self):
        self.hook("TaskCreated", "Verify: `test -f missing.txt`")
        self.run_cmd("true")
        rc, err = self.complete("Verify: `true`")
        self.assertEqual(rc, 2)
        self.assertIn("test -f missing.txt", err)

    def test_line_added_after_creation_is_used(self):
        self.hook("TaskCreated", "no line yet")
        self.assertEqual(self.complete("Verify: `true`")[0], 2)

    def test_other_sessions_and_tasks_are_separate(self):
        self.hook("TaskCreated", "Verify: `false`")
        self.run_cmd("true")
        self.assertEqual(self.complete("Verify: `true`", task="t2")[0], 0)
        self.assertEqual(self.complete("Verify: `true`", session="s2")[0], 0)


class Worktree(VerifyCase):
    def test_pass_in_a_linked_worktree_counts_in_the_main_checkout(self):
        wt = os.path.join(os.path.realpath(self.tmp.name), "wt")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "unit")
        self.edit(repo=wt)
        self.assertEqual(self.run_cmd("true", repo=wt), 0)
        self.assertEqual(self.complete("Verify: `true`")[0], 0)
        self.edit("c\n", repo=wt)
        self.assertEqual(self.complete("Verify: `true`")[0], 2)

    def test_removed_worktree_is_no_pass(self):
        wt = os.path.join(os.path.realpath(self.tmp.name), "wt")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "unit")
        self.run_cmd("true", repo=wt)
        git(self.repo, "worktree", "remove", "--force", wt)
        self.assertEqual(self.complete("Verify: `true`")[0], 2)


class Teammate(VerifyCase):
    """A teammate's turn end fires the hook too: blocking it on every try would hold the turn open for good."""

    def test_teammate_is_blocked_once_per_tree(self):
        kw = {"teammate_name": "implementer"}
        self.assertEqual(self.complete("Verify: `true`", **kw)[0], 2)
        self.assertEqual(self.complete("Verify: `true`", **kw)[0], 0)
        self.edit()
        self.assertEqual(self.complete("Verify: `true`", **kw)[0], 2)

    def test_plain_session_is_blocked_every_time(self):
        for _ in range(3):
            self.assertEqual(self.complete("Verify: `true`")[0], 2)


class VerifyLine(unittest.TestCase):
    def test_forms(self):
        for text, want in [
            ("Verify: `pytest tests/test_a.py -q`", "pytest tests/test_a.py -q"),
            ("Build.\n- verify: `npm test -- auth`\nMore.", "npm test -- auth"),
            ("  **Verify:** `cargo test auth`", "cargo test auth"),
            ("Verify: bash tests/run.sh", "bash tests/run.sh"),
            ("Verify: `a`\nVerify: `b`", "a"),
            ("We verify: nothing here by hand, see `x`", None),
            ("Verify:", None),
            ("", None),
            (None, None),
        ]:
            with self.subTest(text=text):
                self.assertEqual(tv.declared(text), want)


class Usage(VerifyCase):
    def test_run_without_a_command_is_a_usage_error(self):
        self.assertEqual(self.call(["--repo", self.repo, "run", "--"])[0], 2)
        self.assertEqual(self.call(["bogus"])[0], 2)

    def test_run_outside_a_repo_is_a_usage_error(self):
        rc, err = self.call(["--repo", os.path.realpath(self.tmp.name), "run", "--", "true"])
        self.assertEqual(rc, 2)
        self.assertIn("not a git repo", err)


if __name__ == "__main__":
    unittest.main()
