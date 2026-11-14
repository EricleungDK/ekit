"""The eval case that starts an orchestrate session (orchestrate-mech-tick) arms the Stop gate. Its prompt asks for a
verdict, not for work: running the scaffold's tests must leave the tree the gate hashes as it was at session start.
Otherwise the gate asks for a finish report, and that report replaces the answer the graders read."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import _kit

CASE = os.path.join(_kit.ROOT, "evals", "orchestrate-mech-tick")
GATE = os.path.join(_kit.SCRIPTS, "finish-gate.py")


class TestOrchestrateMechTickScaffold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(self.tmp.name), "repo")
        os.mkdir(self.repo)
        subprocess.run(["bash", os.path.join(CASE, "setup.sh")], cwd=self.repo, check=True, capture_output=True)
        self.env = dict(os.environ, EKIT_STATE=os.path.join(self.tmp.name, "state"))
        for name in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):  # the eval's child writes bytecode beside the source
            self.env.pop(name, None)

    def hook(self, *flags, **payload):
        data = dict({"session_id": "s1", "cwd": self.repo}, **payload)
        r = subprocess.run([sys.executable, "-I", GATE, *flags], input=json.dumps(data), env=self.env,
                           capture_output=True, text=True, check=True)
        return r.stdout.strip()

    def start(self):
        with open(os.path.join(CASE, "prompt.md")) as f:
            prompt = f.read().split("---\n", 2)[2]  # the text after the front matter is what the session receives
        self.hook("--baseline", hook_event_name="SessionStart")
        self.hook("--arm", hook_event_name="UserPromptSubmit", prompt=prompt)

    def test_running_the_scaffolds_tests_is_not_work_for_the_stop_gate(self):
        self.start()
        ran = subprocess.run([sys.executable, "-m", "unittest"], cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.repo, "__pycache__")), "the run wrote no bytecode: nothing tested")
        self.assertEqual(self.hook(hook_event_name="Stop", last_assistant_message="Tick 1 only. Message to A: ..."), "")

    def test_the_gate_is_armed_and_still_sees_an_edit(self):
        self.start()
        with open(os.path.join(self.repo, "version.py"), "a") as f:
            f.write("# edit\n")
        out = self.hook(hook_event_name="Stop", last_assistant_message="Tick 1 only.")
        self.assertEqual(json.loads(out)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
