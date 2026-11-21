"""Shells on any OS: which shell started this process, where a named shell is, how to run a command line with it,
and how to stop a process tree.

The agent's commands may run in bash, zsh or sh (macOS, Linux, Git Bash on Windows) or in PowerShell (Windows without
Git Bash), so a command line means what its shell makes of it. `current()` names the shell this process was started
from: EKIT_SHELL when set (a name, or a path to the shell), else the nearest shell among this process's ancestors,
else a guess from the environment. `find()` resolves a name to an executable on this machine; on Windows `bash` is
Git for Windows' bash, never the WSL launcher in System32, which cannot run a Windows path.
"""
import ctypes
import os
import shutil
import signal
import subprocess
import sys

WIN = os.name == "nt"
if WIN:
    from ctypes import wintypes

    K32 = ctypes.WinDLL("kernel32", use_last_error=True)
    NTDLL = ctypes.WinDLL("ntdll")
    for _f in ("CreateToolhelp32Snapshot", "OpenProcess", "CreateJobObjectW"):
        getattr(K32, _f).restype = wintypes.HANDLE
POSIX_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")  # each takes `-c LINE`
PS_SHELLS = ("pwsh", "powershell")
KNOWN = POSIX_SHELLS + PS_SHELLS + ("cmd",)
# PowerShell's -Command exits 1 for any failing native command: the command's own code is kept
PS_EXIT = "\nif (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE } else { exit 1 } }"


def _name(path):
    base = os.path.basename(path or "").lower()
    return base[:-4] if base.endswith(".exe") else base


def chain(table, pid, steps=12):
    """[(exe name, pid)] of the ancestors of `pid` in `table` ({pid: (parent pid, exe file name)}), nearest first:
    the walk stops at a parent the table lacks, at a pid seen before, or after `steps`."""
    out, seen = [], {pid}
    while pid in table and len(out) < steps:
        pid = table[pid][0]
        if pid not in table or pid in seen:
            break
        seen.add(pid)
        out.append((_name(table[pid][1]), pid))
    return out


def _process_table():
    """{pid: (parent pid, exe file name)} of every process (Windows: a toolhelp snapshot)."""
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    snap = K32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    table = {}
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = K32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(e))
        while ok:
            table[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
            ok = K32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(e))
    finally:
        K32.CloseHandle(wintypes.HANDLE(snap))
    return table


def _image(pid):
    """The full path of process `pid`'s executable (Windows); None when it cannot be read."""
    h = K32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        return buf.value if K32.QueryFullProcessImageNameW(wintypes.HANDLE(h), 0, buf, ctypes.byref(size)) else None
    finally:
        K32.CloseHandle(wintypes.HANDLE(h))


def _ancestors_windows():
    """(exe name, full path or None) of each ancestor, nearest first."""
    return [(name, _image(pid)) for name, pid in chain(_process_table(), os.getpid())]


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
    """{"name", "exe"} of the shell this process was started from (exe None when not known). cmd.exe counts only
    when no other shell is above it: a .bat or .cmd shim (pyenv-win, npm scripts) starts Python through cmd.exe from
    the shell the command was given in."""
    forced = os.environ.get("EKIT_SHELL")
    if forced:
        return {"name": _name(forced), "exe": forced if os.path.isabs(forced) else None}
    up = [(name, exe) for name, exe in ancestors() if name in KNOWN]
    for name, exe in [x for x in up if x[0] != "cmd"] + up:
        return {"name": name, "exe": exe}
    if WIN:
        return {"name": "bash" if os.environ.get("MSYSTEM") else "powershell", "exe": None}
    login = _name(os.environ.get("SHELL"))
    return {"name": login if login in POSIX_SHELLS else "sh", "exe": None}


def _not_wsl(path):
    low = (path or "").replace("/", "\\").lower()  # a Windows path read the same on any OS
    return bool(path) and "\\system32\\" not in low and "\\windowsapps\\" not in low


def bash_candidates(env, which):
    """Where Git for Windows' bash may be, in order: CLAUDE_CODE_GIT_BASH_PATH, bash on PATH, then beside git.exe
    (<git>\\cmd or <git>\\mingw64\\bin): usr\\bin\\bash.exe, the shell itself, before bin\\bash.exe, a launcher that
    starts it."""
    out = [env.get("CLAUDE_CODE_GIT_BASH_PATH"), which("bash")]
    git = which("git")
    if git:
        d = os.path.dirname(os.path.realpath(git))
        for up in (os.path.dirname(d), os.path.dirname(os.path.dirname(d))):
            out += [os.path.join(up, "usr", "bin", "bash.exe"), os.path.join(up, "bin", "bash.exe")]
    return out


