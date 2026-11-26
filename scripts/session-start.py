"""SessionStart hook: record the tree baseline for the finish gate, inject preflight warnings and the kit's always-on rules
(the finish gate and taste-it are orchestrate-only), the stack plan's drift (#57) and the session's default verify
commands (#61). Every command it prints starts the Python the hook found."""
import contextlib
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I drops the script dir from sys.path

import launcher  # noqa: E402 - the sys.path line above has to run first
import preflight  # noqa: E402 - imported after the sys.path line above, like the one before it
from mech_review import adapter_file, gitio, stack_plan  # noqa: E402 - imported after the sys.path line above, like the ones before it

RULES = """[ekit] Working rules:
- A test or check goes red → classify it with the failure-triage skill before editing code.
- Same blocker 3× (missing tool, auth, approval denied, quota) → stop retrying; tell the user exactly what's needed.
- A denied or blocked command stays blocked: ask the user, keeping the exact command. Usage limit hit → stop."""

FIX = "edit it with the ci-doctor skill"
MAX_ITEMS = 20  # manifests and messages shown; the rest is a count and the command that lists them
MAX_TEXT = 500  # characters of one repo-controlled value
SHALLOW = "; in this shallow clone the days retiring count only the history here"
DRIFT_SECONDS = 3  # the drift check's share of the hook (it takes ~0.1 s): past it, one line, the context still goes
VERIFY = os.path.join(HERE, "task-verify.py")
DEFAULTS = "[ekit] Verify defaults"  # every line of the default verify commands (#61) starts so
STEPS = ("build", "lint", "test")  # the verify steps; install is setup, never a verify command


def shown(text):
    """repo- or PR-controlled text (a path, a plan value) as printable text: every character that is not printable
    (newline, CR, other C0 and C1 controls, DEL, line separators) escaped, so it can never start a session line."""
    out = "".join(c if c.isprintable() else repr(c)[1:-1] for c in str(text))  # "\n" -> \n, "\u2028" -> \u2028
    return out if len(out) <= MAX_TEXT else f"{out[:MAX_TEXT]}… (cut: {len(out)} characters)"


def has_tomllib():
    try:
        import tomllib  # noqa: F401 - only whether it imports
    except ImportError:
        return False
    return True


def drift(cwd):
    """The `[ekit]` lines for the stack plan's drift (#57): the committed tree at HEAD of the repo holding cwd against
    the plan at HEAD, what CI's drift check reads. Git only: no test runner, no network. Nothing when cwd is in no git
    repo, the repo has no commit, there is no plan, or it is clean; any other failure is one line, never a clean read."""
    git_env()
    out = []
    worker = threading.Thread(target=lambda: out.append(_guarded(cwd)), daemon=True)  # left behind on overrun
    worker.start()
    worker.join(DRIFT_SECONDS)
    if not out:
        return [f"[ekit] Stack plan: the drift check did not finish in {DRIFT_SECONDS} s here, so nothing here says what "
                f"is unchecked; CI still runs it on every PR."]
    return out[0]


def git_env():
    """the hook's git calls: a missing object is an error, never a fetch (git 2.44+; older: partial_clone), and git's
    own words unlocalized ("not a git repository" is read)."""
    os.environ["GIT_NO_LAZY_FETCH"] = "1"
    os.environ.update(LC_ALL="C", LANGUAGE="")


def _guarded(cwd):
    try:
        return _drift(cwd)
    except FileNotFoundError:
        return ["[ekit] Stack plan: git is not on PATH, so the drift check cannot run here; CI still runs it on every PR."]
    except Exception as e:  # noqa: BLE001 - a git error or a bug here must not fail the hook or read as clean
        return [f"[ekit] Stack plan: the drift check could not run here ({type(e).__name__}: {shown(e)}); CI still "
                f"runs it on every PR."]


