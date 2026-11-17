"""mech-review doctor (#39): find a repo's setup without hints and report each problem with the exact caller input.

Reads the tree at HEAD (manifests, .github/workflows), then trial-runs the tests and the mutation tool in a throwaway worktree
(python: the tests once more inside R3's mutmut sandbox, <project dir>/mutants/) through the runner seam (red.default_runner: runner(argv, cwd) -> (rc, output)). Writes nothing to the checkout: CI changes are
a human decision, so caller gaps are needs-human.
"""
import contextlib
import fnmatch
import json
import os
import re
import shlex
import shutil

from . import gitio, mutants, red, report
from .globs import any_glob
from .mutants import DEFAULT_CMD as RUST_MUTANTS
from .stack import ADAPTERS

CALLER = "EricleungDK/ekit/.github/workflows/mech-review.yml@"
CALLERS = (CALLER, "EricleungDK/ek/.github/workflows/mech-review.yml@")  # + pre-rename callers


def is_caller(text):
    return any(c in text for c in CALLERS)
WORKFLOW = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
SKIP_DIRS = {"node_modules", "vendor", "target", "tests", "test", "fixtures", "testdata", "examples", "third_party", "dist", "build"}
APT = re.compile(r"\bapt(?:-get)?\s+install\s+([^\n#|&;]*)")
EXPR = re.compile(r"\$\{\{.*?\}\}")
PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.:=~\-]*$")
SYSCTL = re.compile(r"\bsysctl\s+(?:-w\s+)?([\w.\-]+=\S+)")
TOOLCHAIN = re.compile(r"(?:^\s*(?:RUSTUP_)?toolchain:\s*['\"]?|dtolnay/rust-toolchain@|rustup\s+(?:default|toolchain\s+install)\s+['\"]?)(\d[\w.\-]*)", re.M | re.I)
CHANNEL = re.compile(r"^\s*channel\s*=\s*['\"]([\w.\-]+)", re.M)
SANDBOX = re.compile(r"bwrap|bubblewrap|unprivileged_userns")
KEY = re.compile(r"^(\s+)([\w-]+):\s*(.*)$")
MUTATION_TOOL = {"rust": RUST_MUTANTS, "python": "mutmut", "ts": "node_modules/.bin/stryker"}
SANDBOX_INPUTS = ("extra-apt-packages: bubblewrap; "
                  "setup-command: sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0")
NOT_YOURS = "merging or pushing the CI change yourself"
NOT_SKIP = "skipping or deselecting tests in the caller to get a green trial"
DEFAULT_TEST_PATHS = "tests/**"
MISSING = re.compile(r"No such file or directory: (['\"])(.+?)\1")


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


def read_ci(texts):
    """{apt: [packages], sysctl: [key=value], toolchain} from workflow texts. Comments are dropped; order is first seen."""
    apt, sysctl, toolchain = [], [], None
    for text in texts:
        text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        text = EXPR.sub(" ", text.replace("\\\n", " "))  # a workflow is not shell: keep only what is plainly a package name
        for m in APT.finditer(text):
            apt += [p for p in m.group(1).split() if PACKAGE.match(p) and p not in apt]
        sysctl += [s for s in SYSCTL.findall(text) if s not in sysctl]
        m = TOOLCHAIN.search(text)
        toolchain = toolchain or (m.group(1) if m else None)
    return {"apt": apt, "sysctl": sysctl, "toolchain": toolchain}


def caller_inputs(text):
    """{input: value} of the `with:` block under the mech-review `uses:` line. A block scalar joins its lines with newlines."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if is_caller(line))
    inputs, indent, key = {}, None, None
    for line in lines[start + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = KEY.match(line)
        depth = len(line) - len(line.lstrip())
        if indent is None:
            if m and m.group(2) == "with":
                indent = -depth  # negative until the first key sets the block's indent
            continue
        if indent < 0:
            if depth <= -indent:
                break
            indent = depth
        if depth < indent:
            break
        if depth > indent and key:
            inputs[key] = (inputs[key] + "\n" + line.strip()).strip()
        elif m:
            key = m.group(2)
            inputs[key] = "" if m.group(3).strip() in ("|", ">") else m.group(3).strip().strip("\"'")
    return inputs


def wanted_inputs(stack, project_dir, ci, channel):
    """The caller inputs this repo needs, left out when they equal the workflow's default."""
    inputs = {"stack": stack}
    if project_dir != ".":
        inputs["project-dir"] = project_dir
        inputs["test-paths"] = f"{project_dir}/{DEFAULT_TEST_PATHS}"
    else:
        inputs["test-paths"] = DEFAULT_TEST_PATHS
    if ci["apt"]:
        inputs["extra-apt-packages"] = " ".join(ci["apt"])
    if ci["sysctl"]:
        inputs["setup-command"] = " && ".join(f"sudo sysctl -w {s}" for s in ci["sysctl"])
    toolchain = ci["toolchain"] or channel
    if stack == "rust" and toolchain:
        inputs["rust-toolchain"] = toolchain
    return inputs


