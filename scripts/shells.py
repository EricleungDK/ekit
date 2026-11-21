"""Shells on any OS: which shell started this process, where a named shell is, how to run a command line with it,
and how to stop a process tree.

The agent's commands may run in bash, zsh or sh (macOS, Linux, Git Bash on Windows) or in PowerShell (Windows without
Git Bash), so a command line means what its shell makes of it. `current()` names the shell this process was started
from: EKIT_SHELL when set (a name, or a path to the shell), else the nearest shell among this process's ancestors,
else a guess from the environment. `find()` resolves a name to an executable on this machine; on Windows `bash` is
Git for Windows' bash, never the WSL launcher in System32, which cannot run a Windows path.
"""
import os
import shutil
import signal
import subprocess
import sys

WIN = os.name == "nt"
POSIX_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")  # each takes `-c LINE`
PS_SHELLS = ("pwsh", "powershell")
KNOWN = POSIX_SHELLS + PS_SHELLS + ("cmd",)
# PowerShell's -Command exits 1 for any failing native command: the command's own code is kept
PS_EXIT = "\nif (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE } else { exit 1 } }"


def _name(path):
    base = os.path.basename(path or "").lower()
    return base[:-4] if base.endswith(".exe") else base


def _ancestors_windows():
    """(exe name, full path or None) of each ancestor, nearest first."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    procs = {}
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            procs[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)

    def full(pid):
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
        finally:
            k32.CloseHandle(h)

    out, pid, seen = [], os.getpid(), set()
    while pid in procs and pid not in seen and len(out) < 12:
        seen.add(pid)
        pid = procs[pid][0]
        if pid not in procs:
            break
        out.append((_name(procs[pid][1]), full(pid)))
    return out


def _ancestors_posix():
    out, pid = [], os.getppid()
    for _ in range(12):
        if pid <= 1:
            break
        exe = None
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
            with open(f"/proc/{pid}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            try:
                r = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True)
                ppid_s, comm = r.stdout.strip().split(None, 1)
                ppid, exe = int(ppid_s), comm.strip().lstrip("-")
            except (OSError, ValueError):
                break
        out.append((_name(exe), exe if exe and os.path.isabs(exe) else None))
        pid = ppid
    return out


def ancestors():
    try:
        return _ancestors_windows() if WIN else _ancestors_posix()
    except Exception:  # noqa: BLE001 - an OS that will not say: the environment guess below
        return []


def current():
    """{"name", "exe"} of the shell this process was started from (exe None when not known)."""
    forced = os.environ.get("EKIT_SHELL")
    if forced:
        return {"name": _name(forced), "exe": forced if os.path.isabs(forced) else None}
    for name, exe in ancestors():
        if name in KNOWN:
            return {"name": name, "exe": exe}
    if WIN:
        return {"name": "bash" if os.environ.get("MSYSTEM") else "powershell", "exe": None}
    login = _name(os.environ.get("SHELL"))
    return {"name": login if login in POSIX_SHELLS else "sh", "exe": None}


def _not_wsl(path):
    low = os.path.normcase(path or "")
    return bool(path) and "\\system32\\" not in low and "\\windowsapps\\" not in low


def git_bash():
    """Git for Windows' bash.exe: CLAUDE_CODE_GIT_BASH_PATH, bash on PATH (not WSL's), or beside git.exe."""
    for p in (os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), shutil.which("bash")):
        if p and os.path.isfile(p) and _not_wsl(p):
            return p
    git = shutil.which("git")
    if git:
        d = os.path.dirname(os.path.realpath(git))
        for up in (os.path.dirname(d), os.path.dirname(os.path.dirname(d))):  # <git>\cmd, <git>\mingw64\bin
            for rel in (("bin", "bash.exe"), ("usr", "bin", "bash.exe")):
                p = os.path.join(up, *rel)
                if os.path.isfile(p):
                    return p
    return None


def find(shell):
    """The executable for `shell` ({"name", "exe"} or a name) on this machine; None when there is none."""
    if isinstance(shell, str):
        shell = {"name": shell, "exe": None}
    exe, name = shell.get("exe"), shell.get("name")
    if exe and os.path.isfile(exe):
        return exe
    if WIN and name in ("bash", "sh"):
        bash = git_bash()
        if bash and name == "sh":
            sh = os.path.join(os.path.dirname(bash), "sh.exe")
            return sh if os.path.isfile(sh) else bash
        return bash
    if WIN and name == "cmd":
        return os.environ.get("ComSpec") or shutil.which("cmd")
    if WIN and name == "powershell":
        p = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                         "powershell.exe")
        return shutil.which("powershell") or (p if os.path.isfile(p) else None)
    return shutil.which(name) if name in KNOWN else None


def command(exe, name, line):
    """argv (or, for cmd.exe, the command string) that runs `line` with the shell `name` at `exe`."""
    if name in PS_SHELLS:
        return [exe, "-NoProfile", "-NonInteractive", "-Command", line + PS_EXIT]
    if name == "cmd":
        return f'"{exe}" /d /s /c "{line}"'
    return [exe, "-c", line]


def group():
    """Popen kwargs that put the child in its own process group, so a timeout can stop the whole tree."""
    if WIN:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc):
    """Stop `proc` and its children: the process group on POSIX, `taskkill /T` on Windows."""
    if WIN:
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


if __name__ == "__main__":
    print(current()["name"])
    sys.exit(0)