def partial_clone(top):
    """the repo has a promisor remote: git fetches any object it lacks from there (a lazy fetch, a network call)."""
    try:
        keys = gitio.git(top, "config", "--name-only", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$")
    except gitio.Die:  # exit 1: no such key
        return False
    for key in keys.splitlines():  # one key a line: a remote name may hold a space
        if key == "extensions.partialclone" or gitio.git(top, "config", "--bool", "--get", key).strip() == "true":
            return True  # a promisor set to 0, no, off or false is none: git reads the value as a boolean
    return False


def _drift(cwd):
    try:
        top = gitio.git(cwd, "rev-parse", "--show-toplevel").strip()
    except gitio.Die as e:
        if "not a git repository (or any" in str(e):  # git's search found none (a ceiling, a filesystem boundary too)
            return []
        raise
    try:
        gitio.resolve(top, "HEAD")
    except gitio.Die:  # no commit yet: no committed plan to read
        return []
    if partial_clone(top):
        return ["[ekit] Stack plan: the drift check is skipped here: this is a partial clone, where git would fetch the "
                "objects it lacks (a network call); CI still runs it on every PR."]
    try:
        d = stack_plan.drift_at(top, "HEAD")
    except stack_plan.PlanError as e:
        if not has_tomllib():
            v = sys.version_info
            return [f"[ekit] Stack plan: the drift check at session start needs python 3.11 or newer (tomllib), this "
                    f"is {v[0]}.{v[1]}: nothing here says what is unchecked. CI still runs the drift check on every PR."]
        return [f"[ekit] Stack plan does not read, so nothing here says what is unchecked: {shown(e)}. Fix it "
                f"({FIX}); CI's drift check stops on it too."]
    if not d.has_plan and gitio.git(top, "ls-tree", "HEAD", stack_plan.PATH):  # listed, yet drift_at read none
        return [f"[ekit] Stack plan: {stack_plan.PATH} is in HEAD's tree but cannot be read as a file (a missing "
                f"object in a partial or broken clone, or not a file), so nothing here says what is unchecked; CI still "
                f"runs it on every PR."]
    if not d.uncovered and not d.messages:
        return []
    items = [f"- unchecked manifest {shown(p)}: no [[stack]] entry covers it, so mech-review checks nothing there; add "
             f"an entry (its folder, an adapter that lists the manifest) or its folder to `ignore`" for p in d.uncovered]
    items += [f"- {shown(m)}" for m in d.messages]
    if gitio.git(top, "rev-parse", "--is-shallow-repository").strip() == "true":  # the history is cut
        items = [i + SHALLOW if i.startswith("- retiring ") else i for i in items]
    if len(items) > MAX_ITEMS:
        # the kit's own path and fixed words, no repo-controlled text: printed whole, never cut
        cmd = launcher.line(os.path.join(HERE, "mech-review.py"), "drift --repo . --base HEAD --head HEAD --format text")
        items[MAX_ITEMS:] = [f"- and {len(items) - MAX_ITEMS} more: in the repo root, run `{cmd}`"]
    return [f"[ekit] Stack plan drift at HEAD ({stack_plan.PATH}; {FIX}):", *items]


def stack_commands(top, stack):
    """{step: command} of the commands CI runs for a stack (#61): build and lint from an adapter file's [commands] (a
    built-in has none); test as R1 and R4 run it (test_cmd_in on the checkout: an adapter file's [run] runners, a
    built-in's), an adapter file with no [run] its [commands].test. Each trimmed; a step with no command is left out."""
    a = stack.adapter
    got = {k: a.commands.get(k, "") for k in STEPS} if hasattr(a, "commands") else {}
    if getattr(a, "run", True) is not None:  # a built-in has no [run] attribute: it always runs its tests
        got["test"] = a.test_cmd_in(os.path.join(top, *stack.folder.split("/")))
    return {k: v.strip() for k, v in got.items() if v.strip()}  # whitespace at its ends runs as none: trimmed


def in_folder(folder, cmd):
    """the command run in the stack's folder: `cd <folder> && <cmd>` (a folder led by `-` as `./-x`, a path to cd, not
    an option), plain at the repo root"""
    if folder == ".":
        return cmd
    return f"cd {shlex.quote('./' + folder if folder.startswith('-') else folder)} && {cmd}"


def _listed(words, last):
    """`a`, `a or b`, `a, b or c`"""
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} {last} {words[-1]}"


def _none(why):
    return [f"{DEFAULTS}: none declared: {why}."]


def _stacks(cwd):
    """(top, [stack_plan.Stack]) of the repo holding cwd at HEAD, resolved as CI resolves them; else [the one line
    saying why none is]."""
    if not has_tomllib():
        v = sys.version_info
        return _none(f"the default verify commands need python 3.11 or newer (tomllib), this is {v[0]}.{v[1]}; declare "
                     f"them per task with task-verify")
    try:
        try:
            top = gitio.git(cwd, "rev-parse", "--show-toplevel").strip()
        except gitio.Die as e:
            if "not a git repository (or any" in str(e):
                return _none(f"{shown(cwd)} is in no git repo")
            raise
        try:
            gitio.resolve(top, "HEAD")
        except gitio.Die:
            return _none("the repo has no commit yet")
        if partial_clone(top):
            return _none("this is a partial clone, where git would fetch the objects it lacks (a network call)")
        stacks, why = stack_plan.stacks_at(top, "HEAD")
    except stack_plan.PlanError as e:
        return _none(f"the stack plan does not read: {shown(e)}")
    except adapter_file.AdapterFileError as e:
        return _none(shown(e))
    except FileNotFoundError:
        return _none("git is not on PATH")
    except Exception as e:  # noqa: BLE001 - a git error or a bug here must not fail the hook
        return _none(f"the stacks could not be resolved here ({type(e).__name__}: {shown(e)})")
    return _none(shown(why)) if why else (top, stacks)


