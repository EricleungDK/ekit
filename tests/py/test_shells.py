"""scripts/shells.py: the shell a command was given in, where a shell is, how a line is run with it, and stopping a
process tree. The detection cases start real shells: a command means what the shell that ran it makes of it."""
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
ASK = "import sys; sys.path.insert(0, sys.argv[1]); import shells; print(shells.current()['name'])"


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

    def ask(self, argv):
        env = dict(os.environ)
        env.pop("EKIT_SHELL", None)
        r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=120)
        return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr

    def test_a_python_started_from_bash_names_bash(self):
        bash = shells.find("bash")
        if not bash:
            self.skipTest("no bash on this machine")
        py = sys.executable.replace("\\", "/")
        here = _kit.SCRIPTS.replace("\\", "/")
        self.assertEqual(self.ask([bash, "-c", f'"{py}" -c "{ASK}" "{here}"; true']), "bash")

    def test_a_python_started_from_powershell_names_powershell(self):
        ps = shutil.which("pwsh") or (shutil.which("powershell") if WIN else None)
        if not ps:
            self.skipTest("no PowerShell on this machine")
        want = shells._name(ps)
        self.assertEqual(self.ask([ps, "-NoProfile", "-Command", f"& '{sys.executable}' -c \"{ASK}\" '{_kit.SCRIPTS}'"]),
                         want)

    def test_ancestors_starts_at_the_parent(self):
        names = [n for n, _ in shells.ancestors()]
        self.assertTrue(names, "no ancestor found")
        self.assertNotIn(None, names)


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

    def test_bash_on_windows_is_git_bash_never_wsl(self):
        if not WIN:
            self.skipTest("Windows only: elsewhere bash is bash")
        bash = shells.find("bash")
        self.assertIsNotNone(bash)
        self.assertNotIn("\\system32\\", bash.lower())
        self.assertNotIn("\\windowsapps\\", bash.lower())
        r = subprocess.run([bash, "-c", "echo $BASH_VERSION"], capture_output=True, text=True)
        self.assertTrue(r.stdout.strip())

    def test_git_bash_path_from_claude_code_wins(self):
        with tempfile.NamedTemporaryFile(suffix="bash.exe", delete=False) as f:
            path = f.name
        self.addCleanup(os.remove, path)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_GIT_BASH_PATH": path}):
            self.assertEqual(shells.git_bash(), path)

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

    def test_a_line_runs_with_its_exit_code(self):
        bash = shells.find("bash")
        if not bash:
            self.skipTest("no bash on this machine")
        r = subprocess.run(shells.command(bash, "bash", "test -n 'a b' && exit 6"))
        self.assertEqual(r.returncode, 6)


class Env(unittest.TestCase):
    def test_git_bash_gets_its_own_tools_on_path_whatever_path_it_was_started_with(self):
        bash = shells.find("bash")
        if not bash:
            self.skipTest("no bash on this machine")
        env = shells.env_for(bash, "bash", {"PATH": os.path.dirname(sys.executable)})
        r = subprocess.run(shells.command(bash, "bash", "grep -q x <<< x && sed --version >/dev/null"), env=env)
        self.assertEqual(r.returncode, 0)

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

    def test_a_process_already_gone_is_no_error(self):
        p = shells.spawn([sys.executable, "-c", "pass"])
        p.wait()
        shells.kill_tree(p)
        shells.kill_tree(p)


if __name__ == "__main__":
    unittest.main()
