"""scripts/shells.py: the shell a command was given in, where a shell is, how a line is run with it, and stopping a
process tree. The boundaries are faked (the process table, the files on disk, which): the logic runs on every OS.
Real PowerShell and Git Bash runs are in tests/windows-smoke.py."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts import shells

WIN = os.name == "nt"


class Current(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("EKIT_SHELL", None)

    def test_ekit_shell_names_the_shell(self):
        os.environ["EKIT_SHELL"] = "pwsh"
        self.assertEqual(shells.current(), {"name": "pwsh", "exe": None})

    def test_ekit_shell_may_be_the_shells_path(self):
        path = os.path.join(tempfile.gettempdir(), "zsh.exe" if WIN else "zsh")
        os.environ["EKIT_SHELL"] = path
        self.assertEqual(shells.current(), {"name": "zsh", "exe": path})

    def test_the_nearest_shell_among_the_ancestors_is_the_one(self):
        with mock.patch.object(shells, "ancestors", return_value=[("python", None), ("make", None),
                                                                     ("zsh", "/bin/zsh"), ("bash", "/bin/bash")]):
            self.assertEqual(shells.current(), {"name": "zsh", "exe": "/bin/zsh"})

    def test_with_no_shell_among_the_ancestors_the_environment_decides(self):
        with mock.patch.object(shells, "ancestors", return_value=[("node", None)]):
            with mock.patch.object(shells, "WIN", True):
                os.environ["MSYSTEM"] = "MINGW64"
                self.assertEqual(shells.current()["name"], "bash")
                del os.environ["MSYSTEM"]
                self.assertEqual(shells.current()["name"], "powershell")
            with mock.patch.object(shells, "WIN", False):
                os.environ["SHELL"] = "/bin/zsh"
                self.assertEqual(shells.current()["name"], "zsh")
                os.environ["SHELL"] = "/usr/bin/fish"
                self.assertEqual(shells.current()["name"], "sh")
                del os.environ["SHELL"]
                self.assertEqual(shells.current()["name"], "sh")

    def test_cmd_between_python_and_a_shell_further_up_is_not_the_shell(self):
        """a .bat or .cmd shim (pyenv-win, npm scripts) starts Python through cmd.exe: the shell the command was
        given in is the one above it"""
        for chain, want in (([("cmd", None), ("bash", "/g/bash.exe"), ("claude", None)], "bash"),
                            ([("cmd", None), ("powershell", "/w/powershell.exe"), ("cmd", None), ("claude", None)],
                             "powershell"),
                            ([("python", None), ("cmd", "/w/cmd.exe"), ("explorer", None)], "cmd")):
            with self.subTest(chain=chain):
                with mock.patch.object(shells, "ancestors", return_value=chain):
                    self.assertEqual(shells.current()["name"], want)

    def test_ancestors_starts_at_the_parent(self):
        names = [n for n, _ in shells.ancestors()]
        self.assertTrue(names, "no ancestor found")
        self.assertNotIn(None, names)


class Chain(unittest.TestCase):
    """The walk up a process table ({pid: (parent pid, exe name)}), nearest first."""

    def test_the_names_of_the_parents_nearest_first_without_exe(self):
        table = {10: (9, "python.exe"), 9: (8, "cmd.exe"), 8: (7, "PowerShell.EXE"), 7: (1, "claude.exe")}
        self.assertEqual([n for n, _ in shells.chain(table, 10)], ["cmd", "powershell", "claude"])
        self.assertEqual([pid for _, pid in shells.chain(table, 10)], [9, 8, 7])

    def test_a_parent_gone_ends_the_walk_and_a_loop_ends_too(self):
        self.assertEqual(shells.chain({10: (99, "python.exe")}, 10), [])
        self.assertEqual([n for n, _ in shells.chain({10: (9, "python.exe"), 9: (10, "bash.exe")}, 10)], ["bash"])
        self.assertEqual(shells.chain({}, 10), [])

    def test_at_most_twelve_steps(self):
        table = {i: (i + 1, f"p{i}.exe") for i in range(100)}
        self.assertEqual(len(shells.chain(table, 0)), 12)


class Find(unittest.TestCase):
    def test_a_recorded_path_that_exists_is_used(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        self.addCleanup(os.remove, path)
        self.assertEqual(shells.find({"name": "bash", "exe": path}), path)

    def test_a_name_that_is_not_a_shell_is_none(self):
        self.assertIsNone(shells.find("python"))
        self.assertIsNone(shells.find({"name": "nosuchshell", "exe": "/no/such/nosuchshell"}))

    def test_a_shell_not_installed_is_none(self):
        with mock.patch.object(shells.shutil, "which", return_value=None), mock.patch.object(shells, "WIN", False):
            self.assertIsNone(shells.find("zsh"))

    def test_git_bash_path_from_claude_code_wins(self):
        with tempfile.NamedTemporaryFile(suffix="bash.exe", delete=False) as f:
            path = f.name
        self.addCleanup(os.remove, path)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_GIT_BASH_PATH": path}):
            self.assertEqual(shells.git_bash(), path)

    def test_git_bash_is_picked_over_wsls_launcher_and_missing_files(self):
        files = {"C:\\Windows\\System32\\bash.exe", "C:\\Git\\usr\\bin\\bash.exe", "C:\\Git\\bin\\bash.exe"}

        def pick(candidates):
            return shells.pick_bash(candidates, isfile=files.__contains__)
        self.assertEqual(pick([None, "C:\\Windows\\System32\\bash.exe", "C:\\nope\\bash.exe",
                               "C:\\Git\\usr\\bin\\bash.exe"]), "C:\\Git\\usr\\bin\\bash.exe")
        self.assertIsNone(pick(["C:\\Windows\\System32\\bash.exe", None]))

    def test_the_bash_beside_git_is_the_shell_not_its_launcher(self):
        """Git\\bin\\bash.exe starts Git\\usr\\bin\\bash.exe: the shell itself comes first, so a job or a timeout
        holds the real process"""
        g = os.path.realpath(os.path.join(tempfile.gettempdir(), "G"))
        git = os.path.join(g, "cmd", "git.exe")
        got = shells.bash_candidates({"CLAUDE_CODE_GIT_BASH_PATH": "X"}, lambda n: {"bash": "B", "git": git}.get(n))
        self.assertEqual(got[:2], ["X", "B"])
        self.assertEqual(got[2:4], [os.path.join(g, "usr", "bin", "bash.exe"), os.path.join(g, "bin", "bash.exe")])
        self.assertEqual(shells.bash_candidates({}, lambda n: None), [None, None])

    def test_wsls_launcher_is_not_git_bash(self):
        self.assertFalse(shells._not_wsl("C:\\Windows\\System32\\bash.exe"))
        self.assertFalse(shells._not_wsl("C:\\Users\\a\\AppData\\Local\\Microsoft\\WindowsApps\\bash.exe"))
        self.assertTrue(shells._not_wsl("C:\\Program Files\\Git\\usr\\bin\\bash.exe"))
        self.assertFalse(shells._not_wsl(None))


class Command(unittest.TestCase):
    def test_each_kind_of_shell_gets_its_own_argv(self):
        self.assertEqual(shells.command("/bin/zsh", "zsh", "a && b"), ["/bin/zsh", "-c", "a && b"])
        self.assertEqual(shells.command("pwsh", "pwsh", "exit 3"),
                         ["pwsh", "-NoProfile", "-NonInteractive", "-Command", "exit 3" + shells.PS_EXIT])
        self.assertEqual(shells.command("C:\\cmd.exe", "cmd", "echo a"), '"C:\\cmd.exe" /d /s /c "echo a"')

class Env(unittest.TestCase):
    def test_on_windows_its_dirs_go_first_elsewhere_nothing_changes(self):
        with mock.patch.object(shells, "WIN", True):
            env = shells.env_for(os.path.join("G", "usr", "bin", "bash.exe"), "bash", {"PATH": "P"})
            self.assertEqual(env["PATH"].split(os.pathsep),
                             [os.path.join("G", "usr", "bin"), os.path.join("G", "mingw64", "bin"), "P"])
            self.assertEqual(shells.env_for("pwsh.exe", "pwsh", {"PATH": "P"}), {"PATH": "P"})
        with mock.patch.object(shells, "WIN", False):
            self.assertEqual(shells.env_for("/bin/bash", "bash", {"PATH": "P"}), {"PATH": "P"})


class KillTree(unittest.TestCase):
    def test_a_child_and_its_childs_child_both_stop(self):
        mark = os.path.join(tempfile.mkdtemp(), "late")
        self.addCleanup(shutil.rmtree, os.path.dirname(mark), True)
        grandchild = f"import time; time.sleep(3); open({mark!r}, 'w').close()"
        child = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {grandchild!r}]); time.sleep(60)"
        p = shells.spawn([sys.executable, "-c", child], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(1)
        shells.kill_tree(p)
        t0 = time.time()
        p.communicate(timeout=30)
        self.assertLess(time.time() - t0, 10)
        time.sleep(4)
        self.assertFalse(os.path.exists(mark))

    def test_a_spawned_process_runs_gives_its_output_and_is_let_go_of(self):
        """started suspended on Windows, joined to its job, resumed: it runs as any child does"""
        p = shells.spawn([sys.executable, "-c", "print('out')"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(timeout=60)
        self.assertEqual((p.returncode, out.strip(), err), (0, b"out", b""))
        shells.finish(p)
        shells.finish(p)  # twice: nothing left to let go of

    def test_a_process_already_gone_is_no_error(self):
        p = shells.spawn([sys.executable, "-c", "pass"])
        p.wait()
        shells.kill_tree(p)
        shells.kill_tree(p)


if __name__ == "__main__":
    unittest.main()
