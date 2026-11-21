"""The Python launcher: which interpreter the hooks and every printed command start, on any OS and in either hook shell.

Hook commands are run the way Claude Code runs them: `sh -c` (macOS, Linux, Git Bash) and PowerShell (Windows without
Git Bash), `${CLAUDE_PLUGIN_ROOT}` filled in as each does. The interpreters on PATH are fakes, so the order and the
version check are what is tested, not this machine's Pythons."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _kit

launcher = _kit.load("launcher")
HOOKS = os.path.join(_kit.ROOT, "hooks", "hooks.json")
WIN = os.name == "nt"


def hook_commands():
    """(event, command) of every hook in hooks.json."""
    with open(HOOKS) as f:
        doc = json.load(f)
    return [(event, h["command"]) for event, groups in doc["hooks"].items() for g in groups for h in g["hooks"]]


def sh_path():
    """A POSIX sh: /bin/sh, or Git for Windows' sh.exe (never WSL's bash.exe in System32)."""
    if not WIN:
        return "/bin/sh"
    git = shutil.which("git")
    if not git:
        return None
    for up in (1, 2):
        base = os.path.dirname(os.path.dirname(git)) if up == 1 else os.path.dirname(os.path.dirname(os.path.dirname(git)))
        p = os.path.join(base, "usr", "bin", "sh.exe")
        if os.path.isfile(p):
            return p
    return None


def ps_path():
    return shutil.which("pwsh") or (shutil.which("powershell") if WIN else None)


class Pick(unittest.TestCase):
    def pick(self, versions):
        return launcher.pick(lambda words: versions.get(" ".join(words)))

    def test_python3_comes_first(self):
        self.assertEqual(self.pick({"python3": (3, 12), "py -3": (3, 13), "python": (3, 11)}), "python3")

    def test_then_py_3_then_python(self):
        self.assertEqual(self.pick({"py -3": (3, 9), "python": (3, 11)}), "py -3")
        self.assertEqual(self.pick({"python": (3, 10)}), "python")

    def test_a_python_older_than_3_9_is_passed_over(self):
        self.assertEqual(self.pick({"python3": (3, 8), "py -3": (2, 7), "python": (3, 9)}), "python")
        self.assertIsNone(self.pick({"python3": (3, 8), "python": (2, 7)}))

    def test_none_that_works_is_one_message_and_exit_1(self):
        with mock.patch.object(launcher, "version_of", lambda words: (3, 8) if words == ["python"] else None):
            r = _kit.run_cli([], launcher.main)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (1, "", launcher.MESSAGE + "\n"))
        self.assertIn("3.9", launcher.MESSAGE)
        for name in ("python3", "py -3", "python"):
            self.assertIn(name, launcher.MESSAGE)

    def test_main_prints_the_pick(self):
        with mock.patch.object(launcher, "version_of", lambda words: (3, 11) if words == ["py", "-3"] else None):
            self.assertEqual(_kit.run_cli([], launcher.main), (0, "py -3\n", ""))

    def test_a_real_interpreter_reports_its_version(self):
        self.assertEqual(launcher.version_of([sys.executable]), tuple(sys.version_info[:2]))
        self.assertIsNone(launcher.version_of([os.path.join(tempfile.gettempdir(), "no-such-python")]))


class Printed(unittest.TestCase):
    def test_the_hooks_choice_is_the_one_printed(self):
        with mock.patch.dict(os.environ, {"EKIT_PY": "py -3"}):
            self.assertEqual(launcher.command(), "py -3")

    def test_without_a_hook_the_pick_is_printed(self):
        with mock.patch.dict(os.environ, {"EKIT_PY": "rm -rf /"}), \
                mock.patch.object(launcher, "version_of", lambda words: (3, 10) if words == ["python"] else None):
            self.assertEqual(launcher.command(), "python")

    def test_a_path_is_printed_so_bash_and_powershell_read_it_alike(self):
        self.assertEqual(launcher.shown("/opt/ekit/scripts/x.py"), "/opt/ekit/scripts/x.py")
        self.assertEqual(launcher.shown("/opt/my kit/x.py"), '"/opt/my kit/x.py"')
        if WIN:
            self.assertEqual(launcher.shown("C:\\Users\\a\\ekit\\x.py"), "C:/Users/a/ekit/x.py")

    def test_a_printed_script_line_is_the_interpreter_then_the_path(self):
        with mock.patch.dict(os.environ, {"EKIT_PY": "python"}):
            self.assertEqual(launcher.line("/k/scripts/scenarios.py"), "python /k/scripts/scenarios.py")


class HooksJson(unittest.TestCase):
    def test_every_hook_starts_python_through_the_launcher(self):
        cmds = hook_commands()
        self.assertEqual(len(cmds), 6)
        for event, cmd in cmds:
            m = re.search(r'"\$\{CLAUDE_PLUGIN_ROOT\}/scripts/([\w-]+\.py)"((?: --[\w-]+)*)', cmd)
            self.assertIsNotNone(m, cmd)
            self.assertEqual(cmd, launcher.hook_command(m.group(1), *m.group(2).split()), event)


class HookShells(unittest.TestCase):
    """The hook command in each shell Claude Code may use, with fake interpreters on PATH."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.root = os.path.join(self.tmp, "kit")
        os.makedirs(os.path.join(self.root, "scripts"))
        with open(os.path.join(self.root, "scripts", "probe.py"), "w") as f:
            f.write("import os, sys\nprint('ran', os.environ.get('EKIT_PY'), sys.argv[1:], repr(sys.stdin.read()))\n"
                    "sys.exit(2)\n")
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        self.cmd = launcher.hook_command("probe.py", "--hook")

    def fake(self, shell, name, version):
        """A fake interpreter on PATH: `version` answers the version check, a real one runs the script. PowerShell on
        Windows finds a .cmd; sh finds a script."""
        old = version < (3, 9)
        if WIN and shell == "powershell":  # py drops its -3, as the real launcher does
            run = (f'if "%1"=="-3" shift\r\n"{sys.executable}" %1 %2 %3 %4 %5 %6 %7 %8 %9\r\n' if name == "py"
                   else f'"{sys.executable}" %*\r\n')
            body = "@echo off\r\n" + ("exit /b 1\r\n" if old else run + "exit /b %ERRORLEVEL%\r\n")
            path = os.path.join(self.bin, name + ".cmd")
        else:
            body = "#!/bin/sh\n" + ("exit 1\n" if old else
                                    ('[ "$1" = -3 ] && shift\n' if name == "py" else "") + f'exec "{sys.executable}" "$@"\n')
            path = os.path.join(self.bin, name)
        with open(path, "w", newline="") as f:
            f.write(body)
        os.chmod(path, 0o755)

    def run_in(self, shell):
        env = dict(os.environ, PATH=self.bin, CLAUDE_PLUGIN_ROOT=self.root, PYTHONUTF8="1")
        env.pop("EKIT_PY", None)
        if shell == "sh":
            exe = sh_path()
            if not exe:
                self.skipTest("no POSIX sh on this machine")
            # sh form: Claude Code fills the placeholder in, with forward slashes on Windows
            argv = [exe, "-c", self.cmd.replace("${CLAUDE_PLUGIN_ROOT}", self.root.replace("\\", "/"))]
        else:
            exe = ps_path()
            if not exe:
                self.skipTest("no PowerShell on this machine")
            # PowerShell form: Claude Code rewrites the placeholder to the env var
            env["PATH"] = os.pathsep.join([self.bin, os.path.dirname(exe)] + ([os.environ.get("SystemRoot", "C:\\Windows") + "\\System32"] if WIN else []))
            argv = [exe, "-NoProfile", "-NonInteractive", "-Command",
                    self.cmd.replace("${CLAUDE_PLUGIN_ROOT}", "${env:CLAUDE_PLUGIN_ROOT}")]
        r = subprocess.run(argv, input='{"a": "caf\u00e9"}'.encode(), capture_output=True, env=env, timeout=120)
        return r.returncode, r.stdout.decode(errors="replace").strip(), r.stderr.decode(errors="replace").strip()

    def check_order(self, shell):
        self.fake(shell, "python3", (3, 8))
        self.fake(shell, "py", (3, 12))
        self.fake(shell, "python", (3, 12))
        rc, out, _ = self.run_in(shell)
        self.assertEqual((rc, out), (2, "ran py -3 ['--hook'] '{\"a\": \"caf\u00e9\"}'"))
        os.remove(os.path.join(self.bin, "py.cmd" if WIN and shell == "powershell" else "py"))
        rc, out, _ = self.run_in(shell)
        self.assertEqual((rc, out), (2, "ran python ['--hook'] '{\"a\": \"caf\u00e9\"}'"))

    def check_none(self, shell):
        self.fake(shell, "python3", (3, 8))
        rc, out, err = self.run_in(shell)
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(err.splitlines()[-1], launcher.MESSAGE)

    def test_sh_tries_python3_then_py_then_python_and_keeps_stdin_and_the_exit_code(self):
        self.check_order("sh")

    def test_sh_with_no_python_3_9_gives_one_message(self):
        self.check_none("sh")

    def test_powershell_tries_python3_then_py_then_python_and_keeps_stdin_and_the_exit_code(self):
        self.check_order("powershell")

    def test_powershell_with_no_python_3_9_gives_one_message(self):
        self.check_none("powershell")


if __name__ == "__main__":
    unittest.main()
