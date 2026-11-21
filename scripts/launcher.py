"""The Python launcher: how the hooks and every command ekit prints start Python, on macOS, Windows and Linux.

It tries `python3`, then `py -3`, then `python`, and takes the first that is Python 3.9 or newer. None: one message.
`python3` comes first because it is the name on macOS and Linux; on Windows it is often the Microsoft Store stub,
which fails the version check, and python.org installs give `py` and `python`.

Hook commands (hooks/hooks.json, `hook_command`) do this in the shell before any Python runs. Claude Code runs a hook
command with `sh -c` on macOS and Linux, Git Bash on Windows, or PowerShell where Git Bash is not installed, so one
command string holds both: `set \\'` is a no-op in both shells, sh reads the sh loop and stops at `exit` (the rest is
its comment), PowerShell reads the sh loop as one quoted string and then runs its own loop. The chosen name goes to
the script as EKIT_PY, so a printed command names the Python the hook found.

`launcher.py` prints the name it picks, or the message with exit 1.
"""
import os
import re
import shutil
import subprocess
import sys

ORDER = ("python3", "py -3", "python")
NEED = (3, 9)
MESSAGE = ("[ekit] no Python 3.9+ found: tried python3, py -3, python. Install Python 3.9 or newer "
           "(python.org), then start a new session")
CHECK = "import sys; sys.exit(sys.version_info < (3, 9))"

SH = ('for p in python3 "py -3" python; do $p -c "{check}" 2>/dev/null && EKIT_PY="$p" exec $p -I "{script}"{args}; '
      'done; echo "{msg}" >&2; exit 1')
PS = ("foreach ($p in 'python3', 'py -3', 'python') {{ $w = -split $p; "
      "if (Get-Command $w[0] -CommandType Application -ErrorAction Ignore) {{ "
      "& $w[0] $w[1..9] -c '{check}' 2>$null; if ($LASTEXITCODE -eq 0) {{ $env:EKIT_PY = $p; "
      "& $w[0] $w[1..9] -I \"{script}\"{args}; exit $LASTEXITCODE }} }} }}; "
      "[Console]::Error.WriteLine('{msg}'); exit 1")


def hook_command(script, *args):
    """The hooks.json command that runs scripts/<script> with `args` under the first Python that works."""
    path = "${CLAUDE_PLUGIN_ROOT}/scripts/" + script
    tail = "".join(" " + a for a in args)
    fill = dict(check=CHECK, script=path, args=tail, msg=MESSAGE)
    return f"set \\' ; {SH.format(**fill)} # \\' ; {PS.format(**fill)}"


def version_of(words):
    """(major, minor) of the interpreter `words` starts; None when it is missing or does not run."""
    exe = shutil.which(words[0])  # the path: Windows starts a .cmd or .bat shim (pyenv-win) only by its full name
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *words[1:], "-c","import sys; print(*sys.version_info[:2])"], capture_output=True,
                           text=True, timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.fullmatch(r"(\d+) (\d+)", r.stdout.strip())
    return (int(m.group(1)), int(m.group(2))) if r.returncode == 0 and m else None


def pick(probe=None):
    """The first name in ORDER whose interpreter is 3.9+; None when none is."""
    probe = probe or version_of
    for name in ORDER:
        v = probe(name.split())
        if v and tuple(v[:2]) >= NEED:
            return name
    return None


def shown(path):
    """`path` as a command argument both bash and PowerShell read the same: forward slashes, quoted when needed."""
    if os.name == "nt":
        path = path.replace("\\", "/")
    return path if re.fullmatch(r"[\w./:@%+=,-]+", path) else f'"{path}"'


def command():
    """The Python a printed command starts: the hook's choice (EKIT_PY), else the pick, else this interpreter."""
    chosen = os.environ.get("EKIT_PY")
    if chosen in ORDER:
        return chosen
    return pick() or shown(sys.executable)


def line(script, *args):
    """A printed command that runs `script`: `<python> <path> <args>`."""
    return " ".join([command(), shown(script), *args])


def main(argv=None):
    name = pick()
    if not name:
        print(MESSAGE, file=sys.stderr)
        return 1
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
