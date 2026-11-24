"""R0, the adapter proof (#21, parent #13): the runtime half. The adapter measured against the test runner, not just
against itself. Two parts, each with its own fingerprint, run where their tools are:
  run  (in `red`, the red-first job)  census: every test the runner lists (the adapter's list command) must be found by
       the scanner, `found/listed` with the misses named, on the fixture project and on the repo at head; assert
       density: the repo's tests with no recognised assert, listed, and above the limit (`[limits] assert-density`,
       default 10%) a needs-human fail until a person accepts the list (ACCEPTED, read at the base); runner controls:
       the fixture tests read pass, fail, none (skipped), build and none (no such test), and the skipped one carries
       the adapter's skip marker (the skip idiom)
  r3   (in `mutants`, shard 0)  the R3 control: the weak-assert fixture gives a MISSED mutant, the strong one none
A part runs only when its fingerprint is not in the cache dir (`--r0 DIR`) as passed: a hash of the part, the adapter
(an adapter file's bytes, a built-in's name), the fixture dir, the ekit version (the plugin version and the engine's own
source), the target OS, the commands the part runs and the version lines of the toolchain programs the adapter names.
A part that passes writes `<part>-<fingerprint>.pass` there; nothing else does, so a cache hit never turns a fail into a
pass. With a cache hit, `red` still runs the census on the PR's changed test files (one listing at head): a miss there
is an `adapter-fix` entry. A part runs only on the stack's target OS (n/a elsewhere).

Version probes run programs, so they keep #19's program rules (mutants._program_path, mutants._in_checkout,
adapter_file.launcher): a program on PATH's absolute entries or an absolute path, never one in the reviewed checkout,
and for an adapter file's programs never an interpreter, shell or launcher. A probe runs `<program> --version` (the
built-ins: ekit's own fixed argv) in an empty temp dir with a minimal environment. A program not probed is named in the
fingerprint's lines, never run. The runner controls and the census run the test command as R1 and R4 do.

Runtime fixtures: `runtime/` in the fixture dir (r0.builtin_fixtures, or `<adapter>.r0/` read at the base):
  controls.json   {"pass": {"file": F, "name": N}, "fail": ..., "skipped": ..., "build": ..., "no-such-test": ...}
                  file: project-relative; name: the adapter's name for the test (no-such-test: a name no test has)
  project/        the runnable project, every file `<name>.r0` (written without the suffix)
  build/          laid over the project for the build control only (a test file that does not build)
  r3/base/        the R3 control's base commit: a project whose suite passes (R3 needs a green baseline)
  r3/weak/, r3/strong/   each laid over r3/base as one PR's head: a production file and a test of it, weak (a
                  MISSED mutant) and strong (none)
The fixture project's tests sit under tests/ (TEST_GLOBS).
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple

from . import adapter_file, gitio, mutants, r0, red, report
from .gitio import Review, blob, changes
from .report import entry

PARTS = ("run", "r3")
BLOCKS = {"run": ("R1", "R2", "R4"), "r3": ("R3",)}  # the checks a failed part leaves unproven: n/a (blocked)
CONTROLS = {"pass": "pass", "fail": "fail", "skipped": "none", "build": "build", "no-such-test": "none"}
ACCEPTED = r0.ACCEPTED  # {"assert-density": {"<stack>": ["<path>::<test name>", ...]}}, read at the base
TEST_GLOBS = ("tests/**",)
PROBE_TIMEOUT = 60
DENSITY = r0.LIMITS["assert-density"][1]
CENSUS = r0.LIMITS["census"][1]
SHOWN = 10  # misses named in a note or an entry, the rest counted
ENGINE = os.path.dirname(os.path.abspath(__file__))

# the built-ins' toolchain programs, as ekit names them (fixed argv, ekit's own): the run part's and R3's
BUILTIN_PROBES = {
    "rust": {"run": (("cargo", "--version"), ("rustc", "--version")), "r3": (("cargo", "mutants", "--version"),)},
    "python": {"run": (("python3", "--version"), ("python3", "-m", "pytest", "--version")),
               "r3": (("mutmut", "--version"),)},
    "ts": {"run": (("node", "--version"),), "r3": (("node", "--version"),)},
}

Runtime = namedtuple("Runtime", "controls project build r3_base weak strong where")  # dirs as {relpath: bytes}


def loads(text):
    """json.loads with the engine's own nesting limit (mutants.MAX_JSON_DEPTH), never Python's RecursionError, whose
    depth differs between interpreters: ValueError when it nests deeper."""
    if mutants._too_deep(text):
        raise ValueError(f"nested too deep (more than {mutants.MAX_JSON_DEPTH} levels)")
    return json.loads(text)


def host_os():
    """the OS this engine runs on, in target-os words."""
    return "macos" if sys.platform == "darwin" else "windows" if sys.platform.startswith(("win", "cygwin")) else "linux"


def _tree(path):
    """{relpath without `.r0`: bytes} of the `.r0` files under path ({} for no dir)."""
    out = {}
    if not os.path.isdir(path):
        return out
    for top, dirs, files in os.walk(path):
        dirs.sort()
        for fn in sorted(files):
            if fn.endswith(r0.SUFFIX):
                full = os.path.join(top, fn)
                rel = os.path.relpath(full, path).replace(os.sep, "/")[:-len(r0.SUFFIX)]
                with open(full, "rb") as f:
                    out[rel] = f.read()
    return out


def load_runtime(fixtures_dir):
    """Runtime of a fixture dir, or None when it has no runtime/ dir. r0.FixtureError: a controls.json that does not read."""
    if not fixtures_dir:
        return None
    rt = os.path.join(fixtures_dir, "runtime")
    if not os.path.isdir(rt):
        return None
    path = os.path.join(rt, "controls.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = loads(f.read())
    except FileNotFoundError:
        raw = {}
    except (OSError, ValueError) as e:
        raise r0.FixtureError(f"R0 runtime fixture {path}: cannot read: {e}") from None
    controls = {}
    for k, v in (raw.items() if isinstance(raw, dict) else ()):
        if k not in CONTROLS:
            continue
        if not (isinstance(v, dict) and isinstance(v.get("file"), str) and isinstance(v.get("name"), str)):
            raise r0.FixtureError(f"R0 runtime fixture {path}: `{k}`: want {{\"file\": ..., \"name\": ...}}")
        controls[k] = (v["file"], v["name"])
    return Runtime(controls, _tree(os.path.join(rt, "project")), _tree(os.path.join(rt, "build")),
                   _tree(os.path.join(rt, "r3", "base")), _tree(os.path.join(rt, "r3", "weak")),
                   _tree(os.path.join(rt, "r3", "strong")), rt)


def _write_tree(root, *trees):
    for tree in trees:
        for rel, raw in tree.items():
            full = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(raw)


# ---- the fingerprint ----

def _digest_dir(h, path):
    if not path or not os.path.isdir(path):
        h.update(b"no dir\0")
        return
    for top, dirs, files in os.walk(path):
        dirs.sort()
        for fn in sorted(files):
            full = os.path.join(top, fn)
            h.update(os.path.relpath(full, path).replace(os.sep, "/").encode("utf-8", "surrogateescape") + b"\0")
            with open(full, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())


def engine_digest():
    """the engine's own source (scripts/mech_review/*.py), hashed: a change to ekit between releases is a change too."""
    h = hashlib.sha256()
    for fn in sorted(os.listdir(ENGINE)):
        if fn.endswith(".py"):
            with open(os.path.join(ENGINE, fn), "rb") as f:
                h.update(fn.encode() + b"\0" + hashlib.sha256(f.read()).digest())
    return h.hexdigest()[:16]


