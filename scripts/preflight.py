"""Environment preflight: the OS, then one line per problem with its fallback and, for a missing tool, the install
line for this OS (brew on macOS, winget on Windows, apt on Linux). Checks are gated on project markers.

Usage: preflight.py [--quiet] [dir]   (--quiet: the OS line and the problems only)
       preflight.py --env             the finish report's Env line, from what this process can do right now, and the
                                      shell it was run from
"""
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I drops the script dir from sys.path

import launcher  # noqa: E402 - the sys.path line above has to run first
import shells  # noqa: E402 - imported after the sys.path line above, like the one before it

# tool: (macOS, Windows, Linux) install line
INSTALL = {
    "python": ("brew install python", "winget install Python.Python.3.13", "sudo apt install python3"),
    "jq": ("brew install jq", "winget install jqlang.jq", "sudo apt install jq"),
    "rg": ("brew install ripgrep", "winget install BurntSushi.ripgrep.MSVC", "sudo apt install ripgrep"),
    "cargo": ("brew install rustup", "winget install Rustlang.Rustup", "sudo apt install cargo"),
    "node": ("brew install node", "winget install OpenJS.NodeJS.LTS", "sudo apt install nodejs"),
    "docker": ("brew install --cask docker", "winget install Docker.DockerDesktop", "sudo apt install docker.io"),
    "tmux": ("brew install tmux", "none on Windows (WSL: sudo apt install tmux)", "sudo apt install tmux"),
    "expect": ("brew install expect", "none on Windows (WSL: sudo apt install expect)", "sudo apt install expect"),
    "curl": ("brew install curl", "winget install cURL.cURL", "sudo apt install curl"),
    "gh": ("brew install gh", "winget install GitHub.cli", "sudo apt install gh"),
}
GATE = re.compile(r"^\[project\]|^\[tool\.poetry|^\[tool\.uv|^\[build-system\]", re.M)
NOREPLY = "@users.noreply.github.com"


def platform():
    """sys.platform: a seam, so a test can ask for another OS's lines without changing sys for everything else."""
    return sys.platform


def os_name(platform=None):
    platform = platform or globals()["platform"]()
    return "macOS" if platform == "darwin" else "Windows" if platform.startswith("win") else "Linux"


def install(tool, platform=None):
    name = os_name(platform)
    return INSTALL[tool][("macOS", "Windows", "Linux").index(name)]


def have(tool):
    return shutil.which(tool) is not None


def bounded(argv, secs=5):
    """(exit code, stderr) of argv stopped after `secs` with its whole tree; (None, why) when it cannot start."""
    with tempfile.TemporaryFile() as err:  # a file, not a pipe: a child the stop misses holds nothing open
        try:
            p = shells.spawn(argv, stdout=subprocess.DEVNULL, stderr=err, stdin=subprocess.DEVNULL)
        except OSError as e:
            return None, str(e)
        try:
            p.wait(timeout=secs)
            err.seek(0)
            return p.returncode, err.read().decode(errors="replace")
        except subprocess.TimeoutExpired:
            shells.kill_tree(p)
            return 124, f"no answer in {secs}s"
        finally:
            shells.finish(p)


def read(path):
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def loopback():
    try:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", 0))
        finally:
            s.close()
        return True
    except OSError:
        return False


def env_line():
    """`Env: unsandboxed; shell: <name>`, or `Env: sandboxed (<signs>); shell: <name>`: a sandboxed command writes
    only inside the project and the temp dir, and often cannot bind a port. Probed, never assumed: the kit's own
    cache dir stands for "outside the project" (a file made and removed)."""
    signs = []
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "ekit")
    try:
        os.makedirs(cache, exist_ok=True)
        fd, probe = tempfile.mkstemp(dir=cache, prefix="env.")
        os.close(fd)
        os.remove(probe)
    except OSError:
        signs.append("no write outside the project")
    if not loopback():
        signs.append("loopback bind blocked")
    state = f"sandboxed ({', '.join(signs)})" if signs else "unsandboxed"
    return f"Env: {state}; shell: {shells.current()['name']}"


def scenario_files(d):
    """The scenario scripts (SCENARIO.md prose does not count)."""
    for rel in (".ekit/scenarios", ".ek/scenarios"):
        base = os.path.join(d, rel)
        if os.path.isdir(base):
            return [os.path.join(dp, n) for dp, _, ns in os.walk(base) for n in ns if not n.endswith(".md")]
    return []


def runs(files, tool):
    """True when a scenario script runs `tool`: the word in command position (line start, after ; | & ( ` or a
    shell keyword), so the word in a string or in another language's code is not a use."""
    pat = re.compile(r"(^|[;|&(`]|(^|\s)(if|while|until|then|do|else|exec|!))\s*" + re.escape(tool) + r"(\s|$)", re.M)
    return any(pat.search(read(f)) for f in files)


