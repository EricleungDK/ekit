"""task-verify.py in-process: `run -- CMD` records a result for the tree, the TaskCreated/TaskCompleted hook reads it.
The repos are real: the tree hash is the scenario runner's own."""
import contextlib
import hashlib
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

    def check(self, session="s1"):
        """(exit code, stdout) of `check SESSION`: what the Stop gate reads."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = self.call(["--repo", self.repo, "check", session])[0]
        return rc, out.getvalue()

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

    def blocked(self, why, cmd, subject="Unit auth"):
        """What a blocked completion sends to the agent: exit 2 and this text on stderr."""
        return 2, (f"[ekit] Task \"{subject}\" is not verified for the current files: {why}. "
                   f"Run `python3 {os.path.join(_kit.SCRIPTS, 'task-verify.py')} run -- {cmd}` in the checkout that "
                   "holds the work, fix what it shows, and mark the task completed once it exits 0. The command is "
                   "the one the task was created with: a different one is the user's call. It cannot pass here → "
                   "leave the task open and report it blocked (finish skill).\n")

    def edit(self, text="b\n", repo=None):
        with open(os.path.join(repo or self.repo, "a.txt"), "a") as f:
            f.write(text)


class Completion(VerifyCase):
    def test_task_without_a_verify_line_completes(self):
        self.assertEqual(self.complete("Add login and signup endpoints"), (0, ""))
        self.assertEqual(self.complete(None), (0, ""))

    def test_no_recorded_run_blocks_and_names_the_command(self):
        self.assertEqual(self.complete("Build it.\nVerify: `true`"), self.blocked("no run recorded", "true"))
        self.assertEqual(self.complete("Verify: `true`", task_subject="Fix div"),
                         self.blocked("no run recorded", "true", subject="Fix div"))

    def test_passing_run_lets_the_task_complete(self):
        self.assertEqual(self.run_cmd("true"), 0)
        self.assertEqual(self.complete("Verify: `true`"), (0, ""))

    def test_failing_run_blocks_with_its_exit_code(self):
        self.assertEqual(self.run_cmd("exit 3"), 3)
        self.assertEqual(self.complete("Verify: `exit 3`"), self.blocked("the run exited 3", "exit 3"))

    def test_run_reports_the_exit_code_on_stderr(self):
        self.assertEqual(self.call(["--repo", self.repo, "run", "--", "exit 3"]), (3, "task-verify: `exit 3` exited 3\n"))
        self.assertEqual(self.call(["--repo", self.repo, "run", "--", "true"]), (0, "task-verify: `true` exited 0\n"))

    def test_a_later_failing_run_replaces_the_pass(self):
        flag = os.path.join(self.repo, ".git", "flag")  # outside the tree: the files stay as they were
        self.assertEqual(self.run_cmd("test ! -f .git/flag"), 0)
        open(flag, "w").close()
        self.assertEqual(self.run_cmd("test ! -f .git/flag"), 1)
        self.assertEqual(self.complete("Verify: `test ! -f .git/flag`")[0], 2)
        os.remove(flag)
        self.assertEqual(self.run_cmd("test ! -f .git/flag"), 0)
        self.assertEqual(self.complete("Verify: `test ! -f .git/flag`")[0], 0)

    def test_each_command_keeps_its_own_result(self):
        self.run_cmd("true")
        self.run_cmd("test -f a.txt")
        self.run_cmd("false")
        self.assertEqual(self.complete("Verify: `true`", task="t1")[0], 0)
        self.assertEqual(self.complete("Verify: `test -f a.txt`", task="t2")[0], 0)
        self.assertEqual(self.complete("Verify: `false`", task="t3"), self.blocked("the run exited 1", "false"))

    def test_edit_after_the_pass_blocks_until_rerun(self):
        self.run_cmd("true")
        self.edit()
        self.assertEqual(self.complete("Verify: `true`"),
                         self.blocked("the files changed since the passing run", "true"))
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

    def test_run_without_repo_uses_the_current_directory(self):
        sub = os.path.join(self.repo, "sub")
        os.mkdir(sub)
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(sub)
        self.assertEqual(self.call(["run", "--", "test -f a.txt"])[0], 0)
        os.chdir(here)
        self.assertEqual(self.complete("Verify: `test -f a.txt`")[0], 0)

    def test_tree_that_cannot_be_hashed_is_no_pass(self):
        self.run_cmd("true")
        with mock.patch.object(tv.scenarios, "tree_hash", side_effect=SystemExit(3)):
            self.assertEqual(self.complete("Verify: `true`"),
                             self.blocked("the files changed since the passing run", "true"))
            self.assertEqual(self.run_cmd("true"), 0)  # recorded without a tree: never a pass
            self.assertEqual(self.complete("Verify: `true`")[0], 2)
        self.assertEqual(self.complete("Verify: `true`")[0], 2)

    def test_outside_a_git_repo_is_silent(self):
        self.assertEqual(self.complete("Verify: `true`", cwd=os.path.realpath(self.tmp.name)), (0, ""))


class Records(VerifyCase):
    def test_record_sits_in_the_repos_git_dir(self):
        self.run_cmd("true")
        self.assertTrue(os.path.isfile(os.path.join(self.repo, ".git", "ekit", "verify.json")))

    def test_record_sits_under_ekit_state_when_set(self):
        state = os.path.join(os.path.realpath(self.tmp.name), "st")
        os.environ["EKIT_STATE"] = state
        self.run_cmd("true")
        key = hashlib.sha1(os.path.join(self.repo, ".git").encode()).hexdigest()
        self.assertTrue(os.path.isfile(os.path.join(state, "verify", key, "verify.json")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "ekit")))
        self.assertEqual(self.complete("Verify: `true`")[0], 0)

    def test_file_that_is_not_a_record_list_reads_as_no_runs(self):
        path = os.path.join(self.repo, ".git", "ekit", "verify.json")
        os.makedirs(os.path.dirname(path))
        for junk in ('{"a": 1}', "not json", '"text"'):
            with self.subTest(junk=junk):
                with open(path, "w") as f:
                    f.write(junk)
                self.assertEqual(self.complete("Verify: `true`"), self.blocked("no run recorded", "true"))
        self.assertEqual(self.run_cmd("true"), 0)
        self.assertEqual(self.complete("Verify: `true`")[0], 0)


class DeclaredAtCreation(VerifyCase):
    def test_creation_never_blocks(self):
        self.assertEqual(self.hook("TaskCreated", "Verify: `true`"), (0, ""))
        self.assertEqual(self.hook("TaskCreated", "no line"), (0, ""))

    def test_command_from_creation_wins_over_a_later_edit(self):
        self.hook("TaskCreated", "Verify: `test -f missing.txt`")
        self.run_cmd("true")
        self.assertEqual(self.complete("Verify: `true`"),
                         self.blocked("no run recorded", "test -f missing.txt"))

    def test_line_added_after_creation_is_used(self):
        self.hook("TaskCreated", "no line yet")
        self.assertEqual(self.complete("Verify: `true`")[0], 2)

    def test_other_sessions_and_tasks_are_separate(self):
        self.hook("TaskCreated", "Verify: `false`")
        self.run_cmd("true")
        self.assertEqual(self.complete("Verify: `true`", task="t2")[0], 0)
        self.assertEqual(self.complete("Verify: `true`", session="s2")[0], 0)


class SessionCheck(VerifyCase):
    """`check SESSION`: every verify command of the session's tasks, on the files as they are now."""

    def test_session_without_a_verify_command_is_not_green(self):
        self.hook("TaskCreated", "no line")
        self.assertEqual(self.check(), (1, "no task of this session has a `Verify:` line\n"))

    def test_each_command_that_did_not_pass_is_named(self):
        self.hook("TaskCreated", "Verify: `true`", task="t1")
        self.hook("TaskCreated", "Verify: `exit 3`", task="t2")
        self.hook("TaskCreated", "Verify: `test -f a.txt`", task="t3")
        self.run_cmd("exit 3")
        self.run_cmd("test -f a.txt")
        self.assertEqual(self.check(), (1, "`exit 3`: the run exited 3\n`true`: no run recorded\n"))

    def test_all_passed_on_the_current_files_is_green(self):
        self.hook("TaskCreated", "Verify: `true`", task="t1")
        self.hook("TaskCreated", "Verify: `true`", task="t2")
        self.run_cmd("true")
        self.assertEqual(self.check(), (0, ""))
        self.edit()
        self.assertEqual(self.check(), (1, "`true`: the files changed since the passing run\n"))

    def test_only_this_sessions_commands_count(self):
        self.hook("TaskCreated", "Verify: `false`", session="s2")
        self.hook("TaskCreated", "Verify: `false`", session="s11")
        self.hook("TaskCreated", "Verify: `true`")
        self.run_cmd("true")
        self.assertEqual(self.check(), (0, ""))
        self.assertEqual(self.check("s2")[0], 1)

    def test_command_first_seen_at_completion_is_kept(self):
        self.hook("TaskCreated", "no line yet")
        self.assertEqual(self.complete("Verify: `false`")[0], 2)
        self.run_cmd("true")
        self.assertEqual(self.complete("Verify: `true`"), self.blocked("no run recorded", "false"))
        self.assertEqual(self.check(), (1, "`false`: no run recorded\n"))

    def test_before_any_task_hook_ran_there_is_no_command(self):
        self.assertEqual(self.check()[0], 1)


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

    def test_teammate_block_is_per_session_and_task(self):
        kw = {"teammate_name": "implementer"}
        self.assertEqual(self.complete("Verify: `true`", **kw)[0], 2)
        self.assertEqual(self.complete("Verify: `true`", session="s2", **kw)[0], 2)
        self.assertEqual(self.complete("Verify: `true`", task="t2", **kw)[0], 2)
        self.assertEqual(self.complete("Verify: `true`", **kw)[0], 0)

    def test_teammate_is_blocked_again_when_the_reason_changes(self):
        kw = {"teammate_name": "implementer"}
        self.assertEqual(self.complete("Verify: `false`", **kw), self.blocked("no run recorded", "false"))
        self.run_cmd("false")
        self.assertEqual(self.complete("Verify: `false`", **kw), self.blocked("the run exited 1", "false"))
        self.assertEqual(self.complete("Verify: `false`", **kw), (0, ""))

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
            ("Verify: `a` && `b`", "`a` && `b`"),
            ("Verify: ``", None),
            ("Verify: `  `", None),
            ("Verify:", None),
            ("", None),
            (None, None),
        ]:
            with self.subTest(text=text):
                self.assertEqual(tv.declared(text), want)


class Usage(VerifyCase):
    def test_run_without_a_command_is_a_usage_error(self):
        usage = (2, "usage: task-verify.py [--repo DIR] run -- CMD... | [--repo DIR] check SESSION | --hook\n")
        for argv in ([], ["--repo"], ["--repo", self.repo], ["run"], ["run", "--"], ["run", "--", "", " "],
                     ["--repo", self.repo, "run", "--"], ["--repo", self.repo, "run", "true"], ["bogus", "--", "true"],
                     ["run", "true", "--"], ["--hook", "x"], ["check"],
                     ["check", "s1", "s2"], ["--repo", self.repo, "check"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.call(argv), usage)

    def test_run_outside_a_repo_is_a_usage_error(self):
        rc, err = self.call(["--repo", os.path.realpath(self.tmp.name), "run", "--", "true"])
        self.assertEqual((rc, err), (2, f"task-verify: not a git repo: {os.path.realpath(self.tmp.name)}\n"))


if __name__ == "__main__":
    unittest.main()