def _words(cmd):
    try:
        return shlex.split(cmd or "")
    except ValueError:
        return []


def probes(adapter, part, cmds):
    """[(argv, from a file)] the version probes of a part: a built-in's fixed argv, or for an adapter file `--version`
    after the program of each command it names (cmds: the part's commands, as the run will use them; the R3 tool's
    declared `version` args when it has them)."""
    if not getattr(adapter, "from_file", False):
        return [(list(a), False) for a in BUILTIN_PROBES.get(adapter.name, {}).get(part, ())]
    out, seen = [], set()
    tool = getattr(adapter, "mutation_tool", None) or {}
    for cmd in cmds:
        words = _words(cmd)
        if not words or words[0] in seen:
            continue
        seen.add(words[0])
        version = tool.get("version") if part == "r3" and tool.get("command") and \
            _words(tool["command"])[:1] == words[:1] else None
        out.append(([words[0]] + list(version or ["--version"]), True))
    return out


def _probe_env():
    keep = ("PATH", "HOME", "SYSTEMROOT", "RUSTUP_HOME", "CARGO_HOME", "RUSTUP_TOOLCHAIN")
    return {**{k: os.environ[k] for k in keep if k in os.environ}, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def probe(argv, from_file, roots):
    """one version line: `<argv>: <first line it prints>`, or `<argv>: not probed (<why>)` when the program rules
    refuse it (not found, in the reviewed checkout, a launcher an adapter file names). Runs in an empty temp dir."""
    label = " ".join(argv)
    if ("/" in argv[0] or "\\" in argv[0]) and not os.path.isabs(argv[0]):
        return f"{label}: not probed (a path in the project dir, which the PR under review can change)"
    prog = mutants._program_path(argv[0])
    if prog is None:
        return f"{label}: not probed (not found on PATH)"
    if from_file and any(adapter_file.launcher(w) for w in (argv[0], prog, os.path.realpath(prog))):
        return f"{label}: not probed (an interpreter, shell or launcher)"
    inside = mutants._in_checkout(prog, roots)
    if inside:
        return f"{label}: not probed (in the reviewed checkout: {inside})"
    with tempfile.TemporaryDirectory(prefix="ekit-r0-probe-") as tmp:
        try:
            r = subprocess.run(red.stubbed([prog] + list(argv[1:]), os.environ.get("MECH_TEST_STUB")), cwd=tmp,
                               env=_probe_env(), capture_output=True, timeout=PROBE_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"{label}: did not answer ({type(e).__name__})"
    lines = [ln.strip() for ln in (r.stdout + r.stderr).decode("utf-8", "replace").splitlines() if ln.strip()]
    return f"{label}: {lines[0][:200] if lines else 'no output'}" + (f" (exit {r.returncode})" if r.returncode else "")


def fingerprint(part, adapter, adapter_raw, fixtures_dir, target_os, cmds, lines, extra=b""):
    """the part's fingerprint (hex) over everything that can change what it proves."""
    h = hashlib.sha256()
    for piece in (b"ekit-r0-runtime-1", part, adapter.name, report.ekit_version(), engine_digest(), target_os):
        h.update((piece if isinstance(piece, bytes) else str(piece).encode()) + b"\0")
    h.update(hashlib.sha256(adapter_raw or b"built-in").digest())
    _digest_dir(h, fixtures_dir)
    for x in list(cmds) + ["--"] + list(lines):
        h.update(x.encode("utf-8", "surrogateescape") + b"\0")
    h.update(hashlib.sha256(extra).digest())
    return h.hexdigest()


def _pass_file(cache_dir, part, fp):
    return os.path.join(cache_dir, f"{part}-{fp}.pass")


def cached(cache_dir, part, fp):
    """True when the cache dir holds this part's pass for exactly this fingerprint (the file names it inside)."""
    try:
        with open(_pass_file(cache_dir, part, fp), encoding="utf-8") as f:
            return loads(f.read()).get("fingerprint") == fp
    except (OSError, ValueError, AttributeError):
        return False


def remember(cache_dir, part, fp, lines):
    os.makedirs(cache_dir, exist_ok=True)
    with open(_pass_file(cache_dir, part, fp), "w", encoding="utf-8") as f:
        json.dump({"part": part, "fingerprint": fp, "probes": list(lines)}, f)


# ---- the census ----

def found_tests(adapter, files):
    """{path: {name: markers}} of the tests the scanner finds in files ({path: text}); a file that does not parse is
    left out (R2 reads it as unparseable)."""
    out = {}
    for path, text in files.items():
        try:
            if adapter.parse_error(text):
                continue
            out[path] = {f.name: list(f.markers) for f in adapter.test_fns(text)}
        except Exception:  # a scanner that crashes on a real file finds nothing there: the census names the misses
            out[path] = {}
    return out


def _same(adapter, listed, name, by_suffix):
    if listed == name:
        return True
    sep = getattr(adapter, "list_separator", None) or "::"
    if by_suffix and listed.endswith(sep + name):
        return True
    ph = getattr(adapter, "name_placeholders", None)
    if ph is not None and ph.search(name):
        parts, at = [], 0
        for m in ph.finditer(name):
            if m.end() > m.start():
                parts.append(re.escape(name[at:m.start()]))
                at = m.end()
        return re.fullmatch(".+".join(parts + [re.escape(name[at:])]), listed) is not None
    return False


def census(adapter, listed, found, paths=None):
    """(found, listed, misses) of the runner's listing against the scanner's tests. listed: [(path or None, name)];
    found: found_tests(); paths: count only listed tests in these files (a listing with no file: all of them)."""
    misses, n = [], 0
    for path, name in listed:
        if paths is not None and path is not None and path not in paths:
            continue
        n += 1
        if path is not None:
            ok = any(_same(adapter, name, f, False) for f in found.get(path, {}))
        else:
            ok = any(_same(adapter, name, f, True) for names in found.values() for f in names)
        if not ok:
            misses.append(f"{path} :: {name}" if path else name)
    return n - len(misses), n, misses


def listing(adapter, runner, cmd, crate, project_dir="."):
    """([(repo path or None, name)], None) of the tests the runner lists in crate, or (None, why not)."""
    argv = adapter.list_argv(cmd) if hasattr(adapter, "list_argv") else None
    if argv is None:
        return None, f"the `{adapter.name}` adapter names no command that lists the runner's tests"
    rc, out = runner(argv, crate)
    if rc is None:
        return None, f"env: `{argv[0]}` not found"
    got = adapter.listed(rc, out, crate)
    if got is None:
        first = next((ln.strip() for ln in (out or "").splitlines() if ln.strip()), f"exit {rc}")
        return None, f"the listing failed (exit {rc}): {first[:200]}"
    pre = "" if project_dir in (".", "") else project_dir + "/"
    return [(None if p is None else pre + p, n) for p, n in got], None


def _shown(items):
    return ", ".join(f"`{x}`" for x in items[:SHOWN]) + (f" and {len(items) - SHOWN} more" if len(items) > SHOWN else "")


def _test_files(rv, sha):
    """{path: text} of this stack's files that can hold tests at sha, under the project dir."""
    repo, _, _, adapter, globs, project_dir = rv
    pre = "" if project_dir == "." else project_dir + "/"
    names = gitio.git(repo, "ls-tree", "-r", "-z", "--full-tree", "--name-only", sha).split("\0")
    out = {}
    for p in names:
        if p and p.startswith(pre) and adapter.classify(p, globs) is not None and adapter.holds_tests(p, globs):
            out[p] = blob(repo, sha, p)
    return out


def _changed_tests(rv):
    repo, mb, head, adapter, globs, project_dir = rv
    pre = "" if project_dir == "." else project_dir + "/"
    return sorted({ch.new for ch in changes(repo, mb, head) if ch.new and ch.new.startswith(pre)
                   and adapter.classify(ch.new, globs) is not None and adapter.holds_tests(ch.new, globs)})


# ---- assert density ----

def asserting(adapter, text):
    """{test name: True when it has a recognised assert} of one file: its own, or one in a helper it calls by name."""
    tests = [f.name for f in adapter.test_fns(text) if "ignore" not in f.markers]
    asserts = adapter.assertions(text)
    calls = adapter.calls(text)
    owners = {a.owner for a in asserts if a.owner and a.fn is None}  # helpers' asserts, outside every test
    return {t: any(a.fn == t for a in asserts) or bool(set(calls.get(t, ())) & owners) for t in tests}


def accepted_list(repo, sha, stack):
    """(the names a person accepted as tests with no recognised assert, at sha (the base): [`path::name`], the list's
    bytes for the fingerprint). A list that does not read accepts none (R0's editing rules name it in its PR)."""
    raw = r0._blob(repo, sha, ACCEPTED)
    table = r0.accepted(raw)[0] or {}
    return list(table.get(stack, [])), raw or b""


def density(adapter, files, accepted):
    """(tests, [`path::name` with no recognised assert], [those accepted])."""
    total, bare = 0, []
    for path in sorted(files):
        try:
            if adapter.parse_error(files[path]):
                continue
            got = asserting(adapter, files[path])
        except Exception:
            continue
        total += len(got)
        bare += [f"{path}::{t}" for t, ok in got.items() if not ok]
    return total, bare, [b for b in bare if b in accepted]


# ---- the runner controls ----

def _limit(adapter, key):
    return (getattr(adapter, "limits", None) or {}).get(key, r0.LIMITS[key][1])


def _case(case, kind, status, want, got, **more):
    return dict({"case": case, "kind": kind, "status": status, "want": want, "got": got}, **more)


def _git(repo, *args):
    return r0._git(repo, *args)


def _repo_of(root, *trees):
    """a throwaway git repo at root holding the trees: its head sha."""
    _git(root, "init", "-q", "--template=")
    _write_tree(root, *trees)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "--no-verify", "-m", "r0 runtime")
    return _git(root, "rev-parse", "HEAD").strip()


def controls(adapter, rt, runner, cmd, src, results):
    """the runner controls and the skip idiom on the fixture project: results gets one case each; returns the fixture
    census (found, listed, misses) or None. src: the reviewed project dir (worktree_setup links its installs)."""
    found = None
    with tempfile.TemporaryDirectory(prefix="ekit-r0-run-") as tmp:
        proj = os.path.join(tmp, "project")
        os.makedirs(proj)
        _repo_of(proj, rt.project)
        adapter.worktree_setup(src, proj, ".")
        use = cmd or adapter.test_cmd_in(proj)
        texts = {p: raw.decode("utf-8", "surrogateescape") for p, raw in rt.project.items()}
        scan = found_tests(adapter, {p: t for p, t in texts.items() if adapter.classify(p, list(TEST_GLOBS)) is not None})
        listed, why = listing(adapter, runner, use, proj)
        if listed is None:
            results.append(_case("census-fixtures", "census", "n/a" if why.startswith("env") else "fail",
                                 "every listed test found", why))
        else:
            found = census(adapter, listed, scan)
            results.append(_case("census-fixtures", "census", "pass" if not found[2] and found[1] else "fail",
                                 "every listed test found", f"{found[0]}/{found[1]} found" +
                                 (f"; missed: {_shown(found[2])}" if found[2] else "") +
                                 ("; the runner listed no test" if not found[1] else ""),
                                 found=found[0], listed=found[1], misses=found[2]))
        build_dir = None
        for name, want in CONTROLS.items():
            case = f"control-{name}"
            if name not in rt.controls:
                results.append(_case(case, "control", "unproven", want, "no such control in controls.json"))
                continue
            path, test = rt.controls[name]
            cwd = proj
            if name == "build":
                build_dir = os.path.join(tmp, "build")
                shutil.copytree(proj, build_dir, symlinks=True)
                _write_tree(build_dir, rt.build)
                cwd = build_dir
            verdict, first = red.run_named(runner, adapter, use, cwd, path, test)
            if verdict == "env":
                results.append(_case(case, "control", "n/a", want, f"env: {first}"))
                continue
            results.append(_case(case, "control", "pass" if verdict == want else "fail", want,
                                 f"{verdict}: {first}" if verdict != want else verdict))
        if "skipped" in rt.controls:
            path, test = rt.controls["skipped"]
            marks = scan.get(path, {}).get(test)
            if marks is None:
                got, ok = f"the adapter finds no test `{test}` in {path}", False
            else:
                ok = "ignore" in marks
                got = "the adapter marks it skipped" if ok else (
                    f"`{test}` runs as skipped (none), but the adapter sees no skip marker on it: it misses this skip "
                    "idiom")
            results.append(_case("skip-idiom", "control", "pass" if ok else "fail", "the skip marker found", got))
    return found


def _r3_case(case, check, ents, weak):
    missed = [e for e in ents if e["check"] == "R3" and e["forbidden"].startswith("MISSED mutant")]
    status = check.get("status")
    note = check.get("note", "")
    if status == "n/a" and ("not installed" in note or "toolchain absent" in note or "not runnable" in note):
        return _case(case, "r3", "n/a", "", f"env: {note}")
    if weak:
        ok = bool(missed)
        want = "a MISSED mutant"
    else:
        ok = not missed and status in ("pass", "partial")
        want = "no MISSED mutant"
    got = f"R3 {status}, {len(missed)} MISSED: {note}"
    return _case(case, "r3", "pass" if ok else "fail", want, got[:400])


def r3_control(adapter, rt, src, mutants_cmd, budget_min, results):
    """the R3 control: R3 on the weak and the strong fixture PR (base: r3/base), each in a throwaway repo."""
    for case, tree, weak in (("r3-weak", rt.weak, True), ("r3-strong", rt.strong, False)):
        if not tree:
            results.append(_case(case, "r3", "unproven", "a MISSED mutant" if weak else "no MISSED mutant",
                                 f"no fixture runtime/r3/{'weak' if weak else 'strong'}/"))
            continue
        with tempfile.TemporaryDirectory(prefix="ekit-r0-r3-") as tmp:
            base = _repo_of(tmp, rt.r3_base)
            _write_tree(tmp, tree)
            _git(tmp, "add", "-A")
            _git(tmp, "commit", "-q", "--allow-empty", "--no-verify", "-m", "r0 r3 head")
            head = _git(tmp, "rev-parse", "HEAD").strip()
            adapter.worktree_setup(src, tmp, ".")  # an install link (node_modules) stays untracked
            rv = Review(tmp, base, head, adapter, list(TEST_GLOBS) + [r0.FIXTURE_DIR + "/**"], ".")
            try:
                check, ents = mutants.run(rv, mutants_cmd, budget_min)
            except gitio.Die:
                raise
            except Exception as e:
                results.append(_case(case, "r3", "fail", "", f"R3 crashed: {type(e).__name__}: {e}"))
                continue
        results.append(_r3_case(case, check, ents, weak))


# ---- a part's result ----

def _status(results):
    sts = [r["status"] for r in results]
    return "fail" if "fail" in sts else "n/a" if "n/a" in sts else "unproven" if "unproven" in sts else "pass"


def _fail_text(r):
    if r["kind"] == "census":
        return f"census `{r['case']}`: {r['got']}"
    if r["case"] == "skip-idiom":
        return f"skip idiom: {r['got']}"
    if r["kind"] == "r3":
        return f"R3 control `{r['case']}` gave {r['got']} (want {r['want']})"
    return f"control `{r['case'][len('control-'):]}` read {r['got']} (want {r['want']})"


def _result(part, adapter, results, fp, lines, where, note_head, extra_entries=(), **fields):
    status = _status(results)
    failed = [r for r in results if r["status"] == "fail"]
    note = f"runtime half ({part}): {note_head}"
    if failed:
        note += "; failed: " + " ".join(r["case"] for r in failed)
    others = [r for r in results if r["status"] in ("n/a", "unproven")]
    if others:
        note += "; " + "; ".join(f"{r['status']} {r['case']}: {r['got']}" for r in others)
    check = {"status": status, "note": note, "half": "runtime", "part": part, "adapter": adapter.name,
             "fingerprint": fp, "probes": list(lines), "cases": results, **fields}
    entries = list(extra_entries)
    if failed:
        cause = (f"R0 runtime half ({part}) failed for the `{adapter.name}` adapter: "
                 + "; ".join(_fail_text(r) for r in failed))
        check.update(blocks=list(BLOCKS[part]), cause=cause)
        entries.append(entry("R0", where, 0, f"runtime:{part}:" + ",".join(r["case"] for r in failed), "adapter-fix",
                             "fail", cause, "repair the adapter (ci-doctor repair mode) in a PR of its own, then re-run "
                                            "R0; the PR under review never edits its own checker",
                             "tuning the adapter or its fixtures until this PR passes"))
    if any(e["severity"] == "fail" for e in entries) and check["status"] != "fail":
        check["status"] = "fail"
    return check, entries


def _where(adapter_path, fixtures_dir):
    """the entry's file: the adapter file, else the fixture dir (ekit's own as `ekit:<path>`)."""
    if adapter_path:
        return adapter_path
    return r0._where(r0.Fixtures("", None, {}, fixtures_dir)) if fixtures_dir else ""


def _wrong_os(part, adapter):
    if adapter.target_os == host_os():
        return None
    return {"status": "n/a", "half": "runtime", "part": part, "adapter": adapter.name,
            "note": f"runtime half ({part}): n/a: the stack runs on {adapter.target_os} (target-os), this machine is "
                    f"{host_os()}: R0 runs where the stack's tests run"}, []


def run_cmds(adapter, cmd, crate):
    """the commands the run part uses: the test command and the listing's."""
    use = cmd or adapter.test_cmd_in(crate)
    out = [use]
    argv = adapter.list_argv(use) if hasattr(adapter, "list_argv") else None
    if argv:
        out.append(" ".join(shlex.quote(a) for a in argv))
    return out


def run_fingerprint(rv, cmd, fixtures_dir, adapter_raw, accepted_raw, crate):
    adapter = rv.adapter
    cmds = run_cmds(adapter, cmd, crate)
    lines = [probe(a, f, (rv.repo,)) for a, f in probes(adapter, "run", cmds)]
    return fingerprint("run", adapter, adapter_raw, fixtures_dir, adapter.target_os, cmds, lines, accepted_raw), lines


def r3_cmds(adapter, mutants_cmd):
    tool = getattr(adapter, "mutation_tool", None) if getattr(adapter, "from_file", False) else None
    if mutants_cmd:
        return [mutants_cmd]
    if tool:
        return [tool["command"]]
    return [{"rust": "cargo mutants", "python": "mutmut", "ts": "node_modules/.bin/stryker"}.get(adapter.name, "")]


def r3_fingerprint(rv, mutants_cmd, fixtures_dir, adapter_raw):
    adapter = rv.adapter
    cmds = r3_cmds(adapter, mutants_cmd)
    lines = [probe(a, f, (rv.repo,)) for a, f in probes(adapter, "r3", cmds)]
    return fingerprint("r3", adapter, adapter_raw, fixtures_dir, adapter.target_os, cmds, lines), lines


def part_fingerprint(rv, part, cmd=None, mutants_cmd=None, fixtures_dir=None, adapter_raw=None):
    """(fingerprint, probe lines) of a part as `red --r0` (run) or `mutants --r0` (r3) computes it: the key the
    workflow's cache step restores before the run."""
    if part == "r3":
        return r3_fingerprint(rv, mutants_cmd, fixtures_dir, adapter_raw)
    accepted_raw = accepted_list(rv.repo, rv.mb, rv.adapter.name)[1]
    with red.worktree(rv.repo, rv.head) as wt:
        crate = os.path.join(wt, rv.project_dir)
        rv.adapter.worktree_setup(rv.repo, wt, rv.project_dir)
        return run_fingerprint(rv, cmd, fixtures_dir, adapter_raw, accepted_raw, crate)


def run_part(rv, runner, cmd, fixtures_dir, adapter_raw=None, cache_dir=None, adapter_path=None):
    """(R0 check, raw entries) of the run part in `red`: the census, assert density and the runner controls when the
    fingerprint has no pass in cache_dir; else only the census of the PR's changed test files."""
    repo, mb, head, adapter, globs, project_dir = rv
    wrong = _wrong_os("run", adapter)
    if wrong:
        return wrong
    where = _where(adapter_path, fixtures_dir)
    accepted, accepted_raw = accepted_list(repo, mb, adapter.name)
    with red.worktree(repo, head) as wt:
        crate = os.path.join(wt, project_dir)
        if not os.path.isdir(crate):
            return {"status": "n/a", "half": "runtime", "part": "run", "adapter": adapter.name,
                    "note": f"runtime half (run): n/a: project dir {project_dir} not in this commit"}, []
        adapter.worktree_setup(repo, wt, project_dir)
        fp, lines = run_fingerprint(rv, cmd, fixtures_dir, adapter_raw, accepted_raw, crate)
        use = cmd or adapter.test_cmd_in(crate)
        hit = bool(cache_dir) and cached(cache_dir, "run", fp)
        changed = _changed_tests(rv)
        files = _test_files(rv, head)
        results = []
        listed, why = (listing(adapter, runner, use, crate, project_dir) if (not hit or changed) else (None, None))
        scan = found_tests(adapter, files) if (not hit or changed) else {}
        census_out = {}
        if hit:
            head_note = f"fingerprint {fp[:12]} passed before (cache): not re-run"
            if changed:
                if listed is None:
                    results.append(_case("census-pr", "census", "n/a" if why.startswith("env") else "fail",
                                         "every listed test in the changed test files found", why))
                else:
                    f, n, miss = census(adapter, listed, scan, set(changed))
                    census_out["pr"] = {"found": f, "listed": n, "misses": miss}
                    results.append(_case("census-pr", "census", "fail" if miss else "pass",
                                         "every listed test in the changed test files found",
                                         f"{f}/{n} found" + (f"; missed: {_shown(miss)}" if miss else "")))
                    head_note += f"; census of the {len(changed)} changed test file(s): {f}/{n} listed tests found"
            else:
                head_note += "; no test file changed"
            return _result("run", adapter, results, fp, lines, where, head_note, census=census_out, ran=False)
        # the full part
        if listed is None:
            results.append(_case("census-repo", "census", "n/a" if why.startswith("env") else "fail",
                                 "every listed test found", why))
            repo_note = f"census: not read ({why})"
        else:
            f, n, miss = census(adapter, listed, scan)
            limit = _limit(adapter, "census")
            ok = n == 0 or f * 100 >= limit * n
            census_out["repo"] = {"found": f, "listed": n, "misses": miss}
            results.append(_case("census-repo", "census", "pass" if ok else "fail",
                                 f"at least {limit}% of the listed tests found",
                                 f"{f}/{n} found" + (f"; missed: {_shown(miss)}" if miss else "")))
            repo_note = f"census: {f}/{n} listed tests found" + (f" (missed: {_shown(miss)})" if miss else "")
        total, bare, ok_bare = density(adapter, files, accepted)
        limit = _limit(adapter, "assert-density")
        left = [b for b in bare if b not in ok_bare]
        pct = (100.0 * len(left) / total) if total else 0.0
        dens = {"tests": total, "no_assert": bare, "accepted": ok_bare, "limit": limit, "percent": round(pct, 1)}
        dens_note = (f"assert density: {len(bare)} of {total} tests with no recognised assert"
                     + (f" ({len(ok_bare)} accepted)" if ok_bare else "") + f", {pct:.0f}% (limit {limit}%)")
        extra = []
        if pct > limit:
            dens_note += f": {_shown(left)}"
            extra.append(entry(
                "R0", ACCEPTED, 0, f"assert-density:{adapter.name}", "needs-human", "fail",
                f"R0 assert density for the `{adapter.name}` adapter: {len(left)} of {total} tests ({pct:.0f}%) have "
                f"no assert the adapter recognises, over the {limit}% limit: {_shown(left)}",
                f"a person decides: if these tests use an assert the adapter does not know, repair the adapter in a PR "
                f"of its own (ci-doctor repair mode); if they are meant to have none, a person accepts the list: add "
                f"each name to {ACCEPTED} under assert-density.{adapter.name} in a PR of its own (R0's editing rules "
                f"make that PR needs-human); it counts from the base branch",
                "adding a dummy assert, or accepting the list in the PR it judges"))
        rt = load_runtime(fixtures_dir)
        fx = None
        if rt is None:
            results.append(_case("controls", "control", "unproven", "the runner controls", "no runtime/ fixtures"))
        else:
            fx = controls(adapter, rt, runner, cmd, os.path.join(repo, project_dir), results)
        if fx is not None:
            census_out["fixtures"] = {"found": fx[0], "listed": fx[1], "misses": fx[2]}
    ctl = [r for r in results if r["kind"] == "control" and r["case"].startswith("control-")]
    head_note = (f"fingerprint {fp[:12]} (ran); {repo_note}"
                 + (f"; fixtures census: {fx[0]}/{fx[1]}" if fx else "") + f"; {dens_note}; controls: "
                 + f"{sum(1 for r in ctl if r['status'] == 'pass')} of {len(CONTROLS)} read right")
    check, entries = _result("run", adapter, results, fp, lines, where, head_note, extra, census=census_out,
                             density=dens, ran=True)
    if check["status"] == "pass" and cache_dir:
        remember(cache_dir, "run", fp, lines)
    return check, entries


def r3_part(rv, mutants_cmd, budget_min, fixtures_dir, adapter_raw=None, cache_dir=None, adapter_path=None):
    """(R0 check, raw entries) of the R3 control in `mutants`, when its fingerprint has no pass in cache_dir."""
    repo, mb, head, adapter, globs, project_dir = rv
    wrong = _wrong_os("r3", adapter)
    if wrong:
        return wrong
    where = _where(adapter_path, fixtures_dir)
    fp, lines = r3_fingerprint(rv, mutants_cmd, fixtures_dir, adapter_raw)
    if cache_dir and cached(cache_dir, "r3", fp):
        return _result("r3", adapter, [], fp, lines, where, f"fingerprint {fp[:12]} passed before (cache): not re-run",
                       ran=False)
    rt = load_runtime(fixtures_dir)
    results = []
    if rt is None:
        results.append(_case("r3-weak", "r3", "unproven", "a MISSED mutant", "no runtime/ fixtures"))
    else:
        r3_control(adapter, rt, os.path.join(repo, project_dir), mutants_cmd, budget_min, results)
    got = {r["case"]: r for r in results}
    head_note = f"fingerprint {fp[:12]} (ran); R3 control: " + ", ".join(
        f"{c} {got[c]['status']}" for c in ("r3-weak", "r3-strong") if c in got)
    check, entries = _result("r3", adapter, results, fp, lines, where, head_note, ran=True)
    if check["status"] == "pass" and cache_dir:
        remember(cache_dir, "r3", fp, lines)
    return check, entries