def _missing(name, want, have, paths):
    """True when the caller's value does not cover `want`. Packages may be a superset; a command may be part of a longer one.
    Custom test-paths stand while they match a file; a repo with no tests at `want` has nothing better to offer."""
    if name == "test-paths":
        globs = have.get(name, DEFAULT_TEST_PATHS).split()
        return not any(any_glob(p, globs) for p in paths) and any(any_glob(p, [want]) for p in paths)
    if name not in have:
        return name != "stack" or want != "rust"  # rust is the workflow's default
    if name == "extra-apt-packages":
        return not set(want.split()) <= set(have[name].split())
    if name == "setup-command":
        return want not in have[name]
    return want != have[name]


def caller_entries(callers, inputs, paths):
    if not callers:
        return [report.entry("doctor", ".github/workflows/mech-review.yml", 0, "no-caller", "needs-human", "fail",
                             "no mech-review caller workflow",
                             "add a caller with `uses: " + CALLER + "v0` and these inputs: " + json.dumps(inputs),
                             NOT_YOURS)]
    path, have = callers[0]
    return [report.entry("doctor", path, 0, name, "needs-human", "fail", f"caller input {name} missing or wrong",
                         f"set {name}: {want}", NOT_YOURS)
            for name, want in inputs.items() if _missing(name, want, have, paths)]


def _copy(src, dst):
    """mutmut 3.8.1's copy of an also_copy entry (and its defaults): a file with copy2, a dir with copytree over what
    is there (links followed), a missing entry skipped."""
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    elif os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)


def _copy_source(crate, name, box):
    """mutmut 3.8.1's copy of a source path (copy_src_dir): a file with copy2; a dir walked with os.walk, which does not
    follow a link to a dir, and each file in it (a file link followed) copied with copy2 unless already there."""
    top = os.path.join(crate, name)
    if os.path.isdir(top):
        files = [os.path.join(root, f) for root, _, fs in os.walk(top) for f in fs]
    else:
        files = [top] if os.path.isfile(top) else []
    for src in files:
        dst = os.path.join(box, os.path.relpath(src, crate))
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def sandbox(repo, head, crate, project_dir):
    """`<crate>/mutants/` filled the way R3's mutmut run fills it, at best: the entries that may be R3's source_paths,
    then also_copy and mutmut's defaults (root test*.py from the crate dir, as mutmut globs them). Returns its path.
    With no diff no source is named, so each tracked top-level entry that holds a .py file and is not in also_copy
    (also_copy leaves out an entry holding a link mutmut's copytree cannot copy) is copied the way R3 copies a source:
    the most R3 ever copies of it (as a non-source it is not copied at all)."""
    box = os.path.join(crate, "mutants")  # made by the first copy: a python project dir always holds a manifest
    copied = mutants.also_copy(repo, head, project_dir, [])
    tree = head if project_dir == "." else f"{head}:{project_dir}"
    tracked = gitio.git(repo, "ls-tree", "-r", "-z", "--full-tree", "--name-only", tree).split("\0")
    skip = set(copied) | mutants.MUTMUT_COPIES | {"mutants"}
    srcs = sorted({p.split("/", 1)[0] for p in tracked if p.endswith(".py")} - skip)
    tests = sorted(n for n in os.listdir(crate) if fnmatch.fnmatchcase(n, "test*.py"))
    for name in srcs:
        if name not in tests:
            _copy_source(crate, name, box)
    for name in copied + sorted(mutants.MUTMUT_COPIES) + tests:
        _copy(os.path.join(crate, name), os.path.join(box, name))
    return box


