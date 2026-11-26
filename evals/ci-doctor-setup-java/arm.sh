# Sourced by each ci-doctor-setup-* setup.sh after its scaffold commit (#23). Arms the grader support: whenever a ref
# moves (commit, reset, checkout, merge, rebase, in any worktree), .git/ekit-eval/verdict.py (written below: a heredoc,
# so the kit tracks no python file outside its test paths) grades the setup branch and writes
# .git/ekit-eval/verdict.txt, which the regex graders read. The trigger is evals/git-shim.sh, which evals/run.sh puts
# first on PATH as `git` (the eval sandbox turns git hooks off). $1: the case's expect.json (the script's header). The
# kit's path is data in a file, never shell text.
arm_verdict() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  mkdir -p .git/ekit-eval
  printf '%s' "$(cd "$here/../.." && pwd -P)" > .git/ekit-eval/kit
  printf '%s\n' "$1" > .git/ekit-eval/expect.json
  git rev-parse HEAD > .git/ekit-eval/start
  cat > .git/ekit-eval/verdict.py <<'PY'
# The end state of a ci-doctor setup eval (#23), written to .git/ekit-eval/verdict.txt for the regex graders after
# every ref move (evals/git-shim.sh). Graded: the setup branch, the newest branch other than main that holds a commit
# beyond the scaffold's (.git/ekit-eval/start), whichever worktree or HEAD the agent ends on. expect.json: {"status": "current" |
# "planned", "folder", "target_os", "ci": "keep" | "write", and for a repo with tests "tests" (the names the adapter
# must read), "test_files" (the paths that hold them) and "test_paths" (their glob)}. `setup: yes` needs every line it
# checks at once. Git and the kit's own engine only (r0 static half, r2 for the census, drift; doctor's workflow
# reader); nothing printed. A harness problem (no kit, no tomllib) says `harness:`. An adapter or fixtures copied from
# the kit's reference (tests/fixtures/adapters/java.toml, java.r0) is no setup: `copied: yes`.
# A known limit: the agent under test can open this grading (the kit's evals/, the scaffold's .git/ekit-eval/).
import json
import os
import re
import subprocess
import sys
import tempfile

here = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True,
                      text=True).stdout.strip()  # the main checkout's .git, from it or from any linked worktree
repo = os.path.dirname(here)
env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                                                        "GIT_OBJECT_DIRECTORY", "GIT_PREFIX")}
CALLER = "EricleungDK/ekit/.github/workflows/mech-review.yml@"
WAIVER = "EricleungDK/ekit/.github/workflows/mech-waive.yml@"


def git(*a, extra=None):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, env=dict(env, **(extra or {})))


def read(name):
    with open(os.path.join(here, "ekit-eval", name), encoding="utf-8") as f:
        return f.read()


expect, kit, start = json.loads(read("expect.json")), read("kit"), read("start").strip()
engine = os.path.join(kit, "scripts", "mech-review.py")
sys.path.insert(0, os.path.join(kit, "scripts"))
try:
    from mech_review import doctor, stack_plan  # the kit's own workflow reader and folder rule
except Exception as e:
    doctor = stack_plan = None
    kit_error = f"{type(e).__name__}: {e}"
lines, ok = [], []

# the setup branch, among the branches other than main (the PR's base) that hold a new commit: the one the main
# checkout's HEAD is on, else the newest whose tree holds a stack plan, else the newest
heads = [x.split(" ", 1) for x in git("for-each-ref", "--sort=-committerdate", "--format=%(objectname) %(refname:short)",
                                      "refs/heads/").stdout.splitlines()]
setup = [(sha, name) for sha, name in heads if name != "main"
         and git("rev-list", "--count", f"{start}..{sha}").stdout.strip() not in ("", "0")]
on = git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
setup.sort(key=lambda b: (b[1] != on, git("cat-file", "-e", f"{b[0]}:.ekit/stack-plan.toml").returncode != 0))
ref, branch = setup[0] if setup else (None, None)
lines.append(f"branch: {branch}" if branch else "branch: none (no branch other than main holds a new commit)")
ok.append(bool(ref))
main_moved = git("rev-parse", "refs/heads/main").stdout.strip() != start
lines.append(f"main: {'moved' if main_moved else 'untouched'}")
ok.append(not main_moved)
# every commit beyond the scaffold's on any ref, any worktree's HEAD or any reflog (a detached HEAD, a deleted branch);
# a stash's own commits (its entry, and the index and untracked commits it holds) are no commit of the work
commits = set(git("rev-list", "--all", "--reflog", "--not", start).stdout.split())
for w in git("reflog", "show", "--format=%H", "refs/stash").stdout.split():
    commits -= {w, *git("rev-list", "--parents", "-n", "1", w).stdout.split()[2:]}
