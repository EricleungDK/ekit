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
launcher = _kit.load("launcher")
WIN = os.name == "nt"
TOOL = launcher.shown(os.path.join(_kit.SCRIPTS, "task-verify.py"))


def readonly(path):
    """Make the dir `path` one this user cannot write into, as a sandbox keeps the git dir; returns the undo.
    Windows ignores a dir's mode bits: a deny entry in its ACL does the same."""
    if not WIN:
        os.chmod(path, 0o500)
        return lambda: os.chmod(path, 0o700)
    user = os.environ.get("USERNAME") or "*S-1-1-0"
    subprocess.run(["icacls", path, "/deny", f"{user}:(W,AD,WD)"], check=True, capture_output=True)
    return lambda: subprocess.run(["icacls", path, "/remove:d", user], check=True, capture_output=True)


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
        for name in ("EKIT_STATE", "EK_STATE", "CLAUDE_CODE_SESSION_ID"):
            os.environ.pop(name, None)  # records go to the repo's git dir; the session is the one a test names
        # the commands below are POSIX shell lines: they are declared in bash (Git Bash on Windows), and the
        # commands ekit prints start the Python the hook found
        os.environ.update(EKIT_SHELL="bash", EKIT_PY="python3")

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
                   f"Run `python3 {TOOL} run -- {cmd}` in the checkout that "
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
        self.assertEqual(self.call(["--repo", self.repo, "run", "--", "exit 3"]), (3, "task-verify: `exit 3` exited 3 in bash\n"))
        self.assertEqual(self.call(["--repo", self.repo, "run", "--", "true"]), (0, "task-verify: `true` exited 0 in bash\n"))

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
        self.assertEqual(self.check(), (4, "no verify command was declared for this session\n"))

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
        self.assertEqual(self.check()[0], 4)


class Declare(VerifyCase):
    """`declare -- CMD`: the way to a verify command in a session that has no task list."""

    def declare(self, *cmd, session="s1", repo=None):
        env = {} if session is None else {"CLAUDE_CODE_SESSION_ID": session}
        with mock.patch.dict(os.environ, env):
            if session is None:
                os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            return self.call(["--repo", repo or self.repo, "declare", "--", *cmd])

    def test_declared_command_is_one_the_session_must_pass(self):
        self.assertEqual(self.declare("test", "-f", "a.txt"),
                         (0, "task-verify: `test -f a.txt` is a verify command of this session\n"))
        self.assertEqual(self.check(), (1, "`test -f a.txt`: no run recorded\n"))
        self.run_cmd("test  -f a.txt")
        self.assertEqual(self.check(), (0, ""))

    def test_declaring_again_and_declaring_more_keeps_them_all(self):
        self.declare("true")
        self.declare("exit 3")
        self.declare("true")
        self.assertEqual(self.check(), (1, "`exit 3`: no run recorded\n`true`: no run recorded\n"))

    def test_declared_commands_and_task_commands_are_one_list(self):
        self.declare("true")
        self.hook("TaskCreated", "Verify: `exit 3`")
        self.hook("TaskCreated", "Verify: `true`", task="t2")
        self.assertEqual(self.check(), (1, "`exit 3`: no run recorded\n`true`: no run recorded\n"))

    def test_the_session_is_the_one_in_the_environment(self):
        self.declare("true", session="s2")
        self.assertEqual(self.check()[1], "no verify command was declared for this session\n")
        self.assertEqual(self.check("s2"), (1, "`true`: no run recorded\n"))

    def test_without_a_session_id_nothing_is_declared(self):
        self.assertEqual(self.declare("true", session=None), (
            2, "task-verify: CLAUDE_CODE_SESSION_ID is not set: run this as a Claude Code Bash command, or set it "
               "to the session id\n"))
        self.assertEqual(self.declare("true", session=""), self.declare("true", session=None))

    def test_declared_in_a_linked_worktree_counts_in_the_main_checkout(self):
        wt = os.path.join(os.path.realpath(self.tmp.name), "wt")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "unit")
        self.declare("true", repo=wt)
        self.assertEqual(self.check(), (1, "`true`: no run recorded\n"))

    def test_commands_sit_beside_the_runs(self):
        self.declare("true")
        self.assertTrue(os.path.isfile(os.path.join(self.repo, ".git", "ekit", "declared.json")))
        state = os.path.join(os.path.realpath(self.tmp.name), "st")
        os.environ["EKIT_STATE"] = state
        self.declare("true")
        key = hashlib.sha1(os.path.join(self.repo, ".git").encode()).hexdigest()
        self.assertTrue(os.path.isfile(os.path.join(state, "verify", key, "declared.json")))

    def test_file_that_is_not_a_session_map_reads_as_no_commands(self):
        path = os.path.join(self.repo, ".git", "ekit", "declared.json")
        os.makedirs(os.path.dirname(path))
        for junk in ("[1]", "not json"):
            with self.subTest(junk=junk):
                with open(path, "w") as f:
                    f.write(junk)
                self.assertEqual(self.check()[1], "no verify command was declared for this session\n")
        self.declare("true")
        self.assertEqual(self.check(), (1, "`true`: no run recorded\n"))