def _task_verify():
    spec = importlib.util.spec_from_file_location("ekit_task_verify", VERIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def declare(top, stacks, session):
    """Declare each stack's commands as the session's verify commands, through task-verify's own code (the same
    string `run` and the Stop gate match); the context lines that name what the store then holds, each step a stack has
    no command for, and each it has one that task-verify would change."""
    if not session:
        return _none("the hook got no session_id")
    tv = _task_verify()
    named, notes = {}, []  # named: {command: {its stack: [its steps]}}, in the order first met
    for st in stacks:
        cmds = stack_commands(top, st)
        where = "at the repo root" if st.folder == "." else f"in {st.folder}"
        kind = "" if st.adapter.name == st.name else f"{shown(st.adapter.name)}, "  # no plan: the name is the adapter's
        about = f"stack `{shown(st.name)}` ({kind}{shown(where)})"
        gap = [k for k in STEPS if k not in cmds]
        if gap:
            notes.append(f"{DEFAULTS}: {about} names no {_listed(gap, 'or')} command, so none is declared for "
                         f"{'that step' if len(gap) == 1 else 'those steps'}.")
        spaced = []
        for k in STEPS:
            if k not in cmds:
                continue
            cmd = in_folder(st.folder, cmds[k])
            if tv.spelled([cmd]) != cmd:  # task-verify collapses whitespace: what it keeps would run elsewhere
                spaced.append(k)
                continue
            named.setdefault(cmd, {}).setdefault(about, []).append(k)
        if spaced:
            notes.append(f"{DEFAULTS}: {about}: {_listed(spaced, 'and')} not declared: its folder or command holds a "
                         f"run of whitespace that task-verify collapses; declare it per task.")
    error = None
    try:
        with contextlib.redirect_stderr(io.StringIO()):  # its own `is a verify command` line: the context says it
            for cmd in named:
                tv.cmd_declare(top, [cmd], session)
    except OSError as e:
        error = f"task-verify's store cannot be written ({shown(e.filename)}: {shown(e.strerror)})"
    held = set(tv.commands(top, session))  # what the store holds, read back: the context says no more than that
    done = [cmd for cmd in named if cmd in held]
    run = launcher.line(VERIFY, "--repo", launcher.shown(top), "run", "--")
    lines = [f"{DEFAULTS} (#61): this session's verify commands, from the stacks at HEAD; run each as shown before "
             f"calling the work done (the Stop gate checks them). Declare more per task as before."] if done else []
    for cmd in done:
        serves = "; ".join(f"{_listed(steps, 'and')} of {about}" for about, steps in named[cmd].items())
        lines.append(f"{DEFAULTS}: `{shown(cmd)}` ({serves}): `{run} {shown(shlex.quote(cmd))}`")
    if error:
        lines += _none(error) if not done else [f"{DEFAULTS}: {len(done)} of {len(named)} declared: {error}."]
    return lines + notes


def defaults(cwd, session):
    """The `[ekit] Verify defaults` lines (#61), within the drift check's deadline: the stacks resolve on a worker,
    git only; past the deadline nothing is declared. The declaring itself runs here, so none lands after the line."""
    git_env()
    out = []
    worker = threading.Thread(target=lambda: out.append(_stacks(cwd)), daemon=True)
    worker.start()
    return lambda deadline: _settled(worker, out, deadline, session)


def _settled(worker, out, deadline, session):
    worker.join(max(0, deadline - time.monotonic()))
    if not out:
        return _none(f"resolving the stacks did not finish in {DRIFT_SECONDS} s here")
    got = out[0]
    if isinstance(got, list):
        return got
    try:
        return declare(*got, session)
    except Exception as e:  # noqa: BLE001 - a bug in declaring must not fail the hook
        return _none(f"declaring them failed here ({type(e).__name__}: {shown(e)})")


def main():
    raw = sys.stdin.read()
    data = json.loads(raw or "{}")
    cwd = data.get("cwd") or os.getcwd()
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "finish-gate.py"), "--baseline"], input=raw, text=True)
    pf = "\n".join(preflight.checks(cwd, quiet=True))
    deadline = time.monotonic() + DRIFT_SECONDS  # the drift check's and the stacks' alike: they run side by side
    verify = defaults(cwd, data.get("session_id"))
    ctx = "\n".join([RULES, f"[ekit] Python: {launcher.command()}",
                     f"[ekit] Scenario runner: {launcher.line(os.path.join(HERE, 'scenarios.py'))}",
                     f"[ekit] Preflight (this env):\n{pf}", *drift(cwd), *verify(deadline)])
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}))


if __name__ == "__main__":
    main()