lines.append(f"new-commits: {len(commits)}")


def folder(v):
    try:
        return stack_plan._folder(v, "folder")
    except Exception:
        return None


entry, adapter = None, {}
try:
    import tomllib
except ImportError:
    tomllib = None
if not tomllib or not stack_plan:
    lines.append("entry: not read: harness: " + ("no tomllib (python 3.11 or newer runs the verdict)" if not tomllib
                                                 else f"the kit's engine does not import ({kit_error})"))
elif ref:
    try:
        stacks = tomllib.loads(git("show", f"{ref}:.ekit/stack-plan.toml").stdout).get("stack", [])
    except Exception as e:  # no plan, or not TOML
        stacks = []
        lines.append(f"plan: does not read ({type(e).__name__})")
    mine = [s for s in stacks if isinstance(s, dict) and folder(s.get("folder")) == folder(expect["folder"])
            and str(s.get("adapter", "")).endswith(".toml")]
    entry = mine[0] if mine else None
    if entry:
        shown = git("show", f"{ref}:{entry['adapter']}")
        try:
            adapter = tomllib.loads(shown.stdout) if shown.returncode == 0 else {}
        except Exception:
            adapter = {}
        lines.append(f"entry: {entry.get('name')} adapter {entry['adapter']} status {entry.get('status')}")
    else:
        lines.append(f"entry: none (no plan entry for folder {expect['folder']!r} naming an adapter file)")
else:
    lines.append("entry: none (no setup branch)")
ok.append(bool(entry) and entry.get("status") == expect["status"])
target = (entry or {}).get("target-os") or adapter.get("target-os") or "linux"
lines.append(f"target-os: {target}")
ok.append(target == expect["target_os"])


def same(text):
    """text with comments (#, //, /* */) and whitespace dropped: a copy reads the same, whatever its comments"""
    return re.sub(r"\s+", "", re.sub(r"/\*[\s\S]*?\*/|//[^\n]*|#[^\n]*", "", text))


def copied(path):
    """`copied: no`, or `copied: yes (...)` when the adapter file is the kit's reference, or more than half of the
    reference's fixture files are there, the same, under the same name in the adapter's fixture dir"""
    # A known limit (the owner's call, #23): a text check, so a renamed copy (the stack's name and the fixtures' class
    # names changed) reads `copied: no`. The orchestrator reads the run's trace before it uses a generated adapter.
    ref_dir = os.path.join(kit, "tests", "fixtures", "adapters")
    if not os.path.isfile(os.path.join(ref_dir, "java.toml")):
        return "copied: not checked: harness: the kit's tests/fixtures/adapters/java.toml is not there"
    with open(os.path.join(ref_dir, "java.toml"), encoding="utf-8") as f:
        why = [f"{path} is the kit's tests/fixtures/adapters/java.toml"] \
            if same(git("show", f"{ref}:{path}").stdout) == same(f.read()) else []
    mine = path[:-len(".toml")] + ".r0/"
    ref_files, equal = [], 0
    for root, _, names in os.walk(os.path.join(ref_dir, "java.r0")):
        for fn in names:
            rel = os.path.relpath(os.path.join(root, fn), os.path.join(ref_dir, "java.r0")).replace(os.sep, "/")
            ref_files.append(rel)
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                theirs = git("show", f"{ref}:{mine}{rel}")
                equal += theirs.returncode == 0 and same(theirs.stdout) == same(f.read())
    if equal * 2 > len(ref_files):
        why.append(f"{equal} of {len(ref_files)} fixture files are java.r0's")
    return f"copied: yes ({'; '.join(why)})" if why else "copied: no"


def engine_run(*args, base=None, head=None):
    r = subprocess.run([sys.executable, "-I", engine, *args, "--repo", repo, "--base", base or ref, "--head",
                        head or ref], capture_output=True, text=True, env=env)
    try:
        return r, json.loads(r.stdout)
    except ValueError:
        return r, None


name = str(adapter.get("name") or "")
if not os.path.isfile(engine) or not doctor:
    why = f"the kit's scripts/mech-review.py is not at {kit!r}" if not os.path.isfile(engine) else kit_error
    lines += [f"r0: not run: harness: {why} (not the model's doing)", "census: not run: harness",
              "copied: not checked: harness", "drift: not run: harness"]
    ok.append(False)
elif not ref or not name:
    lines += ["r0: not run (no plan entry with an adapter file that reads on the setup branch)", "census: not run",
              "copied: not checked"]
    lines.append("drift: not run (no setup branch)" if not ref else "drift: see r0")
    ok.append(False)
