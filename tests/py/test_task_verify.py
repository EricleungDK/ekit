"""task-verify.py in-process: `run -- CMD` records a result for the tree, the TaskCreated/TaskCompleted hook reads it.
The repos are real: the tree hash is the scenario runner's own."""
import contextlib
import errno
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import _kit

tv = _kit.load("task-verify")
launcher = _kit.load("launcher")
TOOL = launcher.shown(os.path.join(_kit.SCRIPTS, "task-verify.py"))


def readonly(path):
    """Refuse every write into the dir `path`, as a sandbox that keeps the git dir read-only does: task-verify's own
    open() for writing there raises the OS's PermissionError (a mode change would not stop root); returns the undo."""
    real = open

    def refusing(file, mode="r", *a, **kw):
        if any(c in mode for c in "wax+") and os.path.normcase(os.path.dirname(os.path.abspath(file))) == \
                os.path.normcase(path):
            raise PermissionError(errno.EACCES, "Permission denied", file)
        return real(file, mode, *a, **kw)
    patch = mock.patch.object(tv, "open", refusing, create=True)
    patch.start()
    return patch.stop


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

    def test_the_session_may_be_given_as_an_argument_in_any_shell(self):
        """`CLAUDE_CODE_SESSION_ID=x cmd` is bash only; `--session x` reads the same in PowerShell"""
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        self.assertEqual(self.call(["--repo", self.repo, "--session", "s7", "declare", "--", "true"]),
                         (0, "task-verify: `true` is a verify command of this session\n"))
        self.assertEqual(self.check("s7"), (1, "`true`: no run recorded\n"))
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s1"}):
            self.call(["--session", "s8", "--repo", self.repo, "declare", "--", "false"])
        self.assertEqual(self.check("s8"), (1, "`false`: no run recorded\n"))

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

    def tool(self, verb, session=None):
        return f"python3 {TOOL} --repo {launcher.shown(self.repo)} {f'--session {session} ' if session else ''}{verb} --"

    def test_run_that_cannot_record_is_not_a_pass(self):
        self.assertEqual(self.call(["--repo", self.repo, "run", "--", "test", "-f", "a.txt"]),
                         self.refused("verify.json", f"{self.tool('run')} 'test -f a.txt'"))
        self.unlock()
        self.assertEqual(self.complete("Verify: `test -f a.txt`"), self.blocked("no run recorded", "test -f a.txt"))

    def test_declare_that_cannot_record_gives_the_call_with_the_session_id(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s1"}):
            self.assertEqual(self.call(["--repo", self.repo, "declare", "--", "true"]), self.refused(
                "declared.json", f"{self.tool('declare', session='s1')} true"))
        self.unlock()
        self.assertEqual(self.check()[0], 4)


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

    def faked_powershell(self, rc):
        """PowerShell as this machine would start it: its path found, the process faked (its rc); the argv kept.
        A real PowerShell runs these lines in tests/windows-smoke.py."""
        calls, real = [], subprocess.run

        def run(argv, **kw):
            if argv[0] != "/ps/pwsh":
                return real(argv, **kw)  # git, for the tree hash
            calls.append((argv, os.path.normpath(kw.get("cwd"))))  # git names the repo root C:/x on Windows
            return subprocess.CompletedProcess(argv, rc)
        return calls, mock.patch.object(tv.shells, "find", return_value="/ps/pwsh"), \
            mock.patch.object(tv.subprocess, "run", side_effect=run)

    def test_a_powershell_line_declared_in_powershell_is_run_by_powershell_from_bash(self):
        line = "if ((Get-Content 'a.txt') -eq 'a') { exit 0 } else { exit 7 }"
        self.declare(line, "powershell")
        calls, find, run = self.faked_powershell(7)
        with find, run:
            self.assertEqual(self.run_in(line, "bash"), (7, f"task-verify: `{line}` exited 7 in powershell\n"))
        self.assertEqual(calls, [(tv.shells.command("/ps/pwsh", "powershell", line), self.repo)])
        self.assertEqual(self.runs(), {line: (7, "powershell")})

    def test_a_line_with_and_and_declared_in_powershell_records_one_result_in_powershell(self):
        line = "git --version && exit 3"
        self.declare(line, "pwsh")
        calls, find, run = self.faked_powershell(3)
        with find, run:
            self.assertEqual(self.run_in(line, "bash")[0], 3)
        self.assertEqual(calls[0][0][:4], ["/ps/pwsh", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertTrue(calls[0][0][4].startswith(line + "\n"))
        self.assertEqual(self.runs(), {line: (3, "pwsh")})

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


# this Python by its name, its folder first on PATH (setUp): a plain word, which a full path quoted is not
PY = os.path.basename(sys.executable)


class MissingRunner(VerifyCase):
    """A run that fails because its runner is not installed is n/a (env) naming what to install (#117): after a
    failing exit task-verify asks whether the runner is there. A runner that is there and fails is a failed run,
    whatever it printed."""

    def setUp(self):
        super().setUp()
        os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]

    def module(self, name, body, folder=""):
        os.makedirs(os.path.join(self.repo, folder), exist_ok=True)
        with open(os.path.join(self.repo, folder, f"{name}.py"), "w") as f:
            f.write(body)

    def call(self, argv, payload=None):
        """VerifyCase.call, with what the run's own processes write to fd 1 and 2 kept in self.child_output, not
        passed on: a runner's `No module named pytest` would otherwise land in this suite's own output"""
        with tempfile.TemporaryFile() as out:
            sys.stdout.flush()
            sys.stderr.flush()
            saved = os.dup(1), os.dup(2)
            os.dup2(out.fileno(), 1)
            os.dup2(out.fileno(), 2)
            try:
                return super().call(argv, payload)
            finally:
                os.dup2(saved[0], 1)
                os.dup2(saved[1], 2)
                os.close(saved[0])
                os.close(saved[1])
                out.seek(0)
                self.child_output = out.read().decode("utf-8", "replace")

    def na(self, cmd, fix, task="t1"):
        """`cmd` reads n/a (env) with `fix`: in run (exit 5, its line last on stderr), check and the task hook"""
        rc, err = self.call(["--repo", self.repo, "run", "--", cmd])
        self.ran = self.child_output  # what the run itself wrote, before the check below replaces it
        self.assertEqual(rc, 5, err)
        self.assertTrue(err.endswith(f"task-verify: `{cmd}` is n/a (env): {fix}\n"), err)
        self.assertEqual(self.complete(f"Verify: `{cmd}`", task=task), self.blocked(f"n/a (env): {fix}", cmd))
        self.assertIn(f"`{cmd}`: n/a (env): {fix}\n", self.check()[1])

    def failed(self, cmd, rc, task="t1"):
        """`cmd` ran and failed: its exit code, never n/a"""
        self.assertEqual(self.run_cmd(cmd), rc)
        self.complete(f"Verify: `{cmd}`", task=task)
        self.assertIn(f"`{cmd}`: the run exited {rc}\n", self.check()[1])

    def script(self, folder, body, name="python3"):
        """a sh script `name` in `folder`: the run's bash starts it (Git Bash too), task-verify never does"""
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w", newline="\n") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(path, 0o755)
        return path

    def real_python(self, folder):
        """a python3 in `folder` that is this Python"""
        return self.script(folder, f'exec "{sys.executable.replace(os.sep, "/")}" "$@"\n')

    def no_module_python(self, folder):
        """a python3 in `folder` that finds no module (exit 3 for the probe) and fails every run (exit 1)"""
        return self.script(folder, 'case "$1" in -c) exit 3;; esac\nexit 1\n')

    def startup_puts_first(self, folder):
        """BASH_ENV: a file bash reads before each `-c` line, putting `folder` first on PATH, as a profile might"""
        env_file = os.path.join(os.path.realpath(self.tmp.name), "bash_env")
        with open(env_file, "w", newline="\n") as f:
            f.write(f'PATH="{folder.replace(os.sep, "/")}:$PATH"\n')
        os.environ["BASH_ENV"] = env_file

    def test_the_python_asked_is_the_one_the_runs_shell_finds_after_its_startup_file(self):
        """BASH_ENV (zsh: ~/.zshenv) can change PATH before the line runs: the probe asks that python, not the one on
        the PATH task-verify inherited"""
        self.module("ekit_runner", "import sys\nsys.exit(1)\n")
        base = os.path.realpath(self.tmp.name)
        self.real_python(os.path.join(base, "venv"))
        self.no_module_python(os.path.join(base, "sysbin"))
        os.environ["PATH"] = os.path.join(base, "sysbin") + os.pathsep + os.environ["PATH"]
        self.startup_puts_first(os.path.join(base, "venv"))
        self.failed("python3 -m ekit_runner", 1)

    def test_a_startup_file_putting_a_python_without_the_module_first_is_n_a(self):
        """the mirror: the inherited PATH's python would find the module, the one the run uses does not"""
        self.module("ekit_runner", "import sys\nsys.exit(1)\n")
        base = os.path.realpath(self.tmp.name)
        self.no_module_python(os.path.join(base, "nomod"))
        self.real_python(os.path.join(base, "venv"))
        os.environ["PATH"] = os.path.join(base, "venv") + os.pathsep + os.environ["PATH"]
        self.startup_puts_first(os.path.join(base, "nomod"))
        self.na("python3 -m ekit_runner", "install module ekit_runner for python3 (that Python finds no ekit_runner)")

    def test_a_python_its_shell_does_not_find_is_named_as_the_command_to_install(self):
        self.na("python9.99 -m pytest", "install python9.99 (bash finds no python9.99)")

    def fake_runs(self, rc, answer):
        """bash found and its process faked: the run exits `rc`; a python probe (a line that holds the find_spec
        line) gets answer(argv): an exit code, or an exception it raises; git runs for real. Returns the probes'
        (argv, cwd)."""
        real, probes = subprocess.run, []

        def run(argv, **kw):
            if argv[0] == "git":
                return real(argv, **kw)
            if tv.FINDS in (argv if isinstance(argv, str) else " ".join(argv)):
                probes.append((argv, kw.get("cwd")))
                got = answer(argv)
                if isinstance(got, BaseException):
                    raise got
                return subprocess.CompletedProcess(argv, got)
            return subprocess.CompletedProcess(argv, rc)
        patches = (mock.patch.object(tv.shells, "find", return_value="/fake/bash"),
                   mock.patch.object(tv.subprocess, "run", side_effect=run),
                   mock.patch.dict(os.environ, {"EKIT_SHELL": "bash"}))
        return probes, patches

    # the runner is not there

    def test_python_m_of_a_module_not_installed_is_n_a_env_naming_the_module_and_python(self):
        self.na(f"{PY} -m ekit_absent_runner -q",
                f"install module ekit_absent_runner for {PY} (that Python finds no ekit_absent_runner)")

    def test_pytest_missing_points_at_the_readme(self):
        self.na(f"{PY} -I -S -m pytest -q",  # -S: no site-packages, so this Python finds no pytest
                f"install module pytest for {PY} -I -S (that Python finds no pytest; ekit's README § Development "
                "names the version CI installs)")
        self.assertTrue("No module named pytest" in self.ran)  # the runner's own line is shown, not read

    def test_a_submodule_of_a_package_not_installed_names_the_package(self):
        self.na(f"{PY} -m ekit_absent_pkg.cli",
                f"install module ekit_absent_pkg for {PY} (that Python finds no ekit_absent_pkg)")

    def test_a_missing_module_is_found_whatever_else_the_interpreter_printed(self):
        self.na(f"{PY} -X importtime -m ekit_absent_runner",  # importtime prints a line per import first
                f"install module ekit_absent_runner for {PY} -X importtime (that Python finds no ekit_absent_runner)")

    def test_a_stack_folder_is_where_the_module_is_asked_for(self):
        self.module("ekit_runner", "import sys\nsys.exit(1)\n")  # in the repo root, not in sub
        os.mkdir(os.path.join(self.repo, "sub"))
        self.na(f"cd sub && {PY} -m ekit_runner",
                f"install module ekit_runner for {PY} (that Python finds no ekit_runner)", task="sub")
        self.module("ekit_other", "import sys\nsys.exit(1)\n", folder="sub")
        self.failed(f"cd sub && {PY} -m ekit_other", 1, task="other")

    def test_a_python_that_is_only_the_store_stub_is_n_a_env(self):
        """the stub prints `Python was not found` and exits 9009, which only Windows can give: faked here"""
        real = subprocess.run

        def run(argv, **kw):
            return real(argv, **kw) if argv[0] == "git" else subprocess.CompletedProcess(argv, 9009)
        with mock.patch.object(tv.subprocess, "run", side_effect=run):
            self.assertEqual(self.run_cmd("python3 -m pytest"), 5)
        self.complete("Verify: `python3 -m pytest`")
        self.assertEqual(self.check(), (1, "`python3 -m pytest`: n/a (env): install Python: python3 ran no Python "
                                           "(exit 9009, the Microsoft Store stub)\n"))

    def test_a_command_not_on_path_is_n_a_env_naming_it(self):
        self.na("ekit_absent_tool117 --version", "install ekit_absent_tool117 (bash finds no ekit_absent_tool117)")

    def test_a_line_with_a_leading_assignment_is_never_asked_about(self):
        """NAME=value changes what the run finds (PATH=.venv/bin:..., PYTHONPATH=...): no line with one is read"""
        self.failed("EKIT_X=1 ekit_absent_tool117", 127)
        for shell, rc in (("powershell", 1), ("cmd", 9009)):
            with self.subTest(shell=shell):
                find, run, env = self.faked(shell, rc)
                with find, run, env:
                    self.assertEqual(self.run_cmd(f"EKIT_X=1 ekit_absent_tool117 {shell}"), rc)

    def test_a_command_word_that_is_no_plain_name_or_path_is_never_asked_about(self):
        """`. ./x.ps1` (dot-sourcing), `..`, a word led by `-`: PowerShell's 1 and a probe that finds none would
        read `install .`"""
        for i, cmd in enumerate((". ./run-tests.ps1", ".. x", "-ekit_absent_tool117 x", "./ x")):
            with self.subTest(cmd=cmd):
                find, run, env = self.faked("pwsh", 1)
                with find, run, env:
                    self.assertEqual(self.run_cmd(cmd), 1)

    def test_a_module_name_that_is_no_dotted_name_is_never_asked_about(self):
        self.failed(f"{PY} -m ekit-absent-runner", 1)

    def test_a_cd_into_a_folder_that_is_no_plain_word_is_never_asked_about(self):
        """`cd sub$x` is `cd sub` to bash: the folder the run is in is not the word as written"""
        for d in ("sub", "sub$x"):
            os.mkdir(os.path.join(self.repo, d))
        self.failed("cd sub$x && ekit_absent_tool117", 127)

    def test_the_python_asked_is_the_one_the_run_finds_from_its_folder(self):
        """a relative path or PATH entry is the run's folder's, not task-verify's own: task-verify runs from a folder
        with no .venv, the repo's .venv python3 is this Python, and a later PATH entry's python3 finds nothing"""
        self.module("ekit_runner", "import sys\nsys.exit(1)\n")
        base = os.path.realpath(self.tmp.name)
        self.real_python(os.path.join(self.repo, ".venv", "bin"))
        self.no_module_python(os.path.join(base, "sysbin"))
        os.environ["PATH"] = os.path.join(base, "sysbin") + os.pathsep + os.environ["PATH"]
        os.mkdir(os.path.join(base, "elsewhere"))
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(os.path.join(base, "elsewhere"))
        self.failed("./.venv/bin/python3 -m ekit_runner", 1, task="path")
        os.environ["PATH"] = ".venv/bin" + os.pathsep + os.environ["PATH"]
        self.failed("python3 -m ekit_runner", 1, task="entry")
    def test_a_zero_exit_is_never_n_a(self):
        self.assertEqual(self.run_cmd(f"{PY} -m ekit_absent_runner || true"), 0)
        self.assertEqual(self.complete(f"Verify: `{PY} -m ekit_absent_runner || true`"), (0, ""))

    def test_a_zero_exit_is_never_asked_about(self):
        probes, patches = self.fake_runs(0, lambda argv: 3)  # a probe would say: no such module
        with patches[0], patches[1], patches[2]:
            self.assertEqual(self.run_cmd("python3 -m pytest"), 0)
        self.assertEqual((probes, self.complete("Verify: `python3 -m pytest`")), ([], (0, "")))

    def test_an_installed_runner_whose_test_cannot_import_is_a_failed_run(self):
        self.module("ekit_runner", "import ekit_absent_dep\n")
        self.failed(f"{PY} -m ekit_runner", 1)

    def test_an_installed_runner_whose_only_line_says_no_module_named_it_is_a_failed_run(self):
        self.module("ekit_runner", "import sys\nsys.stderr.write('ImportError while loading conftest: x.y: No module "
                                   "named ekit_runner\\n')\nsys.exit(4)\n")
        self.failed(f"{PY} -m ekit_runner", 4)

    def test_an_installed_runner_exiting_127_over_a_missing_argument_word_is_a_failed_run(self):
        self.module("ekit_runner", "import sys\nsys.stderr.write('sh: 1: ekit_absent_tool117: command not found\\n')\n"
                                   "sys.exit(127)\n")
        self.failed(f"{PY} -m ekit_runner -k ekit_absent_tool117", 127)

    def test_exit_127_from_a_builtin_is_a_failed_run(self):
        self.failed("exit 127", 127)

    def test_only_the_first_command_is_asked_about(self):
        self.failed("true && ekit_absent_tool117", 127)

    def test_a_probe_that_hangs_is_a_failed_run(self):
        probes, patches = self.fake_runs(1, lambda argv: subprocess.TimeoutExpired(argv, tv.PROBE_SECONDS))
        with patches[0], patches[1], patches[2]:
            self.failed("python3 -m pytest", 1)
        self.assertEqual(len(probes), 1)

    def test_the_default_command_with_its_runner_missing_is_n_a(self):
        probes, patches = self.fake_runs(1, lambda argv: 3)  # 3: what the probe exits for no such module
        with patches[0], patches[1], patches[2]:
            self.na("python3 -m pytest", "install module pytest for python3 (that Python finds no pytest; ekit's "
                                         "README § Development names the version CI installs)")
        self.assertTrue(probes[0][0][-1].startswith("python3 -c ") and probes[0][0][-1].endswith(" pytest"))

    def test_a_line_that_is_not_one_plain_command_is_never_asked_about(self):
        """only a plain simple command is parsed: a separator, redirect, subshell, quote or expansion anywhere in it
        (assignments included) and the run is a failed run, as it was before #117"""
        self.module("ekit_runner", "import sys\nsys.exit(1)\n")
        self.module("ekit_pkg", "import sys\nsys.exit(1)\n", folder="src")
        os.mkdir(os.path.join(self.repo, "sub"))
        for i, (cmd, rc) in enumerate((
                (f"{PY} -m ekit_runner&&echo ok", 1),
                (f"{PY} -m ekit_runner;echo $? >/dev/null; exit 1", 1),
                ("true; ekit_absent_tool117", 127),
                ("(cd sub && ekit_absent_tool117)", 127),
                ("2>/dev/null ekit_absent_tool117", 127),
                (f"PYTHONPATH=$PWD/src {PY} -m ekit_pkg", 1),
                (f'PYTHONPATH="$(pwd)/src" {PY} -m ekit_pkg', 1),
                ("ekit_absent_tool117 'a b'", 127))):
            with self.subTest(cmd=cmd):
                self.failed(cmd, rc, task=f"t{i}")

    def test_a_probe_with_an_answer_it_does_not_know_is_a_failed_run(self):
        for shell, rc, probe_rc in (("bash", 127, 2), ("powershell", 1, 7)):
            with self.subTest(shell=shell):
                find, run, env = self.faked(shell, rc, probe_rc)
                with find, run, env:
                    self.assertEqual(self.run_cmd(f"ekit_absent_tool117 {shell}"), rc)

    def test_a_probe_that_errors_is_a_failed_run(self):
        for i, answer in enumerate((lambda argv: 2, lambda argv: OSError("cannot start"))):
            probes, patches = self.fake_runs(1, answer)
            with self.subTest(i=i), patches[0], patches[1], patches[2]:
                self.failed("python3 -m pytest", 1, task=f"t{i}")

    def test_stdout_and_stderr_keep_their_order(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(_kit.SCRIPTS, "task-verify.py"), "--repo", self.repo,
                            "run", "--", "echo o1; echo e1 >&2; echo o2; echo e2 >&2"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        self.assertEqual(r.stdout.splitlines()[:4], ["o1", "e1", "o2", "e2"])

    def test_a_closed_stderr_does_not_hang_the_run(self):
        p = subprocess.Popen([sys.executable, "-I", os.path.join(_kit.SCRIPTS, "task-verify.py"), "--repo", self.repo,
                              "run", "--", "for i in $(seq 1 30000); do echo line$i >&2; done; exit 1"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        p.stderr.readline()
        p.stderr.close()
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            self.fail("the run hung once its stderr closed")

    def test_a_child_left_running_does_not_hold_the_run(self):
        start = time.monotonic()
        self.assertEqual(self.run_cmd("(sleep 6; echo late >&2) & echo bg"), 0)
        self.assertLess(time.monotonic() - start, 4)

    # PowerShell and cmd, their processes faked

    def faked(self, shell, rc, probe_rc=3):
        """`shell` found and its process faked: the run exits `rc`, a probe (Get-Command, command -v) `probe_rc`;
        git runs for real"""
        real = subprocess.run

        def run(argv, **kw):
            if argv[0] == "git":
                return real(argv, **kw)
            line = argv if isinstance(argv, str) else " ".join(argv)
            probing = "Get-Command" in line or "command -v" in line
            return subprocess.CompletedProcess(argv, probe_rc if probing else rc, "", "")
        return mock.patch.object(tv.shells, "find", return_value=f"/fake/{shell}"), \
            mock.patch.object(tv.subprocess, "run", side_effect=run), \
            mock.patch.dict(os.environ, {"EKIT_SHELL": shell})

    def test_powershell_and_cmd_not_finding_the_command_is_n_a_env(self):
        for shell, rc in (("powershell", 1), ("pwsh", 1), ("cmd", 9009)):
            with self.subTest(shell=shell):
                cmd = f"ekit_absent_tool117 -q {shell}"
                find, run, env = self.faked(shell, rc)
                with find, run, env:
                    self.assertEqual(self.run_cmd(cmd), 5)
                self.complete(f"Verify: `{cmd}`", task=shell)
                self.assertIn(f"`{cmd}`: n/a (env): install ekit_absent_tool117 ({shell} finds no "
                              "ekit_absent_tool117)\n", self.check()[1])

    def test_cmd_finds_a_command_in_the_runs_own_folder_first(self):
        """cmd.exe looks in its folder before PATH: a tool there is found, so its 9009 is its own"""
        tool = os.path.join(self.repo, "ekit_tool_here" + (".exe" if os.name == "nt" else ""))
        open(tool, "w").close()
        os.chmod(tool, 0o755)
        find, run, env = self.faked("cmd", 9009)
        with find, run, env:
            self.assertEqual(self.run_cmd("ekit_tool_here -q"), 9009)

    def test_a_tool_missing_in_a_stack_folder_is_n_a(self):
        os.mkdir(os.path.join(self.repo, "sub"))
        self.na("cd sub && ekit_absent_tool117", "install ekit_absent_tool117 (bash finds no ekit_absent_tool117)")

    def test_a_lone_cd_step_is_never_asked_about(self):
        os.mkdir(os.path.join(self.repo, "sub"))
        find, run, env = self.faked("pwsh", 1)
        with find, run, env:
            self.assertEqual(self.run_cmd("cd sub &&"), 1)

    def test_cmd_finds_a_path_from_the_runs_own_folder(self):
        """a word with a `/` is a path: cmd looks for it from its folder, not on PATH"""
        tool = os.path.join(self.repo, "bin", "ekit_tool_here" + (".exe" if os.name == "nt" else ""))
        os.mkdir(os.path.dirname(tool))
        open(tool, "w").close()
        os.chmod(tool, 0o755)
        find, run, env = self.faked("cmd", 9009)
        with find, run, env:
            self.assertEqual(self.run_cmd("bin/ekit_tool_here -q"), 9009)
            self.assertEqual(self.run_cmd("bin/ekit_absent_tool117 -q"), 5)
        self.complete("Verify: `bin/ekit_absent_tool117 -q`")
        self.assertEqual(self.check(), (1, "`bin/ekit_absent_tool117 -q`: n/a (env): install bin/ekit_absent_tool117 "
                                           "(cmd finds no bin/ekit_absent_tool117)\n"))

    def test_the_module_question_is_one_line_each_shell_runs_the_same(self):
        """`<python> [flags] -c "<find_spec>" <pkg>`, double-quoted: the find_spec line holds no `$`, backtick, `!` or
        quote, so bash, PowerShell and cmd each pass it as one word"""
        finds = ('"import importlib.util as u, sys; sys.exit(0 if u.find_spec(sys.argv[1]) else 3)"')
        for shell, rc in (("bash", 1), ("pwsh", 1), ("cmd", 1)):
            with self.subTest(shell=shell):
                probes, patches = self.fake_runs(rc, lambda argv: 3)
                with patches[0], patches[1], mock.patch.dict(os.environ, {"EKIT_SHELL": shell}):
                    self.assertEqual(self.run_cmd(f"python3 -X utf8 -m pytest.main -q {shell}"), 5)
                line = probes[0][0] if isinstance(probes[0][0], str) else probes[0][0][-1]
                self.assertIn(f"python3 -X utf8 -c {finds} pytest", line)

    def test_powershell_finding_the_command_and_cmd_with_another_exit_are_failed_runs(self):
        for shell, rc, probe in (("powershell", 1, 0), ("pwsh", 3, 3), ("cmd", 1, 3)):
            with self.subTest(shell=shell):
                find, run, env = self.faked(shell, rc, probe)
                with find, run, env:
                    self.assertEqual(self.run_cmd(f"ekit_absent_tool117 -q {shell}"), rc)


class Usage(VerifyCase):
    def test_run_without_a_command_is_a_usage_error(self):
        usage = (2, "usage: task-verify.py [--repo DIR] [--session ID] declare -- CMD... | run -- CMD... | "
                    "check SESSION | task-verify.py --hook\n")
        for argv in ([], ["--repo"], ["--repo", self.repo], ["run"], ["run", "--"], ["run", "--", "", " "],
                     ["--repo", self.repo, "run", "--"], ["--repo", self.repo, "run", "true"], ["bogus", "--", "true"],
                     ["run", "true", "--"], ["--hook", "x"], ["check"],
                     ["check", "s1", "s2"], ["--repo", self.repo, "check"], ["declare"], ["declare", "--"],
                     ["declare", "true"], ["declare", "--", " "], ["--session"], ["--session", "s1"],
                     ["--repo", self.repo, "--session"], ["--session", "", "declare", "--", "true"]):
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
