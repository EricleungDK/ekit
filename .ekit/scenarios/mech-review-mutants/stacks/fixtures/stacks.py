"""Shared setup for the two-stack R3 scenarios (imported by their run.py; not a scenario). cwd = the scenario's temp dir.

The kit as a user gets it: a clone of the tree under test. A repo with two stacks: `api` (python, folder api/) and
`web` (rust, folder web/); the head changes production code in both. Fake tools (MECH_TEST_STUB): the R3 cap
scenarios' fake cargo-mutants (a 12-mutant listing) and the python shard-count scenarios' fake mutmut + pytest.
The report step posts to the kit clone's fake GitHub (as the mech-waive scenario uses it), never the network.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time

TMP = os.getcwd()
REPO_UNDER_TEST = os.environ["EKIT_REPO"]
KIT = os.path.join(TMP, "kit")
R = os.path.join(TMP, "repo")


def fail(msg):
    sys.exit(f"ASSERT FAILED: {msg}")


def eq(what, got, want):
    if got != want:
        fail(f"{what}: expected [{want}] got [{got}]")


def has(what, text, part):
    if part not in text:
        fail(f"{what}: expected output to contain [{part}], got [{text}]")


def hasnt(what, text, part):
    if part in text:
        fail(f"{what}: output must not contain [{part}], got [{text}]")


ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
           HOME=os.path.join(TMP, "home"))
ENV.pop("MECH_TEST_STUB", None)
os.makedirs(ENV["HOME"], exist_ok=True)


def sh(argv, cwd=None, env=None, check=True):
    p = subprocess.run(argv, cwd=cwd, env=env or ENV, capture_output=True, text=True)
    if check and p.returncode != 0:
        fail(f"setup: {' '.join(argv)} exit {p.returncode}: {p.stderr}")
    return p


def git(*a):
    return sh(["git", "-C", R, *a]).stdout.strip()


def write(path, text):
    path = os.path.join(R, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


# the install
sh(["git", "-c", "advice.detachedHead=false", "clone", "-q", REPO_UNDER_TEST, KIT])
MR = os.path.join(KIT, "scripts", "mech-review.py")
MC = os.path.join(KIT, "scripts", "mech-comment.py")
FAKE_GH = os.path.join(KIT, "tests", "fixtures", "mech-waive", "fake_github.py")
SCN = os.path.join(KIT, ".ekit", "scenarios")
CM = os.path.join(TMP, "fake-cargo-mutants")
MM = os.path.join(TMP, "fake-mutmut")
shutil.copy(os.path.join(SCN, "mech-review-mutants", "fixtures", "fake_cargo_mutants.py"), CM)
shutil.copy(os.path.join(SCN, "mech-review-baseline", "python-cost", "fixtures", "fake_mutmut.py"), MM)
os.chmod(CM, 0o755)
os.chmod(MM, 0o755)
LIST = os.path.join(TMP, "list12.json")
with open(LIST, "w") as f:
    f.write(sh([sys.executable, os.path.join(SCN, "mech-review-mutants", "fixtures", "gen_list.py"), "2"]).stdout)

# the user's repo: api/ (python) and web/ (rust)
os.makedirs(R)
sh(["git", "init", "-q", "-b", "main", R])
write("api/pyproject.toml", '[project]\nname = "calc"\nversion = "0.0.1"\n\n[tool.pytest.ini_options]\npythonpath = ["src"]\n')
write("api/src/calc/__init__.py", "")
write("api/src/calc/core.py", "def f1(n):\n    return n+1\n\n\ndef f2(n):\n    return n+2\n")
write("api/tests/test_core.py", "from calc.core import f1\n\n\ndef test_all():\n    assert f1(1) == 2\n")
write("web/Cargo.toml", '[package]\nname = "x"\nversion = "0.1.0"\n')
write("web/src/lib.rs", "pub fn add(a: i32, b: i32) -> i32 { a + b }\n")
write("web/tests/a.rs", "#[test]\nfn adds() {\n    assert_eq!(add(1, 2), 3);\n}\n")
git("add", "-A")
git("commit", "-qm", "base")
B = git("rev-parse", "HEAD")
write("api/src/calc/core.py", "def f1(n):\n    return n + 1\n\n\ndef f2(n):\n    return n + 2\n")
write("web/src/lib.rs", "pub fn add(a: i32, b: i32) -> i32 { a + b } // fixed\n")
git("commit", "-qam", "head")
H = git("rev-parse", "HEAD")

LEGS = {"api": ("python", "api", MM), "web": ("rust", "web", CM)}


def run(argv, env=None):
    """mech-review.py <argv> in the user's repo: (exit code, parsed stdout or None, stderr)"""
    p = subprocess.run([sys.executable, "-I", MR, *argv], cwd=R, env=env or ENV, capture_output=True, text=True)
    hasnt(f"no traceback from {argv[0]}", p.stderr, "Traceback")
    try:
        out = json.loads(p.stdout) if p.stdout.strip() else None
    except ValueError:
        out = None
    return p.returncode, out, p.stderr


