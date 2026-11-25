"""mech-review doctor (#39): find a repo's setup without hints and report each problem with the exact caller input.

Reads the tree at HEAD (manifests, .github/workflows), then trial-runs the tests and the mutation tool in a throwaway worktree
(python: the tests once more inside R3's mutmut sandbox, <project dir>/mutants/) through the runner seam (red.default_runner: runner(argv, cwd) -> (rc, output)). Writes nothing to the checkout: CI changes are
a human decision, so caller gaps are needs-human.
"""
import contextlib
import json
import os
import re
import shlex
import shutil

from . import adapter_file, detect, gitio, mutants, red, report, stack_plan
from .globs import any_glob
from .mutants import DEFAULT_CMD as RUST_MUTANTS
from .resolve import candidates, pick
from .stack import ADAPTERS

CALLER = "EricleungDK/ekit/.github/workflows/mech-review.yml@"
CALLERS = (CALLER, "EricleungDK/ek/.github/workflows/mech-review.yml@")  # + pre-rename callers
WAIVER = "EricleungDK/ekit/.github/workflows/mech-waive.yml@"


def is_caller(text):
    return any(c in text for c in CALLERS)

WORKFLOW = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
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
NOT_UNPROVEN = "opening the setup PR before its adapter passes R0"
DEFAULT_TEST_PATHS = "tests/**"
SCENARIOS = ".ekit/scenarios/"  # taste-it scenarios (and their fixtures): test support in every stack (#39)
SCENARIO_GLOB = SCENARIOS + "**"
MUTMUT_PYTEST = "-p no:randomly -p no:random-order"  # what mutmut 3.8.1 adds to its pytest run (runners/harness.py)
LS_TREE = re.compile(r"(\d+) \w+ (\w+)\t(.*)", re.S)  # a record of `git ls-tree -z`
MISSING = re.compile(r"No such file or directory: (['\"])(.+?)\1")


def own_ci(repo, head, paths):
    """the repo's own CI workflow files (#23): each one is_ci reads as the team's CI. Setup mode writes base CI jobs only
    when there is none."""
    return [p for p in sorted(paths) if WORKFLOW.match(p) and is_ci(gitio.blob(repo, head, p))]


def _calls_ekit(text):
    return is_caller(text) or WAIVER in text


CI_EVENTS = {"push", "pull_request", "pull_request_target", "merge_group"}
YAML_KEY = re.compile(r"""^(['"]?)([\w-]+)\1\s*:(?:\s+(.*?))?\s*$""")
TAGS_ONLY = {"tags", "tags-ignore"}