@contextlib.contextmanager
def _import_path(box):
    """PYTHONPATH for the sandbox run, as mutmut's setup_source_paths sets sys.path before it runs pytest in-process:
    mutants/source, mutants/src and mutants/ (those that exist) first, so the tests import the copy. They go ahead of
    an inherited PYTHONPATH and of an editable install's .pth, which would import the caller's checkout instead. The
    runner seam takes no env: the run inherits this process's, restored after."""
    old = os.environ.get("PYTHONPATH")
    first = [p for p in (os.path.join(box, "source"), os.path.join(box, "src"), box) if os.path.isdir(p)]
    os.environ["PYTHONPATH"] = os.pathsep.join(first + ([old] if old else []))
    try:
        yield
    finally:
        if old is None:
            del os.environ["PYTHONPATH"]
        else:
            os.environ["PYTHONPATH"] = old


def trial(repo, head, stack, project_dir, runner):
    """Run the whole suite and the mutation tool's --version at head; for python, when the suite passes, the suite once
    more inside R3's mutmut sandbox. Returns (trial dict, entries)."""
    adapter = ADAPTERS[stack]()
    try:
        with red.worktree(repo, head) as wt:
            adapter.worktree_setup(repo, wt, project_dir)
            crate = os.path.join(wt, project_dir)
            cmd = adapter.test_cmd_in(crate)
            rc, out = runner(shlex.split(cmd), crate)
            verdict = adapter.outcome(rc, out)
            box, box_entries = "skipped", []
            if stack == "python" and verdict == "pass":
                where = sandbox(repo, head, crate, project_dir)
                with _import_path(where):
                    brc, bout = runner(shlex.split(cmd), where)
                box = "pass" if adapter.outcome(brc, bout) == "pass" else "fail"
                if box == "fail":
                    box_entries = [_sandbox_entry(cmd, project_dir, missing(bout, wt, where))]
            tool = MUTATION_TOOL[stack]
            tool_rc, _ = runner(shlex.split(tool) + ["--version"], crate)
    except gitio.Die as e:  # read-only .git (sandbox): the static findings still stand
        reason = str(e).splitlines()[-1]  # git's last line is the cause
        return {"tests": "unavailable"}, [report.entry("doctor", "", 0, "trial", "env", "fail", f"trial could not run: {reason}",
                                                       "fix that cause (sandbox: rerun outside it); --no-trial reads the tree only",
                                                       NOT_SKIP)]
    state = "absent" if tool_rc is None else "present" if tool_rc == 0 else "broken"  # absent is fine: CI installs it
    result = {"tests": verdict, "command": cmd, "mutation_tool": state}
    if stack == "python":
        result["sandbox"] = box
    entries = []
    if state == "broken":
        entries.append(report.entry("doctor", "", 0, "mutation-tool", "env", "fail", f"`{tool} --version` failed ({tool_rc})",
                                    "repair the install; in CI, set setup-command", NOT_SKIP))
    return result, _test_entries(verdict, cmd, out) + box_entries + entries


def missing(out, wt, box):
    """the paths a FileNotFoundError names in the output, first seen first: relative to the sandbox dir when inside the
    worktree (`../docs/x.md`: above the project dir), as printed otherwise."""
    root, box = os.path.realpath(wt), os.path.realpath(box)
    seen = []
    for m in MISSING.finditer(out):
        path = m.group(2)
        if os.path.isabs(path):
            real = os.path.realpath(path)
            if real == root or real.startswith(root + os.sep):
                path = os.path.relpath(real, box)
        else:
            path = os.path.normpath(path)
        if path not in seen:
            seen.append(path)
    return seen


def _sandbox_entry(cmd, project_dir, paths):
    where = "mutants/" if project_dir == "." else f"{project_dir}/mutants/"
    if paths:
        found = "missing there: " + ", ".join(f"`{p}`" for p in paths)
    else:
        found = f"no missing path found in the output of `{cmd}` run in {where}"
    return report.entry("doctor", "", 0, "sandbox-copy", "env", "fail",
                        f"R3's mutmut sandbox fails where the plain run passes ({found})",
                        f"R3 copies into {where} only the project dir's tracked top-level entries and mutmut's defaults; "
                        "keep the files the tests read inside the project dir, or make the tests not depend on files "
                        "above it (a project-dir in a subfolder whose tests read ../ is a known limit); rerun doctor",
                        NOT_SKIP)