else:
    r, result = engine_run("r0", "--stack", name, "--project-dir", expect["folder"])
    r0 = (result or {}).get("checks", {}).get("R0") or {}
    if r0.get("status") == "pass":
        lines.append(f"r0: pass ({r0.get('note')})")
    else:
        why = [e.get("problem") for e in (result or {}).get("entries", [])] or [r0.get("note")]
        why = why if why != [None] else [(r.stderr.strip().splitlines() or ["no output"])[0]]
        lines.append(f"r0: not pass (exit {r.returncode}, R0 {r0.get('status')}: {'; '.join(why)[:400]})")
    ok.append(r0.get("status") == "pass")
    # the census: the repo's own test files deleted on a commit no ref names; R2 must name each of their tests removed
    if expect.get("tests"):
        with tempfile.TemporaryDirectory() as tmp:
            index = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
            git("read-tree", ref, extra=index)
            git("rm", "-q", "-r", "--cached", "--ignore-unmatch", *expect["test_files"], extra=index)
            tree = git("write-tree", extra=index).stdout.strip()
            scratch = git("commit-tree", tree, "-p", ref, "-m", "census").stdout.strip()
        r, result = engine_run("r2", "--stack", name, "--project-dir", expect["folder"], "--test-paths",
                               expect["test_paths"], head=scratch)
        removed = {e["problem"].split("`")[1] for e in (result or {}).get("entries", [])
                   if e.get("problem", "").startswith("test fn `")}
        parts = lambda n: re.findall(r"[\w$]+", n)  # noqa: E731 - a name under any separator: `A.b`, `A > b`, `A#b`
        read_all = [t for t in expect["tests"] if any(parts(x)[-len(parts(t)):] == parts(t) for x in removed)]
        missed = [t for t in expect["tests"] if t not in read_all]
        lines.append(f"census: {len(read_all)}/{len(expect['tests'])} of the repo's tests read"
                     + (f"; missed: {', '.join(missed)}" if missed else ""))
        ok.append(not missed)
    else:
        lines.append("census: no repo tests yet")
    # the kit's hand-written reference adapter (#22) and its R0 fixtures, copied in place of a generated one
    lines.append(copied(entry["adapter"]))
    ok.append(lines[-1] == "copied: no")
    r, result = engine_run("drift", "--format", "json")
    d = (result or {}).get("checks", {}).get("D") or {}
    clean = r.returncode == 0 and d.get("status") == "pass" and not (result or {}).get("entries")
    lines.append(f"drift: {'clean' if clean else 'not clean'} (exit {r.returncode}, "
                 + (f"D {d.get('status')}, {len((result or {}).get('entries', []))} entries)" if d else "no plan: no D)"))
    ok.append(clean)


def jobs_at(rev):
    """{(workflow file, job id): its lines joined, comments dropped} at rev"""
    if not rev or not doctor:
        return {}, {}
    files = [x.split("\t", 1) for x in git("ls-tree", rev, ".github/workflows/").stdout.splitlines()]
    blobs = {p: meta.split()[2] for meta, p in files if p.endswith((".yml", ".yaml"))}
    out = {}
    for p in blobs:
        text = git("show", f"{rev}:{p}").stdout
        found = doctor.jobs(text)  # None: flow style, unread: the file's own lines, comments dropped, are one job
        for j, body in (found.items() if found is not None else
                        [("(unread)", [x for x in text.splitlines() if not x.lstrip().startswith("#")])]):
            out[(p, j)] = "\n".join(body)
    return blobs, out


(after, jobs), (before, old) = jobs_at(ref), jobs_at(start)
caller = any(CALLER in t for t in jobs.values())
lines.append(f"caller: {'yes' if caller else 'no'}")
ok.append(caller)
kept = bool(ref) and all(after.get(p) == sha for p, sha in before.items())
lines.append(f"ci-kept: {'yes' if kept else 'no'}")
ok.append(kept)
added = {k: t for k, t in jobs.items() if k not in old and CALLER not in t and WAIVER not in t}
test_cmd = (adapter.get("commands") or {}).get("test") if isinstance(adapter.get("commands"), dict) else None
where = ", ".join(f"{p} job {j}" for p, j in sorted(added))
if not added:
    lines.append("base-jobs: none")
elif test_cmd and any(test_cmd in t for t in added.values()):
    lines.append(f"base-jobs: yes ({where} run `{test_cmd}`)")
else:
    lines.append(f"base-jobs: no test command ({where}: none runs the adapter's [commands] test)")
ok.append(lines[-1].startswith("base-jobs: yes" if expect["ci"] == "write" else "base-jobs: none"))
lines.append(f"setup: {'yes' if all(ok) else 'no'}")
with open(os.path.join(here, "ekit-eval", "verdict.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
PY
  python3 -I .git/ekit-eval/verdict.py  # the start state's verdict
}