def sections(lines):
    """{key: (inline value, [lines under it])} of the keys at the outermost indent of a block of YAML lines: a reading
    of the block style a workflow is written in, not a YAML parser. Comment lines, blank lines and ` #` comments after
    a value are dropped."""
    lines = [re.sub(r"\s+#.*$", "", line) for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return {}
    out, key, top = {}, None, min(len(x) - len(x.lstrip()) for x in lines)
    for line in lines:
        m = YAML_KEY.match(line.strip()) if len(line) - len(line.lstrip()) == top else None
        if m:
            key = m.group(2)
            out[key] = (m.group(3) or "", [])
        elif key is not None:
            out[key][1].append(line)
    return out


def jobs(text):
    """{job id: its lines} of a workflow's `jobs:`, or None when they are written in flow style (`jobs: {test: ...}`),
    which this reader does not read"""
    block = sections(text.splitlines()).get("jobs")
    if block and block[0] not in ("", "{}"):
        return None
    return {k: v for k, (_, v) in sections(block[1]).items()} if block else {}


def _events(on):
    """the events a workflow's `on:` names, or None when it holds a shape this reader does not read (a flow mapping)
    or there is no `on:`. A push of tags only is a release: left out."""
    if on is None or on[0].startswith("{"):
        return None
    value, block = on
    items = value.strip("[]").split(",") if value else [x.strip()[1:] for x in block if x.strip().startswith("- ")]
    if value or items:
        return {x.strip().strip("'\"") for x in items}
    return {k for k, (_, under) in sections(block).items() if k != "push" or not under or set(sections(under)) - TAGS_ONLY}


def is_ci(text):
    """the workflow is the team's CI: it holds a job that calls no ekit workflow (a build or test job of its own), and
    its trigger is a push or a pull request (a push of tags only is a release). A trigger or jobs this reader cannot
    read count, so base jobs are never written beside a team's CI"""
    events, found = _events(sections(text.splitlines()).get("on")), jobs(text)
    own = found is None or any(not any(_calls_ekit(line) for line in job) for job in found.values())
    return own and (events is None or bool(events & CI_EVENTS))


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


def wanted_inputs(stack, project_dir, ci, channel, scenarios=False):
    """The caller inputs this repo needs, left out when they equal the workflow's default. scenarios: the repo has
    .ekit/scenarios/, so test-paths holds SCENARIO_GLOB too (one glob per line, as the workflow reads them)."""
    inputs = {"stack": stack}
    if project_dir != ".":
        inputs["project-dir"] = project_dir
        inputs["test-paths"] = f"{project_dir}/{DEFAULT_TEST_PATHS}"
    else:
        inputs["test-paths"] = DEFAULT_TEST_PATHS
    if scenarios:
        inputs["test-paths"] += "\n" + SCENARIO_GLOB
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
        return not any(any_glob(p, globs) for p in paths) and any(any_glob(p, want.split()) for p in paths)
    if name not in have:
        if name in ("stack", "project-dir"):  # the workflow's default is `stack: auto`: missing is fine when auto finds it
            got = pick(paths, have.get("stack", "auto"), have.get("project-dir", "."))
            return got["error"] is not None or got["stack" if name == "stack" else "project_dir"] != want
        return True
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


def scenario_entries(stack, callers, inputs, paths):
    """One env entry when .ekit/scenarios/ holds files of the stack that the caller's test-paths (the workflow's
    default with no caller) do not cover: R3 would mutate them as production code. Language-free: the stack's own
    classify says which files are its."""
    adapter = ADAPTERS[stack]()
    globs = (callers[0][1] if callers else {}).get("test-paths", DEFAULT_TEST_PATHS).split()
    left = [p for p in paths if p.startswith(SCENARIOS) and adapter.classify(p, []) is not None and not any_glob(p, globs)]
    if not left:
        return []
    return [report.entry("doctor", "", 0, "scenario-test-paths", "env", "fail",
                         f"`{SCENARIOS}` holds {stack} files no test path covers ({_listed(left)}): R3 mutates them as "
                         "production code",
                         f"add `{SCENARIO_GLOB}` to test-paths: set test-paths: {inputs['test-paths']}", NOT_YOURS)]


def _copy(src, dst):
    """mutmut 3.8.1's copy of an also_copy entry (and its defaults): a file with copy2, a dir with copytree over what
    is there (links followed), a missing entry skipped."""
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    elif os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)


def _copy_source(crate, name, box):
    """mutmut 3.8.1's copy of a source path (copy_src_dir): a file with copy2, a dangling link skipped; a dir walked with
    os.walk, which does not follow a link to a dir, and each file in it (a file link followed) copied with copy2.
    mutmut keeps a file already in mutants/ (only a tracked mutants/ holds one here): the fresh copy is R3's best case."""
    top = os.path.join(crate, name)
    if os.path.isdir(top):
        files = [os.path.join(root, f) for root, _, fs in os.walk(top) for f in fs]
    else:
        files = [top] if os.path.isfile(top) else []
    for src in files:
        dst = os.path.join(box, os.path.relpath(src, crate))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


class CopyFails(Exception):
    """mutmut's copy into mutants/ would stop or never end: .paths, relative to the project dir (read by the handler
    only: the exception's own args are never shown)."""

    def __init__(self, paths):
        self.paths = paths


def _inside(path, top):
    return path == top or path.startswith(top + os.sep)


OUTSIDE_WALK = 10000  # entries walked outside the checkout per top-level entry: then the rest counts as fine


