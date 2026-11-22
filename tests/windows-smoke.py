"""Windows smoke: ekit in the real shells of a Windows machine, where the unit tests (tests/py) fake them.

    python tests/windows-smoke.py      (CI: the hooks-windows job; locally: verify step (a))

Each check prints `ok` or `FAIL`; exit 1 when any fails. Not Windows: nothing to check, exit 0.
- the hook command in plain PowerShell: python3, py -3, python in that order, the version check, one message, stdin
  and the exit code kept, the plugin dir read from CLAUDE_PLUGIN_ROOT (a ' a $ and a space in it);
- every hooks.json hook in plain PowerShell with no Git Bash on PATH, only Python, Git's cmd dir and System32;
- task-verify: a command holding && declared in PowerShell and in Git Bash, each re-run in its own shell (found from
  the real process tree); a native exit code through PowerShell;
- shells: bash is Git Bash, never WSL's; the shell found under bash and under PowerShell; Git Bash's tools on PATH;
- a scenario timeout with only Git's cmd dir on PATH stops the whole tree in time and is a FAIL;
- run.py scenarios in plain PowerShell with no bash on PATH: a pass, a fail with its exit code, a run.ps1 beside
  them (one whose last native command fails: a FAIL with that code), and a timeout that stops the tree (a background
  child included) and is a FAIL.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
import launcher  # noqa: E402 - the kit's scripts dir is put on sys.path just above
import shells  # noqa: E402 - imported after the sys.path line above, like the one before it

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"\n       {detail}"))
    if not ok:
        FAILS.append(name)


def powershell():
    return shutil.which("pwsh") or shutil.which("powershell")


def git_root():
    d = os.path.dirname(os.path.realpath(shutil.which("git")))
    while d and not os.path.isdir(os.path.join(d, "cmd")) and os.path.dirname(d) != d:
        d = os.path.dirname(d)
    return d


def bare_path(*extra):
    """Python, Git's cmd dir (git.exe and no bash), PowerShell and System32: no Git Bash."""
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    dirs = [os.path.dirname(sys.executable), os.path.join(git_root(), "cmd"), os.path.dirname(powershell()), system32]
    return os.pathsep.join(dict.fromkeys(list(extra) + dirs))


def ps(command, env, cwd=None, stdin=""):
    r = subprocess.run([powershell(), "-NoProfile", "-NonInteractive", "-Command", command], input=stdin.encode(),
                       capture_output=True, env=env, cwd=cwd, timeout=300)
    return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")


def claude_code_fills(cmd, root):
    """What Claude Code does to a hook command before PowerShell: ${CLAUDE_PLUGIN_ROOT} becomes the path, pasted
    unescaped (the command reads the env var instead, so nothing is pasted into it)."""
    return cmd.replace("${CLAUDE_PLUGIN_ROOT}", root)


