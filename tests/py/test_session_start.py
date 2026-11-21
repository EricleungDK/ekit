"""The SessionStart hook in-process: what it puts in the session's context."""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import _kit

ss = _kit.load("session-start")
launcher = _kit.load("launcher")


class Context(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(tmp.name), "repo")
        os.mkdir(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        env = mock.patch.dict(os.environ, {"EKIT_STATE": os.path.join(os.path.realpath(tmp.name), "state"),
                                           "EKIT_PY": "py -3"})
        env.start()
        self.addCleanup(env.stop)

    def context(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"cwd": self.repo, "session_id": "s1"}))), \
                contextlib.redirect_stdout(out):
            ss.main()
        return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]

    def test_the_python_the_hook_found_starts_every_printed_command(self):
        ctx = self.context()
        self.assertIn("[ekit] Python: py -3", ctx)
        self.assertIn(f"[ekit] Scenario runner: py -3 {launcher.shown(os.path.join(_kit.SCRIPTS, 'scenarios.py'))}", ctx)

    def test_preflight_names_the_os_and_its_text_is_not_mangled(self):
        ctx = self.context()
        self.assertIn(f"[ekit] Preflight (this env):\nos: {_kit.load('preflight').os_name()}", ctx)
        self.assertNotIn("â", ctx)  # UTF-8 read as cp1252 on Windows

    def test_the_always_on_rules_stay(self):
        ctx = self.context()
        self.assertIn("failure-triage", ctx)
        self.assertNotIn("taste-it", ctx)


if __name__ == "__main__":
    unittest.main()