def _test_entries(verdict, cmd, out):
    if verdict in ("pass", "none"):
        return []
    if verdict == "env":
        return [report.entry("doctor", "", 0, "toolchain", "env", "fail", f"`{shlex.split(cmd)[0]}` not found",
                             "install it, or set setup-command in the caller", NOT_SKIP)]
    if SANDBOX.search(out):
        return [report.entry("doctor", "", 0, "sandbox", "env", "fail", "tests need a sandbox the runner blocks",
                             f"set {SANDBOX_INPUTS}", NOT_SKIP)]
    return [report.entry("doctor", "", 0, "tests", "env", "fail", f"tests fail at head ({verdict}): `{cmd}`",
                         "fix them, or set setup-command for what they need; rerun doctor", NOT_SKIP)]


def _channel(repo, head, project_dir, paths):
    """The pin in rust-toolchain.toml or a plain rust-toolchain file, repo root first."""
    for name in ("rust-toolchain.toml", "rust-toolchain"):
        for path in (name, f"{project_dir}/{name}"):
            if path in paths:
                text = gitio.blob(repo, head, path)
                m = CHANNEL.search(text) if name.endswith(".toml") else re.match(r"\s*([\w.\-]+)", text)
                if m:
                    return m.group(1)
    return None


def run(repo, head_ref="HEAD", stack=None, project_dir=None, run_trial=True, runner=None):
    try:
        gitio.git(repo, "rev-parse", "--git-dir")
    except gitio.Die:
        raise gitio.Die(f"not a git repo: {repo}")
    head = gitio.resolve(repo, head_ref)
    paths = gitio.git(repo, "ls-tree", "-r", "--name-only", head).splitlines()
    found = [c for c in candidates(paths) if (not stack or c[0] == stack) and (not project_dir or c[1] == project_dir)]
    if project_dir and stack and not found:
        found = [(stack, project_dir)]
    detected = {"stack": None, "project_dir": None}
    inputs, entries, tried = {}, [], {"tests": "skipped"}
    if len(found) != 1:
        if found:
            names = ", ".join(f"{s} in {d}" for s, d in found)
            entries.append(report.entry("doctor", "", 0, "ambiguous", "needs-human", "fail", f"several projects: {names}",
                                        "pick one with --stack and --project-dir", "guessing the project"))
        elif stack or project_dir:
            asked = " in ".join(x for x in (stack, project_dir) if x)
            names = ", ".join(f"{s} in {d}" for s, d in candidates(paths)) or "none"
            entries.append(report.entry("doctor", "", 0, "no-match", "needs-human", "fail", f"no project found for {asked}",
                                        f"projects here: {names}; passing both --stack and --project-dir overrides detection",
                                        "guessing the project"))
        else:
            entries.append(report.entry("doctor", "", 0, "no-project", "needs-human", "fail",
                                        "no project found: no " + ", ".join(m for a in ADAPTERS.values() for m in a.manifests),
                                        "pass --stack and --project-dir", "guessing the project"))
    else:
        stack, project_dir = found[0]
        detected = {"stack": stack, "project_dir": project_dir}
        flows = sorted(p for p in paths if WORKFLOW.match(p))
        texts = {p: gitio.blob(repo, head, p) for p in flows}
        callers = [(p, caller_inputs(t)) for p, t in texts.items() if is_caller(t)]
        ci = read_ci(t for p, t in texts.items() if not is_caller(t))
        inputs = wanted_inputs(stack, project_dir, ci, _channel(repo, head, project_dir, paths))
        entries += caller_entries(callers, inputs, paths)
        if run_trial:
            tried, trial_entries = trial(repo, head, stack, project_dir, runner or red.default_runner())
            entries = trial_entries + entries
    entries = report.finalize(entries)
    summary = f"fail {head} ({len(entries)} problems)" if entries else f"ok {head}"
    return {"ekit": report.ekit_version(), "head": head, "detected": detected, "inputs": inputs, "trial": tried,
            "entries": entries, "summary": summary}
