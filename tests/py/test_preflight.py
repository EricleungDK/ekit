"""preflight.py in-process: one line per problem with its fallback and the install line for this OS, the OS name,
the noreply-email warning, and the finish report's `Env:` line. The tools on PATH are fakes in a temp dir."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import _kit

pf = _kit.load("preflight")
WIN = os.name == "nt"
HUNG = f'"{sys.executable}" -c "import time; time.sleep(30)"'


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in ("CHROME_BIN", "PLAYWRIGHT_BROWSERS_PATH", "EKIT_PY", "EKIT_SHELL", "XDG_CACHE_HOME", "LOCALAPPDATA"):
            os.environ.pop(name, None)  # the host's browser and Python must not reach these cases
        os.environ.update(HOME=self.home, USERPROFILE=self.home)
        self.bin = self.fakebin("bin")
        self.proj = self.dir("p")

    def dir(self, name):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        return d

    def fakebin(self, name, *tools):
        d = self.dir(name)
        for t in tools:
            self.stub(d, t, "exit 0")
        return d

    def stub(self, d, name, posix, cmd=None):
        """A fake tool: `posix` is its sh body, `cmd` its .cmd body on Windows (default: the same line)."""
        if name in ("python3", "python"):
            posix, cmd = f'exec "{sys.executable}" "$@"', f'"{sys.executable}" %*'
        if WIN:
            with open(os.path.join(d, name + ".cmd"), "w") as f:
                f.write("@echo off\r\n" + (cmd if cmd is not None else posix) + "\r\n")
        else:
            p = os.path.join(d, name)
            with open(p, "w") as f:
                f.write("#!/bin/sh\n" + posix + "\n")
            os.chmod(p, 0o755)

    def run_pf(self, *argv, path=None):
        os.environ["PATH"] = path or self.bin
        r = _kit.run_cli(list(argv) or [self.proj], pf.main)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def write(self, rel, text, base=None):
        p = os.path.join(base or self.proj, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)


class OsAndInstallLines(Case):
    def test_the_os_is_named_first(self):
        want = {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "Linux")
        self.assertEqual(self.run_pf(self.proj).splitlines()[0], f"os: {want}")
        self.assertEqual(pf.os_name("darwin"), "macOS")
        self.assertEqual(pf.os_name("win32"), "Windows")
        self.assertEqual(pf.os_name("linux"), "Linux")

    def test_each_missing_tool_gets_the_install_line_for_this_os(self):
        os.environ["EKIT_PY"] = "py -3"  # the Python the hook found
        for plat, line in (("darwin", "brew install jq"), ("win32", "winget install jqlang.jq"),
                           ("linux", "sudo apt install jq")):
            with mock.patch.object(pf, "platform", return_value=plat):
                self.assertIn(f"⚠ jq: missing → py -3 -c 'import json'; install: {line}",
                              self.run_pf(path=self.fakebin("b-" + plat, "rg")))
        with mock.patch.object(pf, "platform", return_value="win32"):
            out = self.run_pf(path=self.fakebin("bw", "jq"))
        self.assertIn("rg: missing → grep -rn / find; install: winget install BurntSushi.ripgrep.MSVC", out)

    def test_every_tool_has_an_install_line_on_every_os(self):
        for tool in pf.INSTALL:
            for plat in ("darwin", "win32", "linux"):
                self.assertTrue(pf.install(tool, plat), (tool, plat))


class Tools(Case):
    def test_bare_python_missing_names_the_python_to_use(self):
        b = self.fakebin("b1")
        self.stub(b, "python3", "")
        out = self.run_pf(path=b)
        self.assertIn("⚠ python: missing → use python3\n", out)  # python3 is here: no install line for python
        self.assertIn("jq: missing → python3 -c 'import json'", out)
        self.assertIn("rg: missing → grep -rn / find", out)
        self.assertNotIn("cargo", out)
        self.assertNotIn("docker", out)

    def test_quiet_with_nothing_wrong_prints_only_the_os(self):
        b = self.fakebin("b2", "jq", "rg")
        self.stub(b, "python3", "")
        self.stub(b, "python", "")
        self.assertEqual(self.run_pf("--quiet", self.proj, path=b), f"os: {pf.os_name()}\n")

    def test_a_python_project_without_a_venv(self):
        self.write("pyproject.toml", '[project]\nname = "x"\ndependencies = ["requests"]\n')
        self.assertIn("venv: no .venv → uv sync, then uv run <cmd>", self.run_pf())
        os.mkdir(os.path.join(self.proj, ".venv"))
        self.assertNotIn("venv:", self.run_pf())
        p2 = self.dir("p2")
        self.write("pyproject.toml", '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', p2)
        self.assertNotIn("venv:", self.run_pf(p2))
        self.write("requirements.txt", "", p2)
        self.assertIn("venv: no .venv", self.run_pf(p2))

    def test_a_rust_project_without_cargo(self):
        self.write("Cargo.toml", "")
        self.assertIn("cargo: missing → Cargo.toml present; rust build/test can't run here", self.run_pf())

    def test_node_below_the_engines_range(self):
        self.write("package.json", '{"engines":{"node":">=22"}}')
        b = self.fakebin("b5")
        self.stub(b, "node", "echo v20.1.0")
        self.assertIn("node: v20.1.0 < engines >=22 → nvm use 22", self.run_pf(path=b))
        self.stub(b, "node", "echo v24.0.0")
        self.assertNotIn("node:", self.run_pf(path=b))
        self.assertIn("node: missing → engines >=22", self.run_pf())

    def test_docker_unusable_or_hung(self):
        self.write("docker-compose.yml", "")
        b = self.fakebin("b6")
        self.stub(b, "docker", "echo 'permission denied while trying to connect to the Docker daemon socket' >&2; exit 1",
                  "echo permission denied while trying to connect to the Docker daemon socket 1>&2\r\nexit /b 1")
        out = self.run_pf(path=b)
        self.assertIn("docker: unusable (permission denied", out)
        self.assertIn("container tests → verification debt", out)
        self.stub(b, "docker", HUNG, HUNG)
        t0 = time.time()
        self.assertIn("docker: unusable", self.run_pf(path=b))
        self.assertLess(time.time() - t0, 20)
        self.stub(b, "docker", "exit 0")
        self.assertIn("ok docker", self.run_pf(path=b))

    def test_playwright_needs_a_chromium(self):
        self.write("package.json", '{"devDependencies":{"@playwright/test":"1.0"}}')
        self.assertIn("playwright: no chromium in the ms-playwright cache or $CHROME_BIN → npx playwright install "
                      "chromium", self.run_pf())
        for cache in (".cache/ms-playwright/chromium-1", "Library/Caches/ms-playwright/chromium-1200"):
            d = os.path.join(self.home, cache)
            os.makedirs(d)
            self.assertNotIn("playwright:", self.run_pf(), cache)
            os.rmdir(d)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = self.dir("pwb")
        os.mkdir(os.path.join(self.tmp, "pwb", "chromium_headless_shell-1200"))
        self.assertNotIn("playwright:", self.run_pf())
        del os.environ["PLAYWRIGHT_BROWSERS_PATH"]
        os.environ["LOCALAPPDATA"] = self.dir("lad")
        os.makedirs(os.path.join(self.tmp, "lad", "ms-playwright", "chromium-1"))
        self.assertNotIn("playwright:", self.run_pf())

    def test_gh_not_authed(self):
        b = self.fakebin("b8")
        self.stub(b, "gh", '[ "$1" = auth ] && exit 1; exit 0', 'if "%1"=="auth" exit /b 1')
        out = self.run_pf(path=b)
        self.assertIn("gh: not authed → user runs: ! gh auth login", out)
        self.assertIn("gh issue view: always pass --json", out)
        self.stub(b, "gh", "exit 0")
        self.assertIn("ok gh", self.run_pf(path=b))

    def test_a_read_only_git_dir(self):
        os.mkdir(os.path.join(self.proj, ".git"))
        with mock.patch.object(pf.os, "access", return_value=False):
            self.assertIn("git: .git read-only (sandbox) → commits need unsandboxed run", self.run_pf())

    def test_loopback_bind_blocked(self):
        with mock.patch.object(pf.socket, "socket", side_effect=PermissionError(1, "Operation not permitted")):
            self.assertIn("loopback: bind 127.0.0.1 blocked (sandbox) → server/e2e tests need unsandboxed run",
                          self.run_pf())
        self.assertIn("ok loopback", self.run_pf())


class ScenarioDrivers(Case):
    def test_missing_driver_tools_warn_for_the_tools_the_scenarios_run(self):
        self.write(".ekit/scenarios/a/run.sh",
                   'tmux new -d -s t\nif ! expect -c "spawn x"; then exit 1; fi\nout=$(curl -s localhost)\n')
        out = self.run_pf()
        for t in ("tmux", "expect", "curl"):
            self.assertIn(f"{t}: missing → scenarios needing {t} can't run here → human verdict / verification debt", out)
        b = self.fakebin("b11", "tmux", "expect", "curl")
        out = self.run_pf(path=b)
        self.assertIn("ok tmux", out)
        self.assertNotIn("curl:", out)
        self.assertNotIn("ok tmux", self.run_pf("--quiet", self.proj, path=b))
        self.assertNotIn("tmux:", self.run_pf(self.dir("empty")))

    def test_the_word_in_a_string_or_in_prose_is_not_a_use(self):
        self.write(".ekit/scenarios/a/run.sh", "python3 app.py --help\n"
                   "printf 'import { it, expect } from \"vitest\"; expect(add(1, 2)).toBe(3)' > t.ts\n"
                   'echo "no curl here, tmux neither"\n')
        self.write(".ekit/scenarios/a/SCENARIO.md", "- expected: we expect curl-like output; tmux not needed\n")
        out = self.run_pf()
        for t in ("tmux", "expect", "curl", "playwright"):
            self.assertNotIn(f"{t}:", out)

    def test_a_run_py_uses_a_tool_it_starts_by_name_in_an_argv_or_looks_up(self):
        self.write(".ekit/scenarios/a/run.py", 'import shutil, subprocess\nsubprocess.run(["tmux", "new", "-d"])\n'
                   "subprocess.run(\n    [\n        'curl', '-s', 'localhost'])\nassert shutil.which('expect')\n")
        out = self.run_pf()
        for t in ("tmux", "expect", "curl"):
            self.assertIn(f"{t}: missing → scenarios needing {t} can't run here → human verdict / verification debt", out)

    def test_a_tuple_argv_and_a_python_helper_in_capitals_are_read_too(self):
        self.write(".ekit/scenarios/a/run.py", 'import subprocess\nsubprocess.run(("tmux", "new", "-d"))\n')
        self.write(".ekit/scenarios/a/DRIVE.PY", "import subprocess\nsubprocess.run(['curl', '-s', 'x'])\n")
        out = self.run_pf()
        for t in ("tmux", "curl"):
            self.assertIn(f"{t}: missing → scenarios needing {t} can't run here → human verdict / verification debt", out)

    def test_a_run_py_tool_named_in_capitals_or_in_a_raw_string_is_read(self):
        self.write(".ekit/scenarios/a/run.py", 'import subprocess\nsubprocess.run(["tmux.EXE", "new"])\n'
                   "subprocess.run([r'curl', '-s', 'x'])\nsubprocess.run((R\"expect\", \"-c\", \"x\"))\n")
        out = self.run_pf()
        for t in ("tmux", "curl", "expect"):
            self.assertIn(f"{t}: missing → scenarios needing {t} can't run here → human verdict / verification debt", out)

    def test_a_run_py_naming_a_tool_in_a_string_or_a_comment_is_not_a_use(self):
        self.write(".ekit/scenarios/a/run.py", 'print("curl here, tmux neither")\n# expect output\n'
                   'subprocess.run(["python3", "-c", "tmux"])\nexpect = 1\n')
        out = self.run_pf()
        for t in ("tmux", "expect", "curl"):
            self.assertNotIn(f"{t}:", out)

    def test_a_run_ps1_uses_a_tool_in_command_position(self):
        self.write(".ekit/scenarios/a/run.ps1", 'Write-Output "expect nothing"\ntmux new -d\n'
                   "if ($LASTEXITCODE) { & Curl.exe -s localhost }\n")
        out = self.run_pf()
        for t in ("tmux", "curl"):
            self.assertIn(f"{t}: missing → scenarios needing {t} can't run here → human verdict / verification debt", out)
        self.assertNotIn("expect:", out)

    def test_a_playwright_scenario_triggers_the_playwright_check(self):
        self.write(".ekit/scenarios/a/run.sh", "npx playwright test\n")
        self.assertIn("playwright: no chromium", self.run_pf())

    def test_the_pre_rename_scenario_dir_is_read_too(self):
        self.write(".ek/scenarios/a/run.sh", "tmux new -d -s t\n")
        self.assertIn("tmux: missing", self.run_pf())


class NoreplyEmail(Case):
    def repo(self, remote, email):
        r = self.dir("r")
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        subprocess.run(["git", "init", "-q", r], check=True, env=env)
        if remote:
            subprocess.run(["git", "-C", r, "remote", "add", "origin", remote], check=True, env=env)
        if email:
            subprocess.run(["git", "-C", r, "config", "user.email", email], check=True, env=env)
        return r

    def path(self):
        import shutil
        return os.pathsep.join([self.bin, os.path.dirname(shutil.which("git"))])

    def test_a_github_remote_with_a_private_email_warns_without_printing_it(self):
        r = self.repo("git@github.com:o/r.git", "me@example.com")
        out = self.run_pf(r, path=self.path())
        self.assertIn("git: user.email is not a GitHub noreply address → GitHub may reject the push (email privacy); "
                      "set: git config user.email <id>+<login>@users.noreply.github.com", out)
        self.assertNotIn("me@example.com", out)

    def test_a_noreply_email_or_another_host_is_quiet(self):
        for remote, email in (("https://github.com/o/r", "1+o@users.noreply.github.com"),
                              ("https://github.com/o/r", "1+O@Users.NoReply.GitHub.com"),
                              ("https://gitlab.com/o/r", "me@example.com"), (None, "me@example.com")):
            with self.subTest(remote=remote):
                import shutil
                shutil.rmtree(os.path.join(self.tmp, "r"), ignore_errors=True)
                self.assertNotIn("noreply", self.run_pf(self.repo(remote, email), path=self.path()))


class Env(Case):
    """--env: the finish report's Env line, a probe of what this process can do, with the shell it was run from."""

    def env_line(self, **extra):
        os.environ.update(extra)
        return self.run_pf("--env").strip()

    def test_a_process_that_writes_outside_the_project_is_unsandboxed(self):
        self.assertEqual(self.env_line(EKIT_SHELL="bash"), "Env: unsandboxed; shell: bash")
        self.assertEqual(os.listdir(os.path.join(self.home, ".cache", "ekit")), [])

    def test_the_shell_is_the_one_the_probe_was_run_from(self):
        self.assertEqual(self.env_line(EKIT_SHELL="powershell"), "Env: unsandboxed; shell: powershell")

    def test_no_write_outside_the_project_is_sandboxed(self):
        os.environ["XDG_CACHE_HOME"] = os.path.join(self.tmp, "nofile", "x")
        with open(os.path.join(self.tmp, "nofile"), "w"):
            pass
        self.assertEqual(self.env_line(EKIT_SHELL="bash"), "Env: sandboxed (no write outside the project); shell: bash")

    def test_loopback_blocked_and_both_signs_named(self):
        with mock.patch.object(pf.socket, "socket", side_effect=PermissionError(1, "Operation not permitted")):
            self.assertEqual(self.env_line(EKIT_SHELL="bash"), "Env: sandboxed (loopback bind blocked); shell: bash")
            with open(os.path.join(self.tmp, "nofile"), "w"):
                pass
            os.environ["XDG_CACHE_HOME"] = os.path.join(self.tmp, "nofile", "x")
            self.assertEqual(self.env_line(),
                             f"Env: sandboxed (no write outside the project, loopback bind blocked); shell: bash")


if __name__ == "__main__":
    unittest.main()
