"""`stack: auto`: settle the stack and project dir from the tracked tree, git only (no PR code runs).

Detection is doctor's (`candidates` lives here so doctor and the workflow's `stack` job share it: the shallowest
manifests, fixture and vendored dirs skipped). It never guesses: several projects, none, or a PR whose head finds
something other than its base is an error naming what was found, and the caller sets `stack` and `project-dir`. A stack the caller set is used as given; a project dir the caller set is
never replaced (`.` is the default and reads as unset).

Result: {"stack": str | None, "project_dir": str, "error": str | None}; the `resolve` subcommand adds "target_os"
(target_os below). The workflow writes the values to job outputs, so a value never holds a control character (a
newline would start another output)."""
from .stack import ADAPTERS

SKIP_DIRS = {"node_modules", "vendor", "target", "tests", "test", "fixtures", "testdata", "examples", "third_party", "dist", "build"}

AUTO = "auto"
SET_INPUTS = "set the stack and project-dir inputs in the mech-review caller"


def candidates(paths):
    """[(stack, dir)] of the shallowest manifests, sorted; fixture, vendored and build dirs do not count."""
    found = {}
    for path in paths:
        parts = path.split("/")
        if SKIP_DIRS & set(parts[:-1]):
            continue
        for stack, adapter in ADAPTERS.items():
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


def _fail(project_dir, why, side=""):
    where = f", {side}" if side else ""
    return {"stack": None, "project_dir": project_dir, "error": f"stack auto{where}: {why}; {SET_INPUTS}"}


def _find(paths, project_dir):
    """((stack, dir), None) for the one project, or (None, why)."""
    if project_dir != ".":
        here = set(paths)
        found = [(s, project_dir) for s, a in sorted(ADAPTERS.items()) if any(f"{project_dir}/{m}" in here for m in a.manifests)]
        if not found:
            return None, f"no project found in {project_dir} (projects here: {_names(candidates(paths)) or 'none'})"
    else:
        found = candidates(paths)
        if not found:
            return None, "no project found (no " + ", ".join(m for a in ADAPTERS.values() for m in a.manifests) + ")"
    if len(found) > 1:
        return None, f"several projects: {_names(found)}"
    if not _safe(found[0][1]):
        return None, f"project dir {found[0][1]!r} holds a control character"
    return found[0], None


def _explicit(stack, project_dir):
    if stack not in ADAPTERS:
        *rest, last = sorted([AUTO, *ADAPTERS])
        return {"stack": None, "project_dir": project_dir, "error": f"stack {stack}: want {', '.join(rest)} or {last}"}
    return {"stack": stack, "project_dir": project_dir, "error": None}


def pick(paths, stack=AUTO, project_dir="."):
    """Settle one tree (its tracked paths)."""
    if stack != AUTO:
        return _explicit(stack, project_dir)
    found, why = _find(paths, project_dir)
    if why:
        return _fail(project_dir, why)
    return {"stack": found[0], "project_dir": found[1], "error": None}


def pick_pr(base_paths, head_paths, stack=AUTO, project_dir="."):
    """Settle a PR: base and head must find the same project, so a PR cannot switch the stack its own checks run with."""
    if stack != AUTO:
        return _explicit(stack, project_dir)
    base, why = _find(base_paths, project_dir)
    if why:
        return _fail(project_dir, why, "base")
    head, why = _find(head_paths, project_dir)
    if why:
        return _fail(project_dir, why, "head")
    if base != head:
        return _fail(project_dir, f"base finds {_names([base])}, head finds {_names([head])}")
    return {"stack": head[0], "project_dir": head[1], "error": None}


def target_os(got, adapter=None):
    """The OS the settled stack's tests run on (#58): the adapter file's `target-os` (validated: linux, macos or
    windows), else the built-in's (linux). None when no stack was settled."""
    if got["stack"] is None:
        return None
    return (adapter or ADAPTERS[got["stack"]]).target_os
