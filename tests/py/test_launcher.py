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
        self.assertEqual(launcher.shown("/opt/my kit/x.py"), "'/opt/my kit/x.py'")
        self.assertEqual(launcher.shown("/opt/$HOME kit/x.py"), "'/opt/$HOME kit/x.py'")  # literal in both shells
        if WIN:
            self.assertEqual(launcher.shown("C:\\Users\\a\\ekit\\x.py"), "C:/Users/a/ekit/x.py")

    def test_a_quote_in_a_path_is_spelled_the_way_the_shell_that_reads_it_spells_it(self):
        with mock.patch.dict(os.environ, {"EKIT_SHELL": "bash"}):
            self.assertEqual(launcher.shown("/o/O'Brien $HOME/x.py"), "'/o/O'\\''Brien $HOME/x.py'")
        for ps in ("powershell", "pwsh"):
            with mock.patch.dict(os.environ, {"EKIT_SHELL": ps}):
                self.assertEqual(launcher.shown("/o/O'Brien $HOME/x.py"), "'/o/O''Brien $HOME/x.py'")

    def test_a_printed_script_line_is_the_interpreter_then_the_path(self):
        with mock.patch.dict(os.environ, {"EKIT_PY": "python"}):
            self.assertEqual(launcher.line("/k/scripts/scenarios.py"), "python /k/scripts/scenarios.py")


class HooksJson(unittest.TestCase):
    def test_every_hook_starts_python_through_the_launcher(self):
        cmds = hook_commands()
        self.assertEqual(len(cmds), 6)
        for event, cmd in cmds:
            m = re.search(r'"\$CLAUDE_PLUGIN_ROOT/scripts/([\w-]+\.py)"((?: --[\w-]+)*)', cmd)
            self.assertIsNotNone(m, cmd)
            self.assertEqual(cmd, launcher.hook_command(m.group(1), *m.group(2).split()), event)


class HookCommand(unittest.TestCase):
    """The command string itself: how its sh part and its PowerShell part are built. They run in a real sh in
    tests/launcher.test.sh, and in PowerShell and Git Bash in tests/windows-smoke.py."""

    def parts(self):
        cmd = launcher.hook_command("probe.py", "--hook")
        head, sep, ps = cmd.partition(" # \\' ; ")
        self.assertTrue(sep, cmd)
        self.assertTrue(head.startswith("set \\' ; "), cmd)
        return head[len("set \\' ; "):], ps

    def test_the_root_is_read_from_the_env_var_never_from_pasted_text(self):
        """Claude Code pastes the plugin path in place of ${CLAUDE_PLUGIN_ROOT} unescaped: a ' or $ in the path
        would break the command. The env var it exports is read by each shell instead."""
        sh, ps = self.parts()
        cmd = launcher.hook_command("probe.py", "--hook")
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", cmd)
        self.assertIn('-I "$CLAUDE_PLUGIN_ROOT/scripts/probe.py" --hook', sh)
        self.assertIn('-I "$env:CLAUDE_PLUGIN_ROOT/scripts/probe.py" --hook', ps)

    def test_each_part_tries_python3_then_py_3_then_python_and_checks_3_9(self):
        sh, ps = self.parts()
        self.assertIn('for p in python3 "py -3" python; do', sh)
        self.assertIn("foreach ($p in 'python3', 'py -3', 'python')", ps)
        for part in (sh, ps):
            self.assertIn("sys.exit(sys.version_info < (3, 9))", part)
            self.assertIn(launcher.MESSAGE, part)

    def test_the_sh_part_holds_no_quote_that_would_end_powershells_string(self):
        sh, _ = self.parts()
        self.assertNotIn("'", sh)

    def test_each_part_hands_the_choice_on_and_keeps_the_exit_code(self):
        sh, ps = self.parts()
        self.assertIn('EKIT_PY="$p" exec $p', sh)
        self.assertIn("$env:EKIT_PY = $p", ps)
        self.assertIn("exit $LASTEXITCODE", ps)
        self.assertTrue(sh.endswith("exit 1"))
        self.assertTrue(ps.endswith("exit 1"))


if __name__ == "__main__":
    unittest.main()