def _copytree_stops(top, crate, root, checkouts):
    """the links in top (a top-level entry, itself a link or not) that copytree (links followed, as mutmut copies
    tests/) stops or loops on: dangling, to a dir that holds a dir on the way there (the project dir included), into
    one of the repo's checkouts (its worktrees: main and linked) by an absolute path, or to a dir that holds one of
    them. A fresh CI checkout has no such path; here copytree would copy the checkout, the link in it included, over
    and over. Found by walking, nothing copied; the checkouts are tested before any walk, so the verdict does not
    hang on the walk's order. A dir outside the checkout at root is walked for loops too, at most OUTSIDE_WALK entries
    (a big one stays cheap). A missing
    top-level entry is skipped, as mutmut skips it. The check sees a bare checkout: a link to something CI's
    setup-command builds reads as dangling here."""
    bad = []
    left = [OUTSIDE_WALK]

    def visit(path, seen):
        real = os.path.realpath(path)
        if not _inside(real, root):
            left[0] -= 1
        into = any((_inside(real, c) and not _inside(real, root)) or _inside(c, real) for c in checkouts)
        if not os.path.exists(real) or into or any(_inside(s, real) for s in seen):  # a dir never holds one on its way
            bad.append(path)
        elif os.path.isdir(path) and left[0] > 0:
            try:
                names = os.listdir(path)
            except OSError:  # unreadable: the copy names it, with its reason
                return
            for name in names:
                visit(os.path.join(path, name), seen | {real})

    root = os.path.realpath(root)  # as real is (macOS: /var is /private/var)
    if os.path.exists(top):
        visit(top, {os.path.realpath(crate)})
    return bad


def _dangling_files(top):
    """the dangling links mutmut's copy of a source dir stops on (it copies each file, dir links not followed)."""
    return [os.path.join(r, f) for r, _, fs in os.walk(top) for f in fs if not os.path.exists(os.path.join(r, f))]