def odd_kit(tmp):
    """A copy of the kit at a path holding a ' a $ and a space."""
    kit = os.path.join(tmp, "O'Brien $HOME kit")
    shutil.copytree(SCRIPTS, os.path.join(kit, "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(ROOT, "hooks"), os.path.join(kit, "hooks"))
    return kit


def launcher_in_powershell(tmp):
    print("launcher: the hook command in PowerShell")
    kit = os.path.join(tmp, "O'Brien $HOME probe")
    os.makedirs(os.path.join(kit, "scripts"))
    with open(os.path.join(kit, "scripts", "probe.py"), "w") as f:
        f.write("import os, sys\nprint('ran', os.environ.get('EKIT_PY'), sys.argv[1:], repr(sys.stdin.read()))\n"
                "sys.exit(2)\n")
    bin_ = os.path.join(tmp, "bin")
    os.mkdir(bin_)

    def fake(name, old):
        run = (f'if "%1"=="-3" shift\r\n"{sys.executable}" %1 %2 %3 %4 %5 %6 %7 %8 %9\r\n' if name == "py"
               else f'"{sys.executable}" %*\r\n')
        with open(os.path.join(bin_, name + ".cmd"), "w", newline="") as f:
            f.write("@echo off\r\n" + ("exit /b 1\r\n" if old else run + "exit /b %ERRORLEVEL%\r\n"))

    cmd = claude_code_fills(launcher.hook_command("probe.py", "--hook"), kit)
    env = dict(os.environ, PATH=os.pathsep.join([bin_, os.path.dirname(powershell()),
                                                 os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")]),
               CLAUDE_PLUGIN_ROOT=kit, PYTHONUTF8="1")
    env.pop("EKIT_PY", None)
    payload = '{"a": "caf\u00e9"}'
    fake("python3", True)
    fake("py", False)
    fake("python", False)
    rc, out, err = ps(cmd, env, stdin=payload)
    check("python3 too old → py -3; stdin, args and exit code kept",
          (rc, out.strip()) == (2, f"ran py -3 ['--hook'] {payload!r}"), (rc, out, err))
    os.remove(os.path.join(bin_, "py.cmd"))
    rc, out, err = ps(cmd, env, stdin=payload)
    check("no py → python", (rc, out.strip()) == (2, f"ran python ['--hook'] {payload!r}"), (rc, out, err))
    os.remove(os.path.join(bin_, "python.cmd"))
    rc, out, err = ps(cmd, env, stdin=payload)
    check("no Python 3.9+ → exit 1 and one message",
          rc == 1 and err.strip().splitlines()[-1:] == [launcher.MESSAGE], (rc, out, err))


def hooks_in_plain_powershell(tmp):
    print("hooks: every hooks.json command in plain PowerShell, no Git Bash on PATH")
    kit = odd_kit(tmp)
    repo = os.path.join(tmp, "repo")
    os.mkdir(repo)
    env = {k: v for k, v in os.environ.items() if k not in ("EKIT_PY", "EKIT_SHELL", "MSYSTEM", "SHELL")}
    env.update(PATH=bare_path(), CLAUDE_PLUGIN_ROOT=kit, EKIT_STATE=os.path.join(tmp, "state"),
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    found = shutil.which("bash", path=env["PATH"])
    check("no Git Bash on PATH", found is None or "system32" in found.lower(), found)
    check("no sh on PATH", shutil.which("sh", path=env["PATH"]) is None, shutil.which("sh", path=env["PATH"]))
    for args in (["init", "-q"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)
    with open(os.path.join(kit, "hooks", "hooks.json")) as f:
        hooks = {e: g[0]["hooks"][0]["command"] for e, g in json.load(f)["hooks"].items()}

    def hook(event, **payload):
        data = dict({"session_id": "s1", "cwd": repo, "hook_event_name": event}, **payload)
        return ps(claude_code_fills(hooks[event], kit), env, cwd=repo, stdin=json.dumps(data))

    rc, out, err = hook("SessionStart", source="startup")
    try:
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    except ValueError:
        ctx = ""
    check("SessionStart: context with the Python line, the runner and the OS",
          rc == 0 and "[ekit] Python: " in ctx and "[ekit] Scenario runner: " in ctx and "os: Windows" in ctx,
          (rc, out, err))
    check("UserPromptSubmit: arms, silent", hook("UserPromptSubmit", prompt="/ekit:orchestrate-agent x")[:2] == (0, ""))
    rc, out, err = hook("PostToolUseFailure", tool_name="Bash", tool_input={"command": "jq .a x"},
                        error="bash: jq: command not found")
    check("PostToolUseFailure: a hint", rc == 0 and "jq missing" in out, (rc, out, err))
    task = {"task_id": "t1", "task_subject": "Unit", "task_description": "Verify: `git status`"}
    check("TaskCreated: never blocks", hook("TaskCreated", **task)[:2] == (0, ""))
    rc, out, err = hook("TaskCompleted", **task)
    check("TaskCompleted: exit 2, no run recorded, naming the run to do",
          rc == 2 and "no run recorded" in err and "task-verify.py\" run -- git status" in err,
          (rc, out, err))
    rc, out, err = hook("Stop", stop_hook_active=False)
    check("Stop: nothing changed → allowed", (rc, out) == (0, ""), (rc, out, err))


def hooks_in_git_bash(tmp):
    print("hooks: every hooks.json command in Git Bash, the plugin dir as Claude Code gives it there (/c/...)")
    kit = os.path.join(tmp, "gb", "O'Brien $HOME kit")
    os.makedirs(os.path.dirname(kit))
    shutil.copytree(os.path.join(tmp, "O'Brien $HOME kit"), kit)
    repo = os.path.join(tmp, "gbrepo")
    os.mkdir(repo)
    bash = shells.find("bash")
    git = git_root()
    env = {k: v for k, v in os.environ.items() if k not in ("EKIT_PY", "EKIT_SHELL")}
    env.update(PATH=os.pathsep.join([os.path.join(git, "usr", "bin"), os.path.join(git, "mingw64", "bin"),
                                     os.path.dirname(sys.executable), os.path.join(git, "cmd")]),
               EKIT_STATE=os.path.join(tmp, "gbstate"), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    unix = subprocess.run([bash, "-c", 'cygpath -u "$1"', "-", kit], capture_output=True, text=True,
                          env=env).stdout.strip()
    env["CLAUDE_PLUGIN_ROOT"] = unix
    check("the root is the /c/... form, a ' in it", unix.startswith("/") and "'" in unix, unix)
    for args in (["init", "-q"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)
    with open(os.path.join(kit, "hooks", "hooks.json")) as f:
        hooks = {e: g[0]["hooks"][0]["command"] for e, g in json.load(f)["hooks"].items()}

    def hook(event, **payload):
        data = dict({"session_id": "g1", "cwd": repo, "hook_event_name": event}, **payload)
        r = subprocess.run([bash, "-c", claude_code_fills(hooks[event], unix)], input=json.dumps(data).encode(),
                           capture_output=True, env=env, cwd=repo, timeout=300)
        return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")

    rc, out, err = hook("SessionStart", source="startup")
    check("SessionStart in Git Bash: context with the Python line", rc == 0 and "[ekit] Python: " in out, (rc, out, err))
    task = {"task_id": "t1", "task_subject": "Unit", "task_description": "Verify: `git status`"}
    rc, out, err = hook("TaskCompleted", **task)
    check("TaskCompleted in Git Bash: exit 2, no run recorded", rc == 2 and "no run recorded" in err, (rc, out, err))


def printed_paths_in_both_shells(tmp):
    print("printed paths: each form read the same in bash and in PowerShell")
    bash = shells.find("bash")
    echo = "import sys; print(sys.argv[1])"
    for path in ("C:/a/my kit/x.py", "C:/a/O'Brien kit/x.py", "C:/a/my $HOME `b kit/x.py"):
        arg = launcher.shown(path)
        rb = subprocess.run([bash, "-c", f"\"{sys.executable.replace(chr(92), '/')}\" -c '{echo}' {arg}"],
                            capture_output=True, text=True, env=shells.env_for(bash, "bash"))
        rc, out, err = ps(f"& '{sys.executable}' -c '{echo}' {arg}", dict(os.environ))
        check(f"{arg}: bash and PowerShell both read {path}",
              rb.stdout.strip() == path and out.strip() == path, (rb.stdout, rb.stderr, out, err))


def verify_shells(tmp):
    print("task-verify: each command re-run in the shell it was declared in")
    repo = os.path.join(tmp, "vrepo")
    os.mkdir(repo)
    env = {k: v for k, v in os.environ.items() if k not in ("EKIT_SHELL", "MSYSTEM", "SHELL")}
    env.update(EKIT_STATE=os.path.join(tmp, "vstate"), CLAUDE_CODE_SESSION_ID="s1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull)
    subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True, env=env)
    with open(os.path.join(repo, "a.txt"), "w") as f:
        f.write("a\n")
    tv, py, bash = os.path.join(SCRIPTS, "task-verify.py"), sys.executable, shells.find("bash")
    slash = lambda p: p.replace("\\", "/")  # noqa: E731 - bash reads a Windows path with / only

    def in_ps(verb, line):
        return ps(f"& '{py}' -I '{tv}' {verb} -- '{line}'", dict(env, PATH=bare_path()), cwd=repo)

    def in_bash(verb, line):
        r = subprocess.run([bash, "-c", f'"{slash(py)}" -I "{slash(tv)}" {verb} -- \'{line}\'; true'], env=env,
                           cwd=repo, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    name = shells._name(powershell())
    ps_line, sh_line = "git --version && git status", "test -f a.txt && grep -q a a.txt"
    in_ps("declare", ps_line)
    in_bash("declare", sh_line)
    rc, _, err = in_ps("run", sh_line)
    check("a bash line declared in Git Bash, run from PowerShell, runs in bash", f"exited 0 in bash" in err, err)
    _, _, err = in_bash("run", ps_line)
    check(f"a && line declared in PowerShell, run from Git Bash, runs in {name}", f"in {name}" in err, err)
    _, _, err = in_ps("run", "git -C no-such-dir status")
    check("a native exit code comes through PowerShell", "exited 128 in" in err, err)


def shells_for_real():
    print("shells: on this machine")
    bash = shells.find("bash")
    check("bash is Git Bash, never WSL's launcher", bool(bash) and shells._not_wsl(bash), bash)
    ask = "import sys; sys.path.insert(0, sys.argv[1]); import shells; print(shells.current()['name'])"
    env = {k: v for k, v in os.environ.items() if k != "EKIT_SHELL"}
    py, here = sys.executable.replace("\\", "/"), SCRIPTS.replace("\\", "/")
    r = subprocess.run([bash, "-c", f'"{py}" -c "{ask}" "{here}"; true'], capture_output=True, text=True, env=env)
    check("a Python started from bash finds bash", r.stdout.strip() == "bash", (r.stdout, r.stderr))
    rc, out, err = ps(f"& '{sys.executable}' -c \"{ask}\" '{SCRIPTS}'", env)
    check("a Python started from PowerShell finds PowerShell", out.strip() == shells._name(powershell()), (out, err))
    r = subprocess.run(shells.command(bash, "bash", "grep -q x <<< x && sed --version >/dev/null && exit 6"),
                       env=shells.env_for(bash, "bash", {"PATH": os.path.dirname(sys.executable)}))
    check("Git Bash finds its own tools whatever PATH it is given; the exit code comes through", r.returncode == 6,
          r.returncode)


def scenario_timeout(tmp):
    print("scenarios: a timeout with only Git's cmd dir on PATH")
    repo = os.path.join(tmp, "srepo")
    d = os.path.join(repo, ".ekit", "scenarios", "slow")
    os.makedirs(d)
    with open(os.path.join(d, "SCENARIO.md"), "w") as f:
        f.write("- story: s\n")
    with open(os.path.join(d, "run.sh"), "w", newline="\n") as f:
        f.write("(sleep 30; echo late) &\nsleep 30\n")
    env = dict(os.environ, PATH=bare_path(), EKIT_SCENARIO_TIMEOUT="2", EKIT_STATE=os.path.join(tmp, "sstate"),
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "s"]):
        subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)
    t0 = time.time()
    r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "scenarios.py"), "--repo", repo, "run"], env=env,
                       capture_output=True, text=True, timeout=120)
    took = time.time() - t0
    check("FAIL timeout, no traceback", "FAIL slow: timeout after 2s" in r.stdout and "Traceback" not in r.stderr,
          (r.stdout, r.stderr))
    check("the whole tree stopped in time (Git\\bin\\bash.exe starts the real shell: both in the job)", took < 20, took)


def scenario_run_py(tmp):
    print("scenarios: run.py in plain PowerShell, no bash on PATH")
    repo = os.path.join(tmp, "py'repo $x")  # a ' and a $: the run.ps1 path goes to PowerShell as one literal
    mark = os.path.join(tmp, "late-child")
    child = f"import time; time.sleep(6); open({mark!r}, 'w')"
    for sid, run_file, text in (
            ("a/pass", "run.py", "import os\nprint('hi')\n"
                                 "open(os.path.join(os.environ['EKIT_ARTIFACT_DIR'], 'shot.png'), 'w').write('png')\n"),
            ("a/fail", "run.py", "import sys\nsys.exit(3)\n"),
            ("a/ps", "run.ps1", "Write-Output 'from PowerShell'\nexit 0\n"),
            ("a/psfail", "run.ps1", "Write-Output 'the last native command fails, no exit'\ngit -C no-such-dir status\n"),
            ("slow", "run.py", f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {child!r}])\n"
                               "time.sleep(30)\n")):
        d = os.path.join(repo, ".ekit", "scenarios", *sid.split("/"))
        os.makedirs(d)
        for name, body in (("SCENARIO.md", "- story: s\n"), (run_file, text)):
            with open(os.path.join(d, name), "w", newline="\n") as f:
                f.write(body)
    env = {k: v for k, v in os.environ.items() if k not in ("EKIT_SCENARIO_TIMEOUT", "MSYSTEM", "SHELL")}
    env.update(PATH=bare_path(), EKIT_STATE=os.path.join(tmp, "pystate"), GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "s"]):
        subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)
    found = shutil.which("bash", path=env["PATH"])
    check("no Git Bash on PATH", found is None or "system32" in found.lower(), found)
    run = (f"& {shells.ps_literal(sys.executable)} -I {shells.ps_literal(os.path.join(SCRIPTS, 'scenarios.py'))} "
           f"--repo {shells.ps_literal(repo)} run")
    rc, out, err = ps(run + " a", env)
    check("a run.py passes, a run.py fails with its exit code, a run.ps1 runs in PowerShell",
          rc == 1 and "PASS a/pass" in out and "FAIL a/fail: exit 3" in out and "PASS a/ps" in out
          and "FAIL: 2/4 scenarios" in out and "Traceback" not in err, (rc, out, err))
    check("a run.ps1 whose last native command fails is a FAIL with that exit code (not -File's 0)",
          "FAIL a/psfail: exit 128" in out, (rc, out, err))
    t0 = time.time()
    rc, out, err = ps(run + " slow", dict(env, EKIT_SCENARIO_TIMEOUT="2"))
    took = time.time() - t0
    check("a run.py timeout is a FAIL, in time", rc == 1 and "FAIL slow: timeout after 2s" in out and took < 30,
          (rc, out, err, took))
    time.sleep(8)
    check("the run.py's background child was stopped with it", not os.path.exists(mark), mark)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # → in a check's name, on a pipe read as cp1252
    if os.name != "nt":
        print("windows-smoke: not Windows, nothing to check")
        return 0
    if not powershell():
        print("  FAIL no PowerShell on this Windows machine")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        tmp = os.path.realpath(tmp)
        launcher_in_powershell(tmp)
        hooks_in_plain_powershell(tmp)
        hooks_in_git_bash(tmp)
        printed_paths_in_both_shells(tmp)
        verify_shells(tmp)
        shells_for_real()
        scenario_timeout(tmp)
        scenario_run_py(tmp)
    print(f"windows-smoke: {'FAIL ' + str(len(FAILS)) if FAILS else 'ALL PASS'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