def uses(files, word):
    pat = re.compile(r"\b" + re.escape(word) + r"\b")
    return any(pat.search(read(f)) for f in files)


def checks(d, quiet=False):
    """The report's lines for the project at `d`."""
    lines = [f"os: {os_name()}"]

    def warn(msg):
        lines.append(f"⚠ {msg}")

    def good(name):
        if not quiet:
            lines.append(f"ok {name}")

    def missing(tool, rest):
        warn(f"{tool}: missing → {rest}; install: {install(tool)}")

    py = launcher.command()

    if launcher.version_of(["python"]):
        good("python")
    elif launcher.pick():  # a Python 3.9+ is here (this one): bare `python` is only a name to avoid
        warn(f"python: missing → use {py}")
    else:
        missing("python", f"use {py}")
    good("jq") if have("jq") else missing("jq", f"{py} -c 'import json'")
    good("rg") if have("rg") else missing("rg", "grep -rn / find")

    if os.path.isfile(os.path.join(d, "requirements.txt")) or GATE.search(read(os.path.join(d, "pyproject.toml"))):
        good("venv") if os.path.isdir(os.path.join(d, ".venv")) else warn(
            "venv: no .venv → uv sync, then uv run <cmd> (or python3 -m venv .venv)")

    if os.path.isfile(os.path.join(d, "Cargo.toml")):
        good("cargo") if have("cargo") else missing("cargo", "Cargo.toml present; rust build/test can't run here")

    m = re.search(r'"node"\s*:\s*"([^"]*)"', read(os.path.join(d, "package.json")))
    if m:
        want = m.group(1)
        if not have("node"):
            missing("node", f"engines {want}")
        else:
            try:
                v = subprocess.run([shutil.which("node"), "-v"], capture_output=True, text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                v = ""
            need, got = re.search(r"\d+", want), re.search(r"\d+", v)
            if need and got and int(got.group()) < int(need.group()):
                warn(f"node: {v} < engines {want} → nvm use {need.group()}")
            else:
                good("node")

    if glob.glob(os.path.join(d, "Dockerfile")) or glob.glob(os.path.join(d, "*compose*.y*ml")):
        if not have("docker"):
            missing("docker", "container tests → verification debt")
        else:
            rc, err = bounded([shutil.which("docker"), "ps"])
            if rc == 0:
                good("docker")
            else:
                warn(f"docker: unusable ({err.strip()[:80]}) → container tests → verification debt")

    files = scenario_files(d)
    for t in ("tmux", "expect", "curl"):
        if runs(files, t):
            good(t) if have(t) else missing(t, f"scenarios needing {t} can't run here → human verdict / verification debt")

    if uses(files, "playwright") or any("playwright" in read(os.path.join(d, f))
                                        for f in ("package.json", "pyproject.toml", "requirements.txt")):
        home = os.path.expanduser("~")
        caches = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), os.path.join(home, ".cache", "ms-playwright"),
                  os.path.join(home, "Library", "Caches", "ms-playwright"),
                  os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local"), "ms-playwright")]
        chrome = os.environ.get("CHROME_BIN")
        found = bool(chrome and os.access(chrome, os.X_OK)) or any(c and glob.glob(os.path.join(c, "chromium*"))
                                                                   for c in caches)
        good("playwright") if found else warn(
            "playwright: no chromium in the ms-playwright cache or $CHROME_BIN → npx playwright install chromium")

    if have("gh"):
        good("gh") if bounded([shutil.which("gh"), "auth", "status"])[0] == 0 else warn(
            "gh: not authed → user runs: ! gh auth login")
        if not quiet:
            lines.append("note gh issue view: always pass --json (plain output errors on Projects classic)")

    gd = os.path.join(d, ".git")
    if os.path.isdir(gd):
        good("git") if os.access(gd, os.W_OK) else warn("git: .git read-only (sandbox) → commits need unsandboxed run")
    if have("git") and gh_remote(d):
        email = git_out(d, "config", "user.email")
        if email and not email.lower().endswith(NOREPLY):  # never printed: it is the user's private address
            warn("git: user.email is not a GitHub noreply address → GitHub may reject the push (email privacy); "
                 f"set: git config user.email <id>+<login>{NOREPLY}")

    good("loopback") if loopback() else warn(
        "loopback: bind 127.0.0.1 blocked (sandbox) → server/e2e tests need unsandboxed run")
    return lines


def git_out(d, *args):
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def gh_remote(d):
    return "github.com" in git_out(d, "remote", "-v")


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ["--env"]:
        print(env_line())
        return 0
    quiet = a[:1] == ["--quiet"]
    if quiet:
        a = a[1:]
    print("\n".join(checks(os.path.abspath(a[0]) if a else os.getcwd(), quiet)))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # ⚠ and → on a Windows console's code page
    sys.exit(main())
