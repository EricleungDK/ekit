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
from scripts import shells  # bash: Git Bash on Windows, where a bare "bash" starts WSL's launcher



def case_dir(name, root=None):
    """evals/<name> of the git checkout that holds root (default _kit.ROOT, the tests' own checkout): its top, as
    `git rev-parse --show-toplevel` names it. R3's mutation run executes the tests from a copy under
    <checkout>/mutants/ that holds evals/ too (mutants.also_copy), its scripts mutated: a plain dir inside the checkout,
    so the case, its scaffold and the kit its hooks call are the checkout's, the code as written. A worktree inside
    another checkout (<repo>/.claude/worktrees/<name>) is a checkout of its own: its own case. Outside git, or a top
    with no such case: the nearest evals/<name> above root, else evals/<name> of root, for the error to name."""
    root = os.path.abspath(root or _kit.ROOT)
    here = root
    while not os.path.isdir(here) and os.path.dirname(here) != here:
        here = os.path.dirname(here)
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                                                            "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_PREFIX")}
    top = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         env=env)  # a git hook's GIT_DIR would make it answer the cwd
    if top.returncode == 0 and os.path.isdir(os.path.join(top.stdout.strip(), "evals", name)):
        return os.path.join(top.stdout.strip(), "evals", name)
    at = root
    while not os.path.isdir(os.path.join(at, "evals", name)) and os.path.dirname(at) != at:
        at = os.path.dirname(at)
    return os.path.join(at if os.path.isdir(os.path.join(at, "evals", name)) else root, "evals", name)


def eval_git(root=None):
    """argv that runs git as the agent under an eval does: through evals/git-shim.sh, which evals/run.sh puts first on
    PATH as `git` and which runs a case's verdict script after each ref move (the eval sandbox turns git hooks off, so
    a scaffold installs none). The shim is the one beside case_dir's cases, the checkout's."""
    return [shells.find("bash"), os.path.join(os.path.dirname(case_dir("stack-plan-js-to-ts", root)), "git-shim.sh")]


CASE = case_dir("orchestrate-mech-tick")
GATE = os.path.join(_kit.SCRIPTS, "finish-gate.py")


class TestOrchestrateMechTickScaffold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(self.tmp.name), "repo")
        os.mkdir(self.repo)
        bash = shells.find("bash")
        subprocess.run([bash, os.path.join(CASE, "setup.sh")], cwd=self.repo, check=True, capture_output=True,
                       env=shells.env_for(bash, "bash"))
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
