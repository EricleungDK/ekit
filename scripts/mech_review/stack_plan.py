"""The stack plan (#56): `.ekit/stack-plan.toml`, the one committed file that lists a repo's stacks, and the drift check
that compares it with the repo's tracked manifests. Git only: no test runner, no network.

Format: docs/mech-review-ci.md#stack-plan. Top level: `ignore` (folders whose manifests are not projects) and one
`[[stack]]` table per stack: name, folder, adapter (a built-in name or an adapter file's repo path), status (planned,
current or retiring), target-os (optional; the adapter's applies when the entry names none).

A manifest (a file name some adapter in play lists: the built-ins' and the plan's adapter files') is covered when a
plan entry's folder holds it, at any depth, and the entry's adapter lists its name. Manifests under resolve.SKIP_DIRS
(fixture, vendor and build folders) or under an `ignore` folder do not count.

Every problem with a plan is a PlanError naming the entry and the field, never a silent default: a bad plan never reads
as clean. tomllib (python 3.11+) is imported only when a plan exists."""
import time
from collections import namedtuple

from . import adapter_file, gitio, report
from .resolve import SKIP_DIRS
from .stack import ADAPTERS

PATH = ".ekit/stack-plan.toml"
STATUSES = ("planned", "current", "retiring")
RETIRING_DAYS = 30  # spec default (#56): a stack retiring longer than this gets a reminder
DAY = 86400
ENTRY_KEYS = ("name", "folder", "adapter", "status", "target-os")

# adapter_ref: the plan's `adapter` value; adapter: the Adapter it names; target_os: the entry's, else its adapter's
Entry = namedtuple("Entry", "name folder adapter_ref adapter target_os status")
Plan = namedtuple("Plan", "entries ignore")
# has_plan: a plan exists where it was read; uncovered: manifest paths no entry covers; messages: lines for the user
Drift = namedtuple("Drift", "has_plan uncovered messages")


class PlanError(ValueError):
    """a plan that cannot be read or is invalid: a usage error (exit 2) naming the entry and the field."""


def _folder(v, where):
    """a folder under the repo root, `/`-separated: `./` parts and a trailing `/` dropped, `.` for the root."""
    if not isinstance(v, str) or not v:
        raise PlanError(f"{where}: want a folder, a non-empty string")
    if any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise PlanError(f"{where}: {v!r} holds a control character")
    if v.startswith("/") or "\\" in v or ".." in v.split("/"):
        raise PlanError(f"{where}: `{v}`: want a folder under the repo root, `/`-separated (no .., not absolute)")
    return "/".join(p for p in v.split("/") if p not in ("", ".")) or "."


def holds(folder, path):
    return folder == "." or path.startswith(folder + "/")


def _adapter(ref, where, read):
    """the Adapter a plan's `adapter` value names: a built-in, or the adapter file at that repo path (read(path) -> bytes
    or None when there is no such file)."""
    if not isinstance(ref, str) or not ref:
        raise PlanError(f"{where}: want a built-in stack ({', '.join(sorted(ADAPTERS))}) or an adapter file path")
    if ref in ADAPTERS:
        return ADAPTERS[ref]()
    path = _folder(ref, where)
    raw = read(path)
    if raw is None:
        raise PlanError(f"{where}: `{ref}` is not a built-in stack ({', '.join(sorted(ADAPTERS))}) and no file is there")
    try:
        a = adapter_file.loads(raw, path)
    except adapter_file.AdapterFileError as e:
        raise PlanError(f"{where}: {e}") from None
    if not a.manifests:
        raise PlanError(f"{where}: adapter file {path} lists no manifests: the plan cannot find its stack")
    return a


def parse(data, read):
    """the Plan a parsed plan file (a dict, as tomllib reads it) describes. read(path) -> bytes or None: an adapter file
    at the plan's ref."""
    if not isinstance(data, dict):
        raise PlanError("want a table")
    for k in data:
        if k not in ("ignore", "stack"):
            raise PlanError(f"{k}: unknown key (want ignore and [[stack]] tables)")
    ignore = data.get("ignore", [])
    if not isinstance(ignore, list):
        raise PlanError("ignore: want a list of folders")
    folders = []
    for i, v in enumerate(ignore):
        f = _folder(v, f"ignore[{i}]")
        if f == ".":
            raise PlanError(f"ignore[{i}]: `{v}` is the repo root: want a folder below it")
        folders.append(f)
    stacks = data.get("stack", [])
    if not isinstance(stacks, list):
        raise PlanError("stack: want an array of tables ([[stack]])")
    entries, names = [], {}
    for i, s in enumerate(stacks):
        label = f"stack[{i}]"
        if not isinstance(s, dict):
            raise PlanError(f"{label}: want a table")
        name = s.get("name")
        if isinstance(name, str) and name and all(ch.isalnum() or ch in "_-" for ch in name):
            label += f" `{name}`"
        for k in s:
            if k not in ENTRY_KEYS:
                raise PlanError(f"{label}, field {k}: unknown key")
        for k in ("name", "folder", "adapter", "status"):
            if k not in s:
                raise PlanError(f"{label}, field {k}: missing")
        if not isinstance(name, str) or not name or not all(ch.isalnum() or ch in "_-" for ch in name):
            raise PlanError(f"{label}, field name: want letters, digits, _ or -")
        if name in names:
            raise PlanError(f"{label}, field name: `{name}` is already {names[name]}")
        names[name] = f"stack[{i}]"
        folder = _folder(s["folder"], f"{label}, field folder")
        status = s["status"]
        if status not in STATUSES:
            raise PlanError(f"{label}, field status: `{status}`: want planned, current or retiring")
        adapter = _adapter(s["adapter"], f"{label}, field adapter", read)
        if "target-os" in s:
            try:
                target = adapter_file.target_os(s["target-os"], f"{label}, field target-os")
            except adapter_file.AdapterFileError as e:
                raise PlanError(str(e)) from None
        else:
            target = adapter.target_os
        entries.append(Entry(name, folder, s["adapter"], adapter, target, status))
    return Plan(entries, folders)