def sandbox(repo, head, crate, project_dir, root):
    """`<crate>/mutants/` filled the way R3's mutmut run fills it, at best: the entries that may be R3's source_paths,
    then also_copy and mutmut's defaults. Returns (its path, {top-level entry: [links that keep it out of R3's copy]});
    raises CopyFails when mutmut's copy would stop or loop, the links checked before anything is copied (root: the
    checkout). An entry kept out (also_copy's link rule, mutants._link_ok) is a known limit of R3, named not copied.
    With no diff no source is named, so each tracked top-level entry that holds a .py file and is not in also_copy
    (also_copy leaves out an entry holding a link mutmut's copytree cannot copy) is copied the way R3 copies a source:
    the most R3 ever copies of it (as a non-source it is not copied at all)."""
    box = os.path.join(crate, "mutants")  # made by the first copy: a python project dir always holds a manifest
    copied = mutants.also_copy(repo, head, project_dir, [])
    tree = head if project_dir == "." else f"{head}:{project_dir}"
    tracked = {}  # path under the project dir -> (mode, object), as also_copy reads it
    for rec in gitio.git(repo, "ls-tree", "-r", "-z", "--full-tree", tree).split("\0"):
        if rec:  # "<mode> <type> <object>\t<path>": the path is everything after the first tab
            mode, obj, path = LS_TREE.fullmatch(rec).groups()
            tracked[path] = (mode, obj)
    skip = set(copied) | mutants.MUTMUT_COPIES | {"mutants"}
    srcs = sorted({p.partition("/")[0] for p in tracked if p.endswith(".py")} - skip)
    held = _held_out(repo, tracked, skip | set(srcs))
    bad = [p for n in srcs for p in _dangling_files(os.path.join(crate, n))]
    checkouts = [os.path.realpath(line[len("worktree "):]) for line in
                 gitio.git(repo, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]
    bad += [p for n in sorted(mutants.MUTMUT_COPIES)
            for p in _copytree_stops(os.path.join(crate, n), crate, root, checkouts)]
    if bad:
        raise CopyFails(sorted({_rel(p, crate) for p in bad}))
    for name in srcs:  # mutmut's root test*.py default among them: tracked .py files left out of also_copy
        _copy_or_fail(_copy_source, crate, name, box)
    for name in copied + sorted(mutants.MUTMUT_COPIES):
        _copy_or_fail(lambda c, n, b: _copy(os.path.join(c, n), os.path.join(b, n)), crate, name, box)
    return box, held


def _held_out(repo, tracked, copied):
    """{top-level entry: sorted links} for each entry R3's copy leaves out because of a link mutants._link_ok rejects
    (dangling, to a dir, or leaving the project dir), of those doctor does not copy either (copied: the names it does)."""
    dirs = set()  # every dir above a tracked path
    for path in tracked:
        while "/" in path:
            path = path.rpartition("/")[0]
            dirs.add(path)
    files = {p for p, (mode, _) in tracked.items() if mode in mutants.FILE_MODES}
    held = {}
    for path, (mode, obj) in sorted(tracked.items()):
        top = path.partition("/")[0]
        if mode == mutants.LINK_MODE and top not in copied \
                and not mutants._link_ok(path, gitio.git(repo, "cat-file", "blob", obj), files, dirs):
            held.setdefault(top, []).append(path)
    return held


class CopyError(Exception):
    """a copy into mutants/ failed for a reason other than the links checked first: .paths, .why (project-relative)."""

    def __init__(self, paths, why):
        super().__init__(paths, why)
        self.paths, self.why = paths, why


def _copy_or_fail(copy, crate, name, box):
    try:
        copy(crate, name, box)
    except OSError as e:
        raise _copy_error(e, crate, name) from e


def _copy_error(e, crate, name):
    """CopyError naming the paths the error names (shutil.Error's (src, dst, why) rows, or its filename), relative to
    the project dir, else the entry being copied (a copy onto itself gives shutil.Error a plain string)."""
    # a row's src or dst can be a DirEntry (copytree recursing with one): made a str before any sort
    # copytree's rows are (src, dst, why) tuples; its args[0] is a str, or such a str split into characters, otherwise
    rows = sorted((os.fspath(a), os.fspath(b), why) for a, b, why in
                  (r for r in e.args[0] if isinstance(r, tuple))) if isinstance(e, shutil.Error) else []
    if rows:
        why = rows[0][2]  # str(OSError) of the first row: its strerror, as for a plain OSError
        m = re.match(r"\[(?:Errno|WinError) \d+\] ([^:]+)", why)  # POSIX and Windows word it so
        return CopyError(sorted({_rel(src, crate) for src, _, _ in rows}), m.group(1) if m else _scrub(why, crate))
    if isinstance(e, shutil.Error):  # its message, or that message split into characters by copytree's errors.extend
        return CopyError([name], _scrub("".join(map(str, e.args[0])), crate))
    return CopyError([_rel(e.filename, crate)] if e.filename else [name], e.strerror or _scrub(str(e), crate))


def _posix(path):
    """a path as an entry names it on every OS: `docs/x.md`, never `docs\\x.md`"""
    return path.replace(os.sep, "/")


def _rel(path, crate):
    return _posix(os.path.relpath(os.fspath(path), crate))


def _scrub(text, crate):
    """text with the checkout's temp prefix taken off its paths (the entry stays the same on every run): the copy
    names them as it was given them, under crate."""
    return text.replace(crate + os.sep, "")


@contextlib.contextmanager
def _import_path(box):
    """PYTHONPATH for the sandbox run, as mutmut's setup_source_paths sets sys.path before it runs pytest in-process:
    mutants/source, mutants/src and mutants/ first (one that does not exist is no harm), so the tests import the copy. They go ahead of
    an inherited PYTHONPATH and of an editable install's .pth, which would import the caller's checkout instead. The
    runner seam takes no env: the run inherits this process's, restored after. Known difference: PYTHONPATH also reaches
    the tests' own subprocesses, which mutmut's in-process sys.path change does not."""
    old = os.environ.get("PYTHONPATH")
    first = [os.path.join(box, "source"), os.path.join(box, "src"), box]
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
                box, box_entries = _sandbox_trial(repo, head, project_dir, cmd, adapter, runner)
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


def _sandbox_trial(repo, head, project_dir, cmd, adapter, runner):
    """the suite once inside R3's mutmut sandbox: ("pass" | "fail", entries). Built in a worktree of its own, as R3 runs
    mutmut in a fresh one: what the plain run left in its checkout (files the tests write) must not reach the copy."""
    with red.worktree(repo, head) as wt:  # python only: its adapter needs no worktree_setup (that is node_modules)
        return _run_in_sandbox(repo, head, wt, project_dir, cmd, adapter, runner)


def _run_in_sandbox(repo, head, wt, project_dir, cmd, adapter, runner):
    crate = os.path.join(wt, project_dir)
    box = _box_dir(project_dir)
    try:
        where, held = sandbox(repo, head, crate, project_dir, wt)
    except CopyFails as e:  # mutmut's copy stops (or never ends) on the same links
        return "fail", [_copy_entry(box, e.paths, "mutmut's copy follows links: a dangling link, one to a dir above "
                                    "it or one into the checkout by an absolute path under tests/ (or a dangling one in "
                                    "a source dir) stops or loops R3 too; drop or fix the link (track its target, make "
                                    "it relative); rerun doctor")]
    except CopyError as e:  # the link check before it reads nothing that raises: os.walk and listdir errors are skipped
        return "fail", [_copy_entry(box, e.paths, f"mutmut's copy into {box} fails on it: {e.why}; fix that in the "
                                    "tree, then rerun doctor")]
    cmd = f"{cmd} {MUTMUT_PYTEST}"
    with _import_path(where):
        brc, bout = runner(shlex.split(cmd), where)
    verdict = adapter.outcome(brc, bout)
    if verdict == "pass":
        return "pass", []
    if verdict == "timeout":  # not a copy problem: no output to read paths from
        return "fail", [report.entry("doctor", "", 0, "sandbox-timeout", "env", "fail",
                                     f"R3's mutmut sandbox run timed out where the plain run passes (`{cmd}` in "
                                     f"{_box_dir(project_dir)})",
                                     f"the suite ran past doctor's {red.TEST_TIMEOUT} s limit there: rerun doctor; if it "
                                     "repeats, find what in the sandbox makes the suite hang", NOT_SKIP)]
    return "fail", [_sandbox_entry(cmd, project_dir, missing(bout, wt, where), held)]


def _copy_entry(box, paths, hint):
    return report.entry("doctor", "", 0, "sandbox-copy", "env", "fail",
                        f"R3's mutmut sandbox cannot be built: mutmut's copy into {box} fails on {_listed(paths)}",
                        hint, NOT_SKIP)


def _listed(paths, cap=10):
    """`a`, `b` … and N more: sorted, at most cap named."""
    named = ", ".join(f"`{p}`" for p in paths[:cap])
    return named + (f" and {len(paths) - cap} more" if len(paths) > cap else "")


def _box_dir(project_dir):
    return "mutants/" if project_dir == "." else f"{project_dir}/mutants/"


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
                path = _posix(os.path.relpath(real, box))
        else:
            path = _posix(os.path.normpath(path))
        if path not in seen:
            seen.append(path)
    return seen


def _sandbox_entry(cmd, project_dir, paths, held):
    where = _box_dir(project_dir)
    if paths:
        found = "missing there: " + ", ".join(f"`{p}`" for p in paths)
    else:
        found = f"no missing path found in the output of `{cmd}` run in {where}"
    kept = "".join(f"; `{top}/` is left out of R3's copy because of the link{'s' if len(links) > 1 else ''} "
                   f"{_listed(links)}" for top, links in sorted(held.items()))
    if any(p.partition("/")[0] in held for p in paths):  # a missing path lies in an entry kept out
        hint = ("a link mutmut cannot copy (dangling, to a dir, or leaving the project dir) keeps its whole top-level "
                "entry out of R3's copy: track its target or remove the link; rerun doctor")
    else:
        hint = (f"R3 copies into {where} only the project dir's tracked top-level entries and mutmut's defaults; "
                "keep the files the tests read inside the project dir, or make the tests not depend on files above it "
                "(a project-dir in a subfolder whose tests read ../ is a known limit); rerun doctor")
    return report.entry("doctor", "", 0, "sandbox-copy", "env", "fail",
                        f"R3's mutmut sandbox fails where the plain run passes ({found}){kept}", hint, NOT_SKIP)


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


def _reads_toml():
    try:
        import tomllib  # noqa: F401 - python 3.11+: adapter files and the stack plan are TOML
    except ImportError:
        return False
    return True


def _repo_adapters(repo, head, paths):
    """({name: (adapter, path)}, own, entries, ignore) as resolve reads them at head (#17): each
    .ekit/adapters/<name>.toml (a file named like a built-in replaces it) and each adapter file the stack plan names,
    read one by one; own: the paths of the adapter files that define a stack of their own (not named like a built-in),
    read or not; entries: a file or a plan that does not read; ignore: the plan's ignore folders. None for the dict
    when this python has no TOML reader and the repo has either."""
    files = [p for p in sorted(paths) if p.rpartition("/")[0] == stack_plan.ADAPTERS_DIR and p.endswith(".toml")]
    if (files or stack_plan.PATH in paths) and not _reads_toml():
        return None, [], [report.entry(
            "doctor", "", 0, "toml", "env", "fail",
            "this python cannot read the repo's adapter files and stack plan (tomllib, python 3.11 or newer): doctor "
            "cannot tell which manifests they cover", "rerun doctor with python 3.11 or newer", NOT_UNPROVEN)], ()
    mine, entries = {}, []
    own = [p for p in files if p.rpartition("/")[2][:-len(".toml")] not in ADAPTERS]
    for path in files:
        try:
            mine.update((n, (a, path)) for n, a in stack_plan.repo_adapters(repo, head, [path]).items())
        except adapter_file.AdapterFileError as e:
            entries.append(report.entry("doctor", path, 0, "adapter-file", "adapter-fix", "fail",
                                        f"the repo's adapter file does not read: {e}",
                                        "repair it (ci-doctor's repair mode, #24), then rerun doctor", NOT_UNPROVEN))
    try:
        plan = stack_plan.at(repo, head)
    except stack_plan.PlanError as e:
        plan = None
        entries.append(report.entry("doctor", stack_plan.PATH, 0, "stack-plan", "adapter-fix", "fail",
                                    f"the stack plan does not read: {e}",
                                    "repair it (ci-doctor's repair mode, #24), then rerun doctor", NOT_UNPROVEN))
    for e in plan.entries if plan else ():
        if e.adapter_ref not in ADAPTERS:
            own += [e.adapter_ref] if e.adapter_ref not in own else []
            if e.adapter is not None:
                mine.setdefault(e.adapter.name, (e.adapter, e.adapter_ref))
    return mine, sorted(own), entries, tuple(plan.ignore) if plan else ()


def _envelope(head, detected, inputs, tried, setup, mode, entries):
    entries = report.finalize(entries)
    summary = f"fail {head} ({len(entries)} problems)" if entries else f"ok {head}"
    return {"ekit": report.ekit_version(), "head": head, "detected": detected, "inputs": inputs, "trial": tried,
            "setup": setup, "mode": mode, "entries": entries, "summary": summary}


def run(repo, head_ref="HEAD", stack=None, project_dir=None, run_trial=True, runner=None):
    try:
        gitio.git(repo, "rev-parse", "--git-dir")
    except gitio.Die:
        raise gitio.Die(f"not a git repo: {repo}")
    head = gitio.resolve(repo, head_ref)
    paths = gitio.git(repo, "ls-tree", "-r", "--name-only", head).splitlines()
    mine, own, entries, ignore = _repo_adapters(repo, head, paths)
    detected = {"stack": None, "project_dir": None}
    inputs, tried, setup, mode = {}, {"tests": "skipped"}, None, None
    if mine is None:  # no TOML reader here: which manifests the repo's adapters cover is unknown, so nothing is routed
        return _envelope(head, detected, inputs, tried, setup, mode, entries)
    adapters = {**ADAPTERS, **{n: a for n, (a, _) in mine.items()}}
    named = stack in adapters  # else a build of a project no adapter covers (detect.BUILDS), or none
    scan = [p for p in paths if not any(stack_plan.holds(f, p) for f in ignore)]  # the plan's ignore: no projects
    found = [c for c in candidates(scan, adapters)
             if (not stack or c[0] == stack) and (not project_dir or c[1] == project_dir)]
    if project_dir and named and not found:
        found = [(stack, project_dir)]
    known = {m for a in adapters.values() for m in a.manifests}
    new = [] if named else detect.projects(repo, head, scan, known, project_dir, stack)
    if found and new:  # one pool, the shallowest wins: the deeper projects are tooling, whichever kind (#23)
        top = min(detect.depth(found[0][1]), detect.depth(new[0]["project_dir"]))
        found = [c for c in found if detect.depth(c[1]) == top]
        new = [p for p in new if detect.depth(p["project_dir"]) == top]
    if new:
        setup = {"projects": new, "own_ci": own_ci(repo, head, paths)}
    if new and len(found) + len(new) > 1:
        mode = "ask"
        names = ", ".join([f"{s} in {d}" for s, d in found]
                          + [f"{p['language']} ({p['build']}, no adapter) in {p['project_dir']}" for p in new])
        entries.append(report.entry("doctor", "", 0, "ambiguous", "needs-human", "fail", f"several projects: {names}",
                                    "pick one with --project-dir, --stack (a built-in, or the build of a project with "
                                    "no adapter) or both", "guessing the project"))
    elif new:
        p = new[0]
        manifest = p["manifests"][0] if p["project_dir"] == "." else f"{p['project_dir']}/{p['manifests'][0]}"
        homes = {path: a for a, path in mine.values()}
        orphans = [x for x in own if x not in homes or not candidates(scan, {"own": homes[x]})]
        if orphans and not (project_dir or stack):  # an adapter of the repo's own finds no project: it may be this one's
            mode = "repair"
            entries.append(report.entry(
                "doctor", manifest, 0, "own-adapter", "adapter-fix", "fail",
                f"no adapter lists `{manifest}` ({p['language']}, {p['build']}), and the repo's own adapter files "
                f"{_listed(orphans)} find no project: one may be meant for it",
                "repair or extend that adapter file (ci-doctor's repair mode, #24) rather than set up a second one; "
                "the owner decides", NOT_UNPROVEN))
        else:
            mode = "setup"
            entries.append(report.entry("doctor", manifest, 0, "no-adapter", "adapter-fix", "fail",
                                        f"no built-in or adapter file covers `{manifest}` ({p['language']}, "
                                        f"{p['build']})", "set up its adapter with ci-doctor's setup mode, starting "
                                        "from `setup`", NOT_UNPROVEN))
    elif len(found) != 1:
        if found:
            mode = "ask"
            names = ", ".join(f"{s} in {d}" for s, d in found)
            entries.append(report.entry("doctor", "", 0, "ambiguous", "needs-human", "fail", f"several projects: {names}",
                                        "pick one with --stack and --project-dir", "guessing the project"))
        elif stack or project_dir:
            asked = " in ".join(x for x in (stack, project_dir) if x)
            names = ", ".join([f"{s} in {d}" for s, d in candidates(scan, adapters)]
                              + [f"{p['language']} ({p['build']}, no adapter) in {p['project_dir']}"
                                 for p in detect.projects(repo, head, scan, known)]) or "none"
            entries.append(report.entry("doctor", "", 0, "no-match", "needs-human", "fail", f"no project found for {asked}",
                                        f"projects here: {names}; passing both --stack and --project-dir overrides detection",
                                        "guessing the project"))
        else:
            entries.append(report.entry("doctor", "", 0, "no-project", "needs-human", "fail",
                                        "no project found: no " + ", ".join(m for a in ADAPTERS.values() for m in a.manifests),
                                        "pass --stack and --project-dir", "guessing the project"))
    elif found[0][0] not in ADAPTERS:
        mode = "repair"
        detected = {"stack": found[0][0], "project_dir": found[0][1]}
        entries.append(report.entry(
            "doctor", mine[found[0][0]][1], 0, "adapter-file", "adapter-fix", "confirm",
            f"`{found[0][0]}` in {found[0][1]} is checked through the repo's adapter file: doctor trial-runs the "
            "built-in stacks only",
            f"prove it with `r0 --stack {found[0][0]} --project-dir {found[0][1]}` (static half; `red --r0` runs the "
            "runtime half) and `drift`; ci-doctor's repair mode (#24) takes it from there", NOT_UNPROVEN))
    else:
        stack, project_dir = found[0]
        mode = "adopt"
        detected = {"stack": stack, "project_dir": project_dir}
        flows = sorted(p for p in paths if WORKFLOW.match(p))
        texts = {p: gitio.blob(repo, head, p) for p in flows}
        callers = [(p, caller_inputs(t)) for p, t in texts.items() if is_caller(t)]
        ci = read_ci(t for p, t in texts.items() if not is_caller(t))
        inputs = wanted_inputs(stack, project_dir, ci, _channel(repo, head, project_dir, paths),
                               scenarios=any(p.startswith(SCENARIOS) for p in paths))
        # a scenario file not of the stack (run.sh) is no test file: it never makes test-paths look missing (#39)
        own = ADAPTERS[stack]()
        seen = [p for p in paths if not p.startswith(SCENARIOS) or own.classify(p, []) is not None]
        entries += caller_entries(callers, inputs, seen) + scenario_entries(stack, callers, inputs, paths)
        if run_trial:
            tried, trial_entries = trial(repo, head, stack, project_dir, runner or red.default_runner())
            entries = trial_entries + entries
    if mode != "ask" and any(e["_key"] in ("adapter-file", "stack-plan") and e["severity"] == "fail" for e in entries):
        mode = "repair"  # a repo adapter file or plan that does not read: repaired before anything is set up on it
    return _envelope(head, detected, inputs, tried, setup, mode, entries)
