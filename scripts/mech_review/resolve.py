"""`stack: auto`: settle the stack and project dir from the tracked tree, git only (no PR code runs).

Detection is doctor's (`candidates` lives here so doctor and the workflow's `stack` job share it: the shallowest
manifests, fixture and vendored dirs skipped). It never guesses: several projects, none, or a PR whose head finds
something other than its base is an error naming what was found, and the caller sets `stack` and `project-dir`. A stack the caller set is used as given; a project dir the caller set is
never replaced (`.` is the default and reads as unset). With a stack plan on the base (#17), from_plan settles the PR
from the plan's stacks to run instead, and nothing is detected; without one, detection takes the repo's adapter files
too (`adapters`: the built-ins and the base's .ekit/adapters/<name>.toml, a file named like a built-in in its place).

Result: {"stack": str | None, "project_dir": str, "error": str | None}; the `resolve` subcommand adds "target_os"
(target_os below); several stacks from a plan add "stacks" (from_plan). The workflow writes the values to job outputs,
so a value never holds a control character (a newline would start another output)."""
from .stack import ADAPTERS

SKIP_DIRS = {"node_modules", "vendor", "target", "tests", "test", "fixtures", "testdata", "examples", "third_party", "dist", "build"}

AUTO = "auto"
SET_INPUTS = "set the stack and project-dir inputs in the mech-review caller"


def candidates(paths, adapters=ADAPTERS):
    """[(stack, dir)] of the shallowest manifests, sorted; fixture, vendored and build dirs do not count. adapters:
    {stack: adapter}, the built-ins by default (with the repo's adapter files in them: #17)."""
    found = {}
    for path in paths:
        parts = path.split("/")
        if SKIP_DIRS & set(parts[:-1]):
            continue
        for stack, adapter in adapters.items():
            if parts[-1] in adapter.manifests:
                found[(stack, "/".join(parts[:-1]) or ".")] = len(parts)
    if not found:
        return []
    depth = min(found.values())
    return sorted(k for k, v in found.items() if v == depth)


def _safe(name):
    return not any(ord(c) < 32 or ord(c) == 127 for c in name)


def _names(found):
    return ", ".join(f"{s} in {d}" if _safe(d) else f"{s} in {d!r}" for s, d in found)


def fail(project_dir, why, side=""):
    where = f", {side}" if side else ""
    return {"stack": None, "project_dir": project_dir, "error": f"stack auto{where}: {why}; {SET_INPUTS}"}


def _find(paths, project_dir, adapters):
    """((stack, dir), None) for the one project, or (None, why)."""
    if project_dir != ".":
        here = set(paths)
        found = [(s, project_dir) for s, a in sorted(adapters.items()) if any(f"{project_dir}/{m}" in here for m in a.manifests)]
        if not found:
            return None, f"no project found in {project_dir} (projects here: {_names(candidates(paths, adapters)) or 'none'})"
    else:
        found = candidates(paths, adapters)
        if not found:
            return None, "no project found (no " + ", ".join(m for a in adapters.values() for m in a.manifests) + ")"
    if len(found) > 1:
        return None, f"several projects: {_names(found)}"
    if not _safe(found[0][1]):
        return None, f"project dir {found[0][1]!r} holds a control character"
    return found[0], None


def _explicit(stack, project_dir, adapters=ADAPTERS):
    if stack not in adapters:
        *rest, last = sorted([AUTO, *adapters])
        return {"stack": None, "project_dir": project_dir, "error": f"stack {stack}: want {', '.join(rest)} or {last}"}
    return {"stack": stack, "project_dir": project_dir, "error": None}


def pick(paths, stack=AUTO, project_dir=".", adapters=ADAPTERS):
    """Settle one tree (its tracked paths)."""
    if stack != AUTO:
        return _explicit(stack, project_dir, adapters)
    found, why = _find(paths, project_dir, adapters)
    if why:
        return fail(project_dir, why)
    return {"stack": found[0], "project_dir": found[1], "error": None}


def pick_pr(base_paths, head_paths, stack=AUTO, project_dir=".", adapters=ADAPTERS):
    """Settle a PR: base and head must find the same project, so a PR cannot switch the stack its own checks run with.
    adapters: the base's (the built-ins and the repo's adapter files there), for both trees."""
    if stack != AUTO:
        return _explicit(stack, project_dir, adapters)
    base, why = _find(base_paths, project_dir, adapters)
    if why:
        return fail(project_dir, why, "base")
    head, why = _find(head_paths, project_dir, adapters)
    if why:
        return fail(project_dir, why, "head")
    if base != head:
        return fail(project_dir, f"base finds {_names([base])}, head finds {_names([head])}")
    return {"stack": head[0], "project_dir": head[1], "error": None}


def from_plan(entries, project_dir="."):
    """Settle a PR from the base branch's stack plan (#17): entries are the ones whose checks run (stack_plan.to_run).
    Detection is not used. One entry gives the single-stack result; several give stack None and `stacks`, one
    {name, stack, project_dir, adapter, target_os} each. A project dir the caller set keeps the entries for it."""
    if project_dir != ".":
        entries = [e for e in entries if e.folder == project_dir]
    if not entries:
        where = f" in {project_dir}" if project_dir != "." else ""
        return fail(project_dir, f"the stack plan has no stack to run{where} (no current, retiring or planned stack "
                                  f"whose manifest is here)")
    if len(entries) == 1:
        return {"stack": entries[0].adapter.name, "project_dir": entries[0].folder, "error": None}
    return {"stack": None, "project_dir": project_dir, "error": None,
            "stacks": [{"name": e.name, "stack": e.adapter.name, "project_dir": e.folder, "adapter": e.adapter_ref,
                        "target_os": e.target_os} for e in entries]}


def target_os(got, adapter=None):
    """The OS the settled stack's tests run on (#58): the adapter file's `target-os` (validated: linux, macos or
    windows), else the built-in's (linux). None when no stack was settled."""
    if got["stack"] is None:
        return None
    return (adapter or ADAPTERS[got["stack"]]).target_os