class ReadOnlyGitDir(VerifyCase):
    """A sandboxed Bash command cannot write the git dir: the verbs that record say so, with their own exit code."""

    def setUp(self):
        super().setUp()
        self.dir = os.path.join(self.repo, ".git", "ekit")
        os.mkdir(self.dir)
        self.undo = readonly(self.dir)
        self.addCleanup(self.unlock)

    def unlock(self):
        """the hook runs outside the sandbox"""
        if self.undo:
            self.undo()
            self.undo = None

    def refused(self, name, call):
        return 3, (f"task-verify: nothing recorded, cannot write {os.path.join(self.dir, name)}.{os.getpid()}: "
                   "Permission denied. A sandbox keeps the git dir read-only: run it outside the sandbox, as "
                   f"`{call}`.\n")

    def tool(self, verb):
        return f"python3 {TOOL} --repo {launcher.shown(self.repo)} {verb} --"

    def test_run_that_cannot_record_is_not_a_pass(self):
        self.assertEqual(self.call(["--repo", self.repo, "run", "--", "test", "-f", "a.txt"]),
                         self.refused("verify.json", f"{self.tool('run')} 'test -f a.txt'"))
        self.unlock()
        self.assertEqual(self.complete("Verify: `test -f a.txt`"), self.blocked("no run recorded", "test -f a.txt"))

    def test_declare_that_cannot_record_gives_the_call_with_the_session_id(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s1"}):
            self.assertEqual(self.call(["--repo", self.repo, "declare", "--", "true"]), self.refused(
                "declared.json", f"CLAUDE_CODE_SESSION_ID=s1 {self.tool('declare')} true"))
        self.unlock()
        self.assertEqual(self.check()[0], 4)


def powershell():
    import shutil
    return shutil.which("pwsh") or (shutil.which("powershell") if WIN else None)


class Shells(VerifyCase):
    """A verify command is re-run in the shell it was declared in, whichever shell runs `run` later."""

    def declare(self, cmd, shell):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s1", "EKIT_SHELL": shell}):
            return self.call(["--repo", self.repo, "declare", "--", cmd])

    def run_in(self, cmd, shell):
        with mock.patch.dict(os.environ, {"EKIT_SHELL": shell}):
            return self.call(["--repo", self.repo, "run", "--", cmd])

    def runs(self):
        with open(os.path.join(self.repo, ".git", "ekit", "verify.json")) as f:
            return {r["cmd"]: (r["rc"], r.get("shell")) for r in json.load(f)}

    def test_a_bash_line_with_and_and_quotes_declared_in_bash_is_run_by_bash_from_powershell(self):
        line = "test -f a.txt && grep -q 'a' a.txt"
        self.declare(line, "bash")
        self.assertEqual(self.run_in(line, "powershell"), (0, f"task-verify: `{line}` exited 0 in bash\n"))
        self.assertEqual(self.runs(), {line: (0, "bash")})
        self.assertEqual(self.check(), (0, ""))

    def test_a_powershell_line_declared_in_powershell_is_run_by_powershell_from_bash(self):
        if not powershell():
            self.skipTest("no PowerShell on this machine")
        line = "if ((Get-Content 'a.txt') -eq 'a') { exit 0 } else { exit 7 }"
        self.declare(line, "pwsh" if os.path.basename(powershell()).startswith("pwsh") else "powershell")
        rc, err = self.run_in(line, "bash")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.check(), (0, ""))

    def test_a_native_exit_code_comes_through_powershell(self):
        if not powershell():
            self.skipTest("no PowerShell on this machine")
        name = "pwsh" if os.path.basename(powershell()).startswith("pwsh") else "powershell"
        self.assertEqual(self.run_in("git -C no-such-dir status", name)[0], 128)  # git's own code, not PowerShell's 1
        self.assertEqual(self.run_in("exit 4", name)[0], 4)

    def test_a_line_with_and_and_declared_in_powershell_records_one_result(self):
        if not powershell():
            self.skipTest("no PowerShell on this machine")
        name = "pwsh" if os.path.basename(powershell()).startswith("pwsh") else "powershell"
        line = "git --version && exit 3"  # PowerShell 7 runs it; Windows PowerShell 5.1 cannot parse it
        self.declare(line, name)
        rc, _ = self.run_in(line, "bash")
        self.assertIn(rc, (1, 3))
        self.assertEqual(self.runs(), {line: (rc, name)})

    def test_an_undeclared_command_is_run_and_kept_with_the_shell_it_was_first_run_in(self):
        self.run_in("true", "bash")
        self.assertEqual(self.runs(), {"true": (0, "bash")})
        self.assertEqual(self.run_in("true", "powershell"), (0, "task-verify: `true` exited 0 in bash\n"))

    def test_a_command_whose_shell_this_machine_lacks_is_n_a_env_never_a_pass(self):
        self.declare("true", "zsh")
        with mock.patch.object(tv.shells, "find", return_value=None):
            self.assertEqual(self.run_in("true", "bash"),
                             (5, "task-verify: `true` is n/a (env): its shell zsh is not on this machine\n"))
        self.assertEqual(self.check(), (1, "`true`: n/a (env): its shell zsh is not on this machine\n"))
        self.assertEqual(self.complete("Verify: `true`")[0], 2)

    def test_a_shell_given_by_path_is_the_one_run(self):
        bash = tv.shells.find("bash")
        self.declare("echo $0 > .git/which", bash)
        self.assertEqual(self.run_in("echo $0 > .git/which", "powershell")[0], 0)
        self.assertEqual(self.runs()["echo $0 > .git/which"], (0, "bash"))


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
        usage = (2, "usage: task-verify.py [--repo DIR] declare -- CMD... | run -- CMD... | check SESSION | "
                    "task-verify.py --hook\n")
        for argv in ([], ["--repo"], ["--repo", self.repo], ["run"], ["run", "--"], ["run", "--", "", " "],
                     ["--repo", self.repo, "run", "--"], ["--repo", self.repo, "run", "true"], ["bogus", "--", "true"],
                     ["run", "true", "--"], ["--hook", "x"], ["check"],
                     ["check", "s1", "s2"], ["--repo", self.repo, "check"], ["declare"], ["declare", "--"],
                     ["declare", "true"], ["declare", "--", " "]):
            with self.subTest(argv=argv):
                self.assertEqual(self.call(argv), usage)

    def test_outside_a_repo_every_verb_is_an_error(self):
        base = os.path.realpath(self.tmp.name)
        for verb in (["declare", "--", "true"], ["check", "s1"]):
            with self.subTest(verb=verb):
                self.assertEqual(self.call(["--repo", base, *verb]), (2, f"task-verify: not a git repo: {base}\n"))
        rc, err = self.call(["--repo", base, "run", "--", "true"])
        self.assertEqual((rc, err), (2, f"task-verify: not a git repo: {os.path.realpath(self.tmp.name)}\n"))


if __name__ == "__main__":
    unittest.main()
