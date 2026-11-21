"""Hook smoke test: every hooks.json command, run the way Claude Code runs it on Windows without Git Bash, in plain
PowerShell with no Git Bash (and no bash) on PATH: only Python, git and PowerShell itself. Each hook gets a real
payload and the real scripts; its exit code and output are what Claude Code would read.

Then task-verify's record for a command holding `&&`, declared in PowerShell and in Git Bash, each re-run in its own
shell: the shell found by the real ancestry, not set by the test.

PowerShell missing (a Linux host without pwsh): skipped with that reason."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import _kit

WIN = os.name == "nt"
PS = shutil.which("pwsh") or (shutil.which("powershell") if WIN else None)
HOOKS = os.path.join(_kit.ROOT, "hooks", "hooks.json")


def bare_path():
    """PATH with Python, git and PowerShell and nothing else: no Git Bash. On Windows git comes from Git's cmd dir,
    which holds no bash; System32 stays (PowerShell needs it), and its bash.exe is WSL's launcher, not Git Bash."""
    dirs = [os.path.dirname(sys.executable), os.path.dirname(PS)]
    git = shutil.which("git")
    if WIN:
        root = os.path.dirname(os.path.dirname(os.path.realpath(git)))
        while root and not os.path.isdir(os.path.join(root, "cmd")) and os.path.dirname(root) != root:
            root = os.path.dirname(root)
        dirs += [os.path.join(root, "cmd"), os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")]
    else:
        dirs.append(os.path.dirname(git))
    return os.pathsep.join(dict.fromkeys(dirs))


@unittest.skipUnless(PS, "no PowerShell on this machine")
class PlainPowerShell(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.tmp, "repo")
        os.mkdir(self.repo)
        self.env = {k: v for k, v in os.environ.items() if k not in ("EKIT_PY", "EKIT_SHELL", "MSYSTEM", "SHELL")}
        self.env.update(PATH=bare_path(), CLAUDE_PLUGIN_ROOT=_kit.ROOT, EKIT_STATE=os.path.join(self.tmp, "state"),
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, CLAUDE_CODE_SESSION_ID="s1")
        self.git("init", "-q")
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("a\n")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
        with open(HOOKS) as f:
            self.hooks = {e: g[0]["hooks"][0]["command"] for e, g in json.load(f)["hooks"].items()}

    def git(self, *args):
        subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, env=self.env)

    def ps(self, command, stdin=""):
        r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command", command], input=stdin.encode(),
                           capture_output=True, env=self.env, cwd=self.repo, timeout=300)
        return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")

    def hook(self, event, **payload):
        """the hook as Claude Code runs it in PowerShell: its placeholder rewritten to the env var"""
        cmd = self.hooks[event].replace("${CLAUDE_PLUGIN_ROOT}", "${env:CLAUDE_PLUGIN_ROOT}")
        data = dict({"session_id": "s1", "cwd": self.repo, "hook_event_name": event}, **payload)
        return self.ps(cmd, json.dumps(data))

    def test_no_git_bash_is_on_the_path(self):
        found = shutil.which("bash", path=self.env["PATH"])
        self.assertTrue(found is None or "system32" in found.lower(), found)
        self.assertIsNone(shutil.which("sh", path=self.env["PATH"]))

    def test_every_hook_starts_and_answers(self):
        rc, out, err = self.hook("SessionStart", source="startup")
        self.assertEqual(rc, 0, err)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[ekit] Python: ", ctx)
        self.assertIn("[ekit] Scenario runner: ", ctx)
        self.assertIn("os: ", ctx)

        self.assertEqual(self.hook("UserPromptSubmit", prompt="/ekit:orchestrate-agent fix it")[:2], (0, ""))

        rc, out, err = self.hook("PostToolUseFailure", tool_name="Bash", tool_input={"command": "jq .a x.json"},
                                 error="bash: jq: command not found")
        self.assertEqual(rc, 0, err)
        self.assertIn("jq missing →", json.loads(out)["hookSpecificOutput"]["additionalContext"])

        task = {"task_id": "t1", "task_subject": "Unit", "task_description": "Verify: `git status`"}
        self.assertEqual(self.hook("TaskCreated", **task)[:2], (0, ""))
        rc, out, err = self.hook("TaskCompleted", **task)
        self.assertEqual(rc, 2, err)  # the code that keeps the task open: no run recorded
        self.assertIn("no run recorded", err)
        self.assertIn("task-verify.py run -- git status", err)

        rc, out, err = self.hook("Stop", stop_hook_active=False)
        self.assertEqual((rc, out), (0, ""), err)  # nothing changed since the session started

    def test_a_command_with_and_and_is_rerun_in_the_shell_it_was_declared_in(self):
        tv = os.path.join(_kit.SCRIPTS, "task-verify.py")
        py = sys.executable
        # declared in PowerShell (Windows PowerShell 5.1 cannot parse && and records its exit 1; PowerShell 7 runs it)
        ps_line = "git --version && git status"
        self.ps(f"& '{py}' -I '{tv}' declare -- '{ps_line}'")
        # declared in a POSIX shell: Git Bash on Windows
        bash = _kit.load("shells").find("bash")
        if not bash:
            self.skipTest("no bash on this machine")
        sh_line = "test -f a.txt && grep -q a a.txt"
        r = subprocess.run([bash, "-c", f'"{py.replace(chr(92), "/")}" -I "{tv.replace(chr(92), "/")}" declare -- '
                                        f"'{sh_line}'; true"], env=dict(self.env, PATH=os.environ["PATH"]),
                           cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        # each re-run from the other shell: run in its own
        rc, _, err = self.ps(f"& '{py}' -I '{tv}' run -- '{sh_line}'")
        self.assertEqual(rc, 0, err)
        self.assertIn(f"`{sh_line}` exited 0 in bash", err)
        r = subprocess.run([bash, "-c", f'"{py.replace(chr(92), "/")}" -I "{tv.replace(chr(92), "/")}" run -- '
                                        f"'{ps_line}'; true"], env=dict(self.env, PATH=os.environ["PATH"]),
                           cwd=self.repo, capture_output=True, text=True)
        ps_name = os.path.basename(PS).lower().replace(".exe", "")
        self.assertRegex(r.stderr, rf"`{ps_line}` exited \d+ in {ps_name}")
        with open(os.path.join(self.tmp, "state", "verify", os.listdir(os.path.join(self.tmp, "state", "verify"))[0],
                               "verify.json")) as f:
            shells = {run["cmd"]: run["shell"] for run in json.load(f)}
        self.assertEqual(shells, {sh_line: "bash", ps_line: ps_name})


if __name__ == "__main__":
    unittest.main()