def pick_bash(candidates, isfile=os.path.isfile):
    """The first candidate that is a file and not WSL's launcher; None when none is."""
    return next((p for p in candidates if p and isfile(p) and _not_wsl(p)), None)


def git_bash():
    """Git for Windows' bash.exe on this machine, never WSL's launcher; None when there is none."""
    return pick_bash(bash_candidates(os.environ, shutil.which))


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


def env_for(exe, name, env=None):
    """The environment to run `exe` with: on Windows, Git Bash's own dirs go first on PATH (a Windows PATH holds
    neither usr/bin nor mingw64/bin, so a bash line would find no grep or sed); elsewhere `env` as it is."""
    env = dict(os.environ if env is None else env)
    if WIN and name in POSIX_SHELLS:
        d = os.path.dirname(exe)
        git = os.path.dirname(os.path.dirname(d)) if os.path.basename(os.path.dirname(d)).lower() == "usr" \
            else os.path.dirname(d)
        own = [os.path.join(git, "usr", "bin"), os.path.join(git, "mingw64", "bin")]
        env["PATH"] = os.pathsep.join(own + [env.get("PATH", "")])
    return env


def command(exe, name, line):
    """argv (or, for cmd.exe, the command string) that runs `line` with the shell `name` at `exe`."""
    if name in PS_SHELLS:
        return [exe, "-NoProfile", "-NonInteractive", "-Command", line + PS_EXIT]
    if name == "cmd":
        return f'"{exe}" /d /s /c "{line}"'
    return [exe, "-c", line]


CREATE_SUSPENDED = 0x4
KILL_ON_JOB_CLOSE = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: closing the job's last handle stops what is in it


def _job_for(pid):
    """A job object holding process `pid` (created suspended, so nothing it starts escapes), resumed: what it starts
    joins the job, so terminating the job stops the whole tree, even a child whose parent is gone (Git Bash's
    launcher and `exec` leave such). The handle is returned; None when the OS refused, the process resumed all the
    same."""
    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("Io", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    h = K32.OpenProcess(0x0800 | 0x0100 | 0x0001, False, pid)  # SUSPEND_RESUME | SET_QUOTA | TERMINATE
    job = K32.CreateJobObjectW(None, None)
    try:
        if job:
            info = Extended()
            info.Basic.LimitFlags = KILL_ON_JOB_CLOSE
            K32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        if not (job and h and K32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(h))):
            if job:
                K32.CloseHandle(wintypes.HANDLE(job))
            job = None
    finally:
        if h:
            NTDLL.NtResumeProcess(wintypes.HANDLE(h))
            K32.CloseHandle(wintypes.HANDLE(h))
    return job


def spawn(argv, **kw):
    """subprocess.Popen(argv) as a tree `kill_tree` can stop: its own process group on POSIX; on Windows a job,
    joined before the process runs. `finish` lets go of it."""
    if WIN:
        kw["creationflags"] = kw.get("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED
        proc = subprocess.Popen(argv, **kw)
        proc.ekit_job = _job_for(proc.pid)
        return proc
    return subprocess.Popen(argv, start_new_session=True, **kw)


def finish(proc):
    """Let go of `proc`'s job (Windows): what it left running stops with it. Nothing on POSIX."""
    job = getattr(proc, "ekit_job", None)
    if job:
        proc.ekit_job = None
        K32.CloseHandle(wintypes.HANDLE(job))


REAP = 10  # seconds to wait for the output of a stopped tree: a child that escaped it may hold the pipes


def reap(proc, secs=REAP):
    """(stdout, stderr) of a stopped `proc`, waited for at most `secs`: past that what was not read is given up
    (on Windows the readers are daemon threads; closing a pipe one of them holds would wait for it), so a child that
    escaped the stop cannot hold the caller."""
    try:
        return proc.communicate(timeout=secs)
    except subprocess.TimeoutExpired:
        return b"", b""


def kill_tree(proc):
    """Stop `proc` and its children: the process group on POSIX; on Windows the job, else `taskkill /T`."""
    if WIN:
        job = getattr(proc, "ekit_job", None)
        if job:
            K32.TerminateJobObject(wintypes.HANDLE(job), 1)
            finish(proc)
        else:
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