def _toml(raw, where):
    try:
        import tomllib
    except ImportError:
        raise PlanError(f"{where}: reading the stack plan needs python 3.11 or newer (tomllib)") from None
    try:
        return tomllib.loads((raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw).decode("utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise PlanError(f"{where}: not valid TOML: {e}") from None
    except UnicodeDecodeError as e:
        raise PlanError(f"{where}: not valid TOML: not UTF-8 ({e.reason} at byte {e.start})") from None
    except RecursionError:
        raise PlanError(f"{where}: not valid TOML: arrays or tables nested too deep") from None


def _blob(repo, sha, path):
    """the file's bytes at sha, or None when it is not a file there."""
    try:
        kind = gitio.git(repo, "cat-file", "-t", f"{sha}:{path}").strip()
    except gitio.Die:
        return None
    if kind != "blob":
        return None
    return gitio.blob(repo, sha, path).encode("utf-8", "surrogateescape")


def at(repo, ref):
    """the Plan at ref, or None when there is no plan file there. PlanError: unreadable or invalid (named)."""
    sha = gitio.resolve(repo, ref)
    raw = _blob(repo, sha, PATH)
    if raw is None:
        return None
    where = f"{PATH} at {sha[:12]}"
    try:
        return parse(_toml(raw, where), lambda p: _blob(repo, sha, p))
    except PlanError as e:
        msg = str(e)
        raise PlanError(msg if msg.startswith(where) else f"{where}: {msg}") from None


def tracked(repo, ref):
    """the tracked paths at ref, raw (-z: a name is never quoted or split)."""
    return [p for p in gitio.git(repo, "ls-tree", "-r", "-z", "--name-only", gitio.resolve(repo, ref)).split("\0") if p]


def manifest_names(*plans):
    """the file names that mark a project: every built-in's, and every plan adapter file's."""
    names = {m for a in ADAPTERS.values() for m in a.manifests}
    for p in plans:
        for e in (p.entries if p else ()):
            names.update(e.adapter.manifests)
    return names


def manifests(paths, names, ignore=()):
    """the paths of manifests that count: outside SKIP_DIRS and the ignore folders, sorted."""
    out = []
    for path in paths:
        parts = path.split("/")
        if parts[-1] in names and not SKIP_DIRS & set(parts[:-1]) and not any(holds(f, path) for f in ignore):
            out.append(path)
    return sorted(out)


def covers(entry, path):
    return holds(entry.folder, path) and path.rsplit("/", 1)[-1] in entry.adapter.manifests


def _either(words):
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} or {words[-1]}"


def judge(plan, paths, since, now, names=None):
    """(uncovered manifest paths, messages) of one tree against a plan (None: no plan, nothing covered).
    since(name) -> unix time the entry became retiring, or None; now: unix time; names: the manifest names (default:
    the built-ins' and this plan's)."""
    names = manifest_names(plan) if names is None else names
    if plan is None:
        return manifests(paths, names), []
    found = manifests(paths, names, plan.ignore)
    uncovered = [p for p in found if not any(covers(e, p) for e in plan.entries)]
    messages = []
    for e in plan.entries:
        mine = [p for p in found if covers(e, p)]
        where = f"stack `{e.name}` ({e.folder})"
        if e.status == "planned":
            if mine:
                messages.append(f"planned {where}: its manifest {mine[0]} is here and its adapter `{e.adapter_ref}` is "
                                f"proven, so its checks start: set its status to current")
        elif not mine:
            messages.append(f"{where}: no {_either(e.adapter.manifests)} in {e.folder} any more: remove the entry "
                            f"`{e.name}` from {PATH}")
        elif e.status == "retiring":
            text = f"retiring {where}: its manifest {mine[0]} is still here: finish the migration, then remove its entry"
            start = since(e.name)
            if start is not None and now - start > RETIRING_DAYS * DAY:
                text += (f"; retiring for {int((now - start) // DAY)} days (over {RETIRING_DAYS}): finish the migration "
                         f"or drop it")
            messages.append(text)
    return uncovered, messages


def _status_in(raw, name):
    """the status of the [[stack]] entry `name` in a plan file's bytes, or None (no such entry, or it does not read)."""
    try:
        data = _toml(raw, PATH)
    except PlanError:
        return None
    stacks = data.get("stack")  # tomllib gives a table; an old plan may hold anything in it
    for s in stacks if isinstance(stacks, list) else ():
        if isinstance(s, dict) and s.get("name") == name:
            return s.get("status")
    return None


def retiring_since(repo, sha, name):
    """unix time (commit time) of the oldest plan commit, in the newest unbroken run of commits up to sha that have the
    entry `name` retiring: when it became retiring. None when the plan at sha does not have it retiring."""
    start = None
    for line in gitio.git(repo, "log", "--format=%H %ct", sha, "--", PATH).splitlines():
        commit, stamp = line.split()
        raw = _blob(repo, commit, PATH)
        if raw is None or _status_in(raw, name) != "retiring":
            break
        start = int(stamp)
    return start


def drift_entry(uncovered):
    """the one `fail` entry for every uncovered manifest of a PR (class adapter-fix). Its key holds the paths, so a
    waiver holds while the same manifests stay uncovered and falls away when another appears."""
    return report.entry(
        "D", PATH, 0, "uncovered:" + "\0".join(uncovered), "adapter-fix", "fail",
        f"manifests no stack in {PATH} covers: {', '.join(uncovered)}",
        f"add a [[stack]] entry for each (its folder, an adapter that lists the manifest), or its folder to `ignore`, "
        f"in a PR of its own that adds no manifest (`/ekit:ci-doctor` writes it); a person may waive this entry",
        "a plan entry added in this PR (a PR that adds a manifest is judged by the base branch's plan); moving or "
        "renaming the manifest so the check does not see it")


def _own_plan(repo, mb, head, head_plan, names):
    """True when the PR edits the plan or one of its adapter files and adds no manifest: its own plan judges it (the
    setup PR). A plan that is unchanged names the same adapter files on base and head, so head's list is enough.
    names: the manifest names of the built-ins and both plans."""
    if head_plan is None:
        return False
    changed = gitio.changes(repo, mb, head)
    adapters = {_folder(e.adapter_ref, "adapter") for e in head_plan.entries if e.adapter_ref not in ADAPTERS}
    touched = {p for c in changed for p in (c.old, c.new) if p}
    if PATH not in touched and not adapters & touched:
        return False
    added = [c.new for c in changed if c.status in "ACR" and c.new]
    return not manifests(added, names)


def check_pr(repo, base_ref, head_ref, now=None):
    """The drift check of a PR: (has_plan, note, uncovered, messages) for the head tree. The base branch's plan judges;
    a PR that edits the plan or an adapter file and adds no manifest is judged by its own. With no plan on base or head
    there is nothing to judge (has_plan False); with none on base, the base judges with nothing covered."""
    base, head, mb = gitio.merge_base(repo, base_ref, head_ref)
    now = time.time() if now is None else now
    head_plan = at(repo, head)
    base_plan = base_error = None
    if _blob(repo, base, PATH) is not None:
        try:
            base_plan = at(repo, base)
        except PlanError as e:  # the PR that fixes it is judged by its own plan; any other PR stops on it below
            base_error = e
    if head_plan is None and base_plan is None and base_error is None:
        return False, "no stack plan", [], []
    # a manifest is a file name a built-in or either plan's adapter files list, whichever plan judges: a PR can hide
    # none by adding or dropping the adapter that lists it
    names = manifest_names(base_plan, head_plan)
    paths = tracked(repo, head)
    if _own_plan(repo, mb, head, head_plan, names):
        uncovered, messages = judge(head_plan, paths, lambda n: retiring_since(repo, head, n), now, names)
        return True, "judged by its own plan (the PR edits the plan or an adapter file and adds no manifest)", \
            uncovered, messages
    if base_error is not None:
        raise base_error
    uncovered, messages = judge(base_plan, paths, lambda n: retiring_since(repo, base, n), now, names)
    note = "judged by the base branch's plan" + ("" if base_plan else " (none there: no manifest is covered)")
    return True, note, uncovered, messages


def entry_for(plan, stack, folder):
    """the plan entry for a settled stack (its adapter's name) in a folder: current first, then retiring, then planned;
    None when no entry is for it."""
    mine = [e for e in (plan.entries if plan else ()) if e.folder == folder and e.adapter.name == stack]
    return min(mine, key=lambda e: ("current", "retiring", "planned").index(e.status), default=None)


def drift_at(repo, ref, now=None):
    """The drift of one tree, no base (session start, #57): the tracked files at ref against the plan at ref. Git only:
    no test runner, no network. Drift(False, [], []) when there is no plan there. PlanError: a bad plan or no tomllib
    (named); gitio.Die: a git error."""
    sha = gitio.resolve(repo, ref)
    plan = at(repo, sha)
    if plan is None:
        return Drift(False, [], [])
    uncovered, messages = judge(plan, tracked(repo, sha), lambda n: retiring_since(repo, sha, n),
                                time.time() if now is None else now)
    return Drift(True, uncovered, messages)