def shard(leg, k, n, survive=None, extra=()):
    """the mutants job of one leg and shard, as the workflow runs it; returns the result file's path"""
    stack, pdir, stub = LEGS[leg]
    env = dict(ENV, MECH_TEST_STUB=stub, FAKE_LIST=LIST)
    if survive:
        env["FAKE_MISS" if stack == "rust" else "FAKE_SURVIVE"] = survive
    rc, out, err = run(["mutants", "--repo", R, "--base", B, "--head", H, "--stack", stack, "--project-dir", pdir,
                        "--test-paths", f"{pdir}/tests/**", "--shard", f"{k}/{n}", *extra], env)
    if out is None:
        fail(f"mutants {leg} {k}/{n} printed no result (exit {rc}): {err}")
    path = os.path.join(TMP, f"{leg}-{k}of{n}{'-miss' if survive else ''}.json")
    with open(path, "w") as f:
        json.dump(out, f)
    return path


def edit(path, name, fn):
    """a copy of a result file with fn applied to its JSON: the result as a broken wiring or tool would leave it"""
    with open(path) as f:
        d = json.load(f)
    fn(d)
    new = os.path.join(TMP, name)
    with open(new, "w") as f:
        json.dump(d, f)
    return new


def merge(leg, shards, envelopes, project_dir=True, stack=None):
    """the report job's merge of one leg: envelopes is a list of (k, file); returns (exit code, result)"""
    st, pdir, _ = LEGS[leg]
    argv = ["merge", "--repo", R, "--base", B, "--head", H, "--stack", stack or st, "--shards", str(shards)]
    if project_dir:
        argv += ["--project-dir", pdir]
    for k, f in envelopes:
        argv += ["--envelope", f"{k}={f}"]
    rc, out, err = run(argv)
    if out is None:
        fail(f"merge {leg} printed no result (exit {rc}): {err}")
    return rc, out


def save(name, d):
    path = os.path.join(TMP, name)
    with open(path, "w") as f:
        json.dump(d, f)
    return path


def r3(out):
    return out["checks"]["R3"]["status"]


def tested(out):
    c = out["checks"]["R3"]
    return f"{c.get('tested')}/{c.get('total')}"


def problems(out, check=None):
    return [e["problem"] for e in out["entries"] if check is None or e["check"] == check]


# each leg's guard (R2) and the repo's drift result, for the report
R2 = {}
for leg, (stack, pdir, _) in LEGS.items():
    rc, out, err = run(["r2", "--repo", R, "--base", B, "--head", H, "--stack", stack, "--project-dir", pdir,
                        "--test-paths", f"{pdir}/tests/**"])
    eq(f"r2 {leg} exit", rc, 0)
    R2[leg] = save(f"r2-{leg}.json", out)
rc, out, err = run(["drift", "--repo", R, "--base", B, "--head", H])
eq("drift exit", rc, 0)
DRIFT = save("drift.json", out)


class FakeGitHub:
    """the kit clone's fake GitHub API on a local port; report() is the report job's comment step"""

    def __init__(self):
        self.state = os.path.join(TMP, "gh-state.json")
        port = os.path.join(TMP, "gh-port")
        with open(self.state, "w") as f:
            json.dump({"head": H, "comments": [], "runs": [], "jobs": {}}, f)
        self.srv = subprocess.Popen([sys.executable, FAKE_GH, self.state, os.path.join(TMP, "gh-writes.log"), port],
                                    env=ENV)
        for _ in range(100):
            if os.path.exists(port) and open(port).read().strip():
                break
            time.sleep(0.1)
        else:
            fail("setup: the fake GitHub did not start")
        self.env = dict(ENV, GITHUB_API_URL=f"http://127.0.0.1:{open(port).read().strip()}",
                        GITHUB_REPOSITORY="o/r", GITHUB_TOKEN="t")

    def report(self, rows):
        """rows: [(name, stack, project_dir, {job: file})]; returns (exit code, sticky comment body)"""
        stacks = save("stacks.json", [{"name": n, "stack": s, "project_dir": d, "envelopes": e} for n, s, d, e in rows])
        p = subprocess.run([sys.executable, MC, "--pr", "1", "--head", H, "--stacks", stacks,
                            "--envelope", f"drift={DRIFT}"], cwd=R, env=self.env, capture_output=True, text=True)
        hasnt("no traceback from mech-comment", p.stderr, "Traceback")
        with open(self.state) as f:
            bodies = [c["body"] for c in json.load(f)["comments"] if c["user"]["type"] == "Bot"]
        eq("one sticky comment", len(bodies), 1)
        return p.returncode, bodies[0]

    def close(self):
        self.srv.kill()


def entry_rows(body):
    """the entries table's rows of a comment: [{id, stack, severity, problem}]"""
    rows = []
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0] not in ("id", "---") and not cells[0].startswith("-"):
            rows.append({"id": cells[0], "stack": cells[1], "severity": cells[2], "problem": cells[4]})
    return rows


def checkout_untouched():
    eq("caller checkout untouched", git("status", "--porcelain"), "")
    eq("caller HEAD unchanged", git("rev-parse", "HEAD"), H)
