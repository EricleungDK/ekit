"""The stack plan and the drift check (#56): `.ekit/stack-plan.toml` compared with the repo's tracked manifests, git only.

`mech-review.py drift --repo R --base B --head H` prints a result envelope whose check `D` is there only when a plan
exists on base or head; resolve's target OS comes from the base plan's entry (#58 wiring). Fixture repos are built
per test; every call goes through cli.main in this process (_kit.run_cli)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

import _kit
from scripts.mech_review import report, stack_plan

PLAN = ".ekit/stack-plan.toml"
DAY = 86400


class Repo:
    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.path = tmp.name
        self.git("init", "-q", "-b", "main")

    def git(self, *args, env=None):
        full = dict(os.environ, **(env or {}))
        return subprocess.run(["git", "-C", self.path, "-c", "user.email=t@t", "-c", "user.name=t",
                               "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True,
                              env=full).stdout

    def commit(self, files, msg="c", when=None):
        """files: {path: text, or None to delete}; when: commit time (unix seconds). Returns the sha."""
        for rel, text in files.items():
            full = os.path.join(self.path, rel)
            if text is None:
                os.remove(full)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", newline="\n") as f:
                f.write(text)
        self.git("add", "-A")
        stamp = {} if when is None else {"GIT_COMMITTER_DATE": f"@{int(when)} +0000", "GIT_AUTHOR_DATE": f"@{int(when)} +0000"}
        self.git("commit", "-q", "--allow-empty", "-m", msg, env=stamp)
        return self.git("rev-parse", "HEAD").strip()


def plan(*entries, ignore=None):
    """plan text: entries are (name, folder, adapter, status[, target-os])."""
    out = []
    if ignore is not None:
        out.append("ignore = [" + ", ".join(json.dumps(x) for x in ignore) + "]")
    for e in entries:
        name, folder, adapter, status = e[:4]
        out += ["", "[[stack]]", f'name = "{name}"', f'folder = "{folder}"', f'adapter = "{adapter}"',
                f'status = "{status}"']
        if len(e) > 4:
            out.append(f'target-os = "{e[4]}"')
    return "\n".join(out) + "\n"


def drift(repo, base, head):
    r = _kit.run_cli(["drift", "--repo", repo.path, "--base", base, "--head", head, "--format", "json"])
    return r, (json.loads(r.stdout) if r.stdout else None)


def fails(env):
    return [e for e in env["entries"] if e["severity"] == "fail"]


class NoPlan(unittest.TestCase):
    def test_no_plan_on_base_or_head_gives_no_drift_check_and_no_entry(self):
        repo = Repo(self)
        base = repo.commit({"pyproject.toml": "[project]\n"})
        head = repo.commit({"web/package.json": "{}", "src/a.py": "x = 1\n"})
        r, env = drift(repo, base, head)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertNotIn("D", env["checks"])
        self.assertEqual(env["entries"], [])
        self.assertEqual(env["summary"], f"pass {head} (0 fail, 0 confirm; ran: none; skipped: R1 R2 R3 R4)")
        self.assertEqual((env["base"], env["head"]), (base, head))


class Uncovered(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.base = self.repo.commit({"api/pyproject.toml": "[project]\n", PLAN: plan(("api", "api", "python", "current"))})

    def test_a_manifest_no_stack_covers_blocks_with_one_adapter_fix_entry(self):
        head = self.repo.commit({"web/package.json": "{}"})
        r, env = drift(self.repo, self.base, head)
        self.assertEqual(r.returncode, 1)
        [e] = env["entries"]
        self.assertEqual((e["check"], e["class"], e["severity"], e["file"], e["line"]),
                         ("D", "adapter-fix", "fail", PLAN, 0))
        self.assertIn("web/package.json", e["problem"])
        self.assertRegex(e["id"], r"^D-[0-9a-f]{8}$")
        self.assertEqual(env["checks"]["D"]["status"], "fail")
        self.assertEqual(env["summary"], f"fail {head} (1 fail, 0 confirm; ran: D; skipped: R1 R2 R3 R4)")

    def test_two_uncovered_manifests_give_exactly_one_entry_naming_both(self):
        head = self.repo.commit({"web/package.json": "{}", "cli/Cargo.toml": "[package]\n"})
        r, env = drift(self.repo, self.base, head)
        self.assertEqual(r.returncode, 1)
        [e] = env["entries"]
        self.assertEqual(e["class"], "adapter-fix")
        self.assertIn("cli/Cargo.toml", e["problem"])
        self.assertIn("web/package.json", e["problem"])

    def test_a_covered_manifest_is_clean(self):
        head = self.repo.commit({"api/src/x.py": "x = 1\n"})
        r, env = drift(self.repo, self.base, head)
        self.assertEqual((r.returncode, env["entries"], env["checks"]["D"]["status"]), (0, [], "pass"))
        self.assertEqual(env["summary"], f"pass {head} (0 fail, 0 confirm; ran: D; skipped: R1 R2 R3 R4)")

    def test_a_manifest_in_the_entrys_folder_that_its_adapter_does_not_claim_is_uncovered(self):
        head = self.repo.commit({"api/package.json": "{}"})
        r, env = drift(self.repo, self.base, head)
        self.assertEqual(r.returncode, 1)
        self.assertIn("api/package.json", fails(env)[0]["problem"])

    def test_a_manifest_deeper_in_the_entrys_folder_is_covered(self):
        head = self.repo.commit({"api/plugins/extra/pyproject.toml": "[project]\n"})
        r, env = drift(self.repo, self.base, head)
        self.assertEqual((r.returncode, env["entries"]), (0, []))

    def test_fixture_vendor_and_build_folders_do_not_count(self):
        files = {f"{d}/package.json": "{}" for d in sorted(stack_plan.SKIP_DIRS)}
        files["web/tests/fixtures/app/Cargo.toml"] = "[package]\n"
        head = self.repo.commit(files)
        r, env = drift(self.repo, self.base, head)
        self.assertEqual((r.returncode, env["entries"]), (0, []))

    def test_the_ignore_list_hides_the_manifests_under_its_folders(self):
        base = self.repo.commit({PLAN: plan(("api", "api", "python", "current"), ignore=["templates/app", "demo"])})
        head = self.repo.commit({"templates/app/package.json": "{}", "templates/app/deep/Cargo.toml": "",
                                 "demo/pyproject.toml": "", "templates/other/package.json": "{}"})
        r, env = drift(self.repo, base, head)
        self.assertEqual(r.returncode, 1)
        [e] = env["entries"]
        self.assertIn("templates/other/package.json", e["problem"])
        for hidden in ("templates/app/package.json", "templates/app/deep/Cargo.toml", "demo/pyproject.toml"):
            self.assertNotIn(hidden, e["problem"])

    def test_the_entry_id_stays_while_the_same_manifests_stay_uncovered(self):
        head = self.repo.commit({"web/package.json": "{}"})
        first = fails(drift(self.repo, self.base, head)[1])[0]["id"]
        later = self.repo.commit({"api/src/y.py": "y = 2\n"})
        self.assertEqual(fails(drift(self.repo, self.base, later)[1])[0]["id"], first)
        more = self.repo.commit({"cli/Cargo.toml": "[package]\n"})
        self.assertNotEqual(fails(drift(self.repo, self.base, more)[1])[0]["id"], first)


MINI_ADAPTER = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.toml")


def mini(target_os=None):
    with open(MINI_ADAPTER) as f:
        text = f.read()
    return text if target_os is None else text.replace('name = "mini"\n', f'name = "mini"\ntarget-os = "{target_os}"\n')


class WhichPlanJudges(unittest.TestCase):
    """The base branch's plan judges a PR; a PR that edits the plan or its adapter files and adds no manifest is
    judged by its own, so the setup PR passes; a PR that adds a manifest and its entry together stays blocked."""

    def setUp(self):
        self.repo = Repo(self)
        self.base = self.repo.commit({"api/pyproject.toml": "[project]\n", "web/package.json": "{}",
                                      PLAN: plan(("api", "api", "python", "current"))})

    def test_on_base_the_manifest_is_uncovered(self):
        r, env = drift(self.repo, self.base, self.base)
        self.assertEqual(r.returncode, 1)
        self.assertIn("web/package.json", fails(env)[0]["problem"])

    def test_a_setup_pr_that_adds_the_entry_for_a_manifest_on_base_passes(self):
        head = self.repo.commit({PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "current"))})
        r, env = drift(self.repo, self.base, head)
        self.assertEqual((r.returncode, env["entries"], env["checks"]["D"]["status"]), (0, [], "pass"))
        self.assertIn("its own plan", env["checks"]["D"]["note"])

    def test_a_setup_pr_with_an_adapter_file_and_the_workflow_caller_passes(self):
        head = self.repo.commit({".ekit/adapters/mini.toml": mini(), "lib/mini.json": "{}",
                                 ".github/workflows/mech-review.yml": "name: mech-review\n"}, "manifest first")
        self.assertEqual(drift(self.repo, self.base, head)[0].returncode, 1)
        base = head
        head = self.repo.commit({PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "current"),
                                            ("lib", "lib", ".ekit/adapters/mini.toml", "current")),
                                 ".github/workflows/mech-review.yml": "name: mech-review\non: pull_request\n"})
        r, env = drift(self.repo, base, head)
        self.assertEqual((r.returncode, env["entries"]), (0, []))

    def test_a_first_plan_that_covers_the_manifests_on_base_passes(self):
        repo = Repo(self)
        base = repo.commit({"pyproject.toml": "[project]\n"})
        head = repo.commit({PLAN: plan(("app", ".", "python", "current"))})
        r, env = drift(repo, base, head)
        self.assertEqual((r.returncode, env["entries"], env["checks"]["D"]["status"]), (0, [], "pass"))

    def test_a_pr_that_adds_a_manifest_and_its_entry_together_is_blocked(self):
        head = self.repo.commit({"cli/Cargo.toml": "[package]\n",
                                 PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "current"),
                                            ("cli", "cli", "rust", "current"))})
        r, env = drift(self.repo, self.base, head)
        self.assertEqual(r.returncode, 1)
        [e] = env["entries"]
        self.assertIn("cli/Cargo.toml", e["problem"])
        self.assertIn("web/package.json", e["problem"])
        self.assertIn("base branch's plan", env["checks"]["D"]["note"])

    def test_a_first_plan_added_with_a_manifest_is_blocked(self):
        repo = Repo(self)
        base = repo.commit({"README.md": "x\n"})
        head = repo.commit({"pyproject.toml": "[project]\n", PLAN: plan(("app", ".", "python", "current"))})
        r, env = drift(repo, base, head)
        self.assertEqual(r.returncode, 1)
        self.assertIn("pyproject.toml", fails(env)[0]["problem"])

    def test_a_pr_that_does_not_touch_the_plan_is_judged_by_the_base_plan(self):
        head = self.repo.commit({"api/src/x.py": "x = 1\n"})
        r, env = drift(self.repo, self.base, head)
        self.assertEqual(r.returncode, 1)
        self.assertIn("base branch's plan", env["checks"]["D"]["note"])

    def test_a_pr_that_edits_only_an_adapter_file_is_judged_by_its_own_plan(self):
        files = {".ekit/adapters/mini.toml": mini(), "lib/mini.json": "{}", "lib/package.json": "{}",
                 PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "current"),
                            ("lib", "lib", ".ekit/adapters/mini.toml", "current"))}
        base = self.repo.commit(files)
        r, env = drift(self.repo, base, base)
        self.assertEqual(fails(env)[0]["problem"], f"manifests no stack in {PLAN} covers: lib/package.json")
        head = self.repo.commit({".ekit/adapters/mini.toml": mini().replace('manifests = ["mini.json"]',
                                                                           'manifests = ["mini.json", "package.json"]')})
        r, env = drift(self.repo, base, head)
        self.assertEqual((r.returncode, env["entries"]), (0, []))
        self.assertIn("its own plan", env["checks"]["D"]["note"])


    def test_a_pr_that_drops_an_adapter_and_adds_the_manifest_only_it_listed_is_judged_by_the_base_plan(self):
        base = self.repo.commit({".ekit/adapters/mini.toml": mini(), "lib/mini.json": "{}",
                                 PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "current"),
                                            ("lib", "lib", ".ekit/adapters/mini.toml", "current"))})
        head = self.repo.commit({"app/mini.json": "{}",
                                 PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "current"))})
        r, env = drift(self.repo, base, head)
        self.assertEqual(r.returncode, 1)
        self.assertIn("app/mini.json", fails(env)[0]["problem"])
        self.assertIn("base branch's plan", env["checks"]["D"]["note"])


def messages(env):
    return env["checks"]["D"]["messages"]


class Messages(unittest.TestCase):
    """Rows 2-4 of #56: messages, never a fail entry."""

    def setUp(self):
        self.repo = Repo(self)

    def test_a_planned_stacks_manifest_appears_and_its_checks_start(self):
        base = self.repo.commit({"api/pyproject.toml": "[project]\n",
                                 PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "planned"))})
        r, env = drift(self.repo, base, base)
        self.assertEqual((r.returncode, messages(env)), (0, []))
        head = self.repo.commit({"web/package.json": "{}"})
        r, env = drift(self.repo, base, head)
        self.assertEqual((r.returncode, env["entries"]), (0, []))
        self.assertEqual(messages(env), ["planned stack `web` (web): its manifest web/package.json is here and its "
                                         "adapter `ts` is proven, so its checks start: set its status to current"])

    def test_a_retiring_stacks_manifest_still_present_is_a_message(self):
        base = self.repo.commit({"package.json": "{}", "tsconfig.json": "{}",
                                 PLAN: plan(("js", ".", "ts", "retiring"), ("app", ".", "ts", "current"))})
        r, env = drift(self.repo, base, base)
        self.assertEqual((r.returncode, env["entries"]), (0, []))
        self.assertEqual(messages(env), ["retiring stack `js` (.): its manifest package.json is still here: finish the "
                                         "migration, then remove its entry"])

    def test_a_stacks_manifest_that_disappears_names_the_entry_to_remove(self):
        base = self.repo.commit({"api/pyproject.toml": "[project]\n", "cli/Cargo.toml": "[package]\n",
                                 PLAN: plan(("api", "api", "python", "current"), ("cli", "cli", "rust", "current"))})
        head = self.repo.commit({"cli/Cargo.toml": None})
        r, env = drift(self.repo, base, head)
        self.assertEqual((r.returncode, env["entries"], env["checks"]["D"]["status"]), (0, [], "pass"))
        self.assertEqual(messages(env), [f"stack `cli` (cli): no Cargo.toml in cli any more: remove the entry `cli` from "
                                         f"{PLAN}"])

    def test_a_manifest_only_under_a_fixture_folder_does_not_keep_a_stack(self):
        base = self.repo.commit({"api/tests/fixtures/pyproject.toml": "[project]\n",
                                 PLAN: plan(("api", "api", "python", "current"))})
        r, env = drift(self.repo, base, base)
        self.assertEqual(messages(env), [f"stack `api` (api): no pyproject.toml, setup.py or setup.cfg in api any more: "
                                         f"remove the entry `api` from {PLAN}"])

    def test_a_planned_stack_with_no_manifest_yet_is_quiet(self):
        base = self.repo.commit({PLAN: plan(("web", "web", "ts", "planned"))})
        r, env = drift(self.repo, base, base)
        self.assertEqual((r.returncode, env["entries"], messages(env)), (0, [], []))


class RetiringReminder(unittest.TestCase):
    """[spec default] a stack `retiring` for more than 30 days, from the plan's git history, gets a reminder."""

    def setUp(self):
        self.repo = Repo(self)
        self.now = time.time()
        self.files = {"package.json": "{}", "tsconfig.json": "{}"}

    def history(self, *steps):
        """steps: (days ago, js status). Returns the last sha."""
        sha = None
        for days, status in steps:
            files = dict(self.files, **{PLAN: plan(("js", ".", "ts", status), ("app", ".", "ts", "current"))})
            sha = self.repo.commit(files, f"js {status}", when=self.now - days * DAY)
        return sha

    def text(self, sha):
        return messages(drift(self.repo, sha, sha)[1])

    def test_retiring_for_more_than_30_days_reminds_to_finish_or_drop_the_migration(self):
        sha = self.history((90, "current"), (41, "retiring"))
        self.assertEqual(self.text(sha), ["retiring stack `js` (.): its manifest package.json is still here: finish the "
                                          "migration, then remove its entry; retiring for 41 days (over 30): finish "
                                          "the migration or drop it"])

    def test_the_time_counts_from_when_it_became_retiring_not_from_the_last_plan_edit(self):
        base = self.history((90, "current"), (45, "retiring"))
        self.repo.commit({PLAN: plan(("js", ".", "ts", "retiring"), ("app", ".", "ts", "current"), ("x", "x", "rust",
                                                                                                    "planned"))},
                         "plan edit", when=self.now - 2 * DAY)
        self.assertIn("retiring for 45 days (over 30)", self.text("HEAD")[0])

    def test_retiring_for_30_days_or_less_is_no_reminder(self):
        sha = self.history((90, "current"), (29, "retiring"))
        self.assertNotIn("days", self.text(sha)[0])

    def test_back_to_current_and_retiring_again_counts_from_the_last_time(self):
        sha = self.history((100, "retiring"), (60, "current"), (10, "retiring"))
        self.assertNotIn("days", self.text(sha)[0])


class Malformed(unittest.TestCase):
    """A bad plan is a usage error (exit 2, nothing on stdout) naming the entry and the field; it never reads clean."""

    def setUp(self):
        self.repo = Repo(self)
        self.base = self.repo.commit({"api/pyproject.toml": "[project]\n", ".ekit/adapters/mini.toml": mini(),
                                      ".ekit/adapters/bad.toml": mini().replace('format = 1\n', 'format = 2\n')})

    def err(self, text, side="head"):
        sha = self.repo.commit({PLAN: text})
        base, head = (self.base, sha) if side == "head" else (sha, sha)
        r = _kit.run_cli(["drift", "--repo", self.repo.path, "--base", base, "--head", head])
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn(f"{PLAN} at {sha[:12]}: ", r.stderr)
        return r.stderr.split(f"{PLAN} at {sha[:12]}: ", 1)[1].strip()

    def test_each_bad_field_names_the_entry_and_the_field(self):
        good = ("api", "api", "python", "current")
        cases = [
            (plan(("api", "api", "python", "done")),
             "stack[0] `api`, field status: `done`: want planned, current or retiring"),
            ('[[stack]]\nname = "api"\nadapter = "python"\nstatus = "current"\n', "stack[0] `api`, field folder: missing"),
            ('[[stack]]\nfolder = "api"\nadapter = "python"\nstatus = "current"\n', "stack[0], field name: missing"),
            (plan(good) + 'colour = "red"\n', "stack[0] `api`, field colour: unknown key"),
            (plan(good, ("api", "web", "ts", "current")), "stack[1] `api`, field name: `api` is already stack[0]"),
            (plan(("my api", "api", "python", "current")), "stack[0], field name: want letters, digits, _ or -"),
            (plan(("api", "../api", "python", "current")),
             "stack[0] `api`, field folder: `../api`: want a folder under the repo root, `/`-separated (no .., not absolute)"),
            (plan(("api", "/api", "python", "current")),
             "stack[0] `api`, field folder: `/api`: want a folder under the repo root, `/`-separated (no .., not absolute)"),
            (plan(("api", "api", "go", "current")),
             "stack[0] `api`, field adapter: `go` is not a built-in stack (python, rust, ts) and no file is there"),
            (plan(("api", "api", ".ekit/adapters/none.toml", "current")),
             "stack[0] `api`, field adapter: `.ekit/adapters/none.toml` is not a built-in stack (python, rust, ts) and "
             "no file is there"),
            (plan(("api", "api", ".ekit/adapters/bad.toml", "current")),
             "stack[0] `api`, field adapter: adapter file .ekit/adapters/bad.toml: format: `2`: want 1"),
            (plan(("api", "api", "python", "current", "beos")),
             "stack[0] `api`, field target-os: `beos`: want linux, macos or windows"),
            (plan(good, ignore=["."]), "ignore[0]: `.` is the repo root: want a folder below it"),
            ('ignore = "demo"\n' + plan(good), "ignore: want a list of folders"),
            ("stack = 1\n", "stack: want an array of tables ([[stack]])"),
            ("stacks = []\n", "stacks: unknown key (want ignore and [[stack]] tables)"),
            ("stack = [1]\n", "stack[0]: want a table"),
            ("[[stack]\n", None),
        ]
        for text, want in cases:
            with self.subTest(want=want):
                got = self.err(text)
                if want is None:
                    self.assertTrue(got.startswith("not valid TOML: "), got)
                else:
                    self.assertEqual(got, want)

    def test_an_adapter_file_that_lists_no_manifest_is_named(self):
        self.repo.commit({".ekit/adapters/none.toml": mini().replace('manifests = ["mini.json"]\n', "")})
        self.assertEqual(self.err(plan(("lib", "lib", ".ekit/adapters/none.toml", "current"))),
                         "stack[0] `lib`, field adapter: adapter file .ekit/adapters/none.toml lists no manifests: the plan "
                         "cannot find its stack")

    def test_a_bad_plan_on_base_is_named_too(self):
        self.assertEqual(self.err(plan(("api", "api", "python", "gone")), side="base"),
                         "stack[0] `api`, field status: `gone`: want planned, current or retiring")

    def test_a_pr_that_fixes_a_bad_base_plan_is_judged_by_its_fixed_plan(self):
        base = self.repo.commit({PLAN: plan(("api", "api", "python", "gone"))})
        head = self.repo.commit({PLAN: plan(("api", "api", "python", "current"))})
        r, env = drift(self.repo, base, head)
        self.assertEqual((r.returncode, env["entries"]), (0, []), r.stderr)

    def test_a_git_error_exits_2(self):
        r = _kit.run_cli(["drift", "--repo", self.repo.path, "--base", "nosuch", "--head", "HEAD"])
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("unknown ref: nosuch", r.stderr)


class OldPython(unittest.TestCase):
    """tomllib is python 3.11+: a plan on an older python is a stated usage error, never clean; no plan needs none."""

    CODE = ("import builtins, sys\n"
            "real = builtins.__import__\n"
            "def imp(name, globals=None, *a, **k):\n"
            "    if name == 'tomllib' and (globals or {}).get('__name__', '').startswith('mech_review'):\n"
            "        raise ImportError('No module named tomllib')\n"
            "    return real(name, globals, *a, **k)\n"
            "builtins.__import__ = imp\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from mech_review.cli import main\n"
            "sys.exit(main(sys.argv[2:]))\n")

    def run_without_tomllib(self, repo, sha):
        return subprocess.run([sys.executable, "-I", "-c", self.CODE, _kit.SCRIPTS, "drift", "--repo", repo.path,
                               "--base", sha, "--head", sha], capture_output=True, text=True)

    def test_a_plan_needs_python_3_11(self):
        repo = Repo(self)
        sha = repo.commit({"pyproject.toml": "", PLAN: plan(("app", ".", "python", "current"))})
        r = self.run_without_tomllib(repo, sha)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("reading the stack plan needs python 3.11 or newer (tomllib)", r.stderr)

    def test_no_plan_needs_no_tomllib(self):
        repo = Repo(self)
        sha = repo.commit({"pyproject.toml": ""})
        r = self.run_without_tomllib(repo, sha)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertNotIn('"D"', r.stdout)


class DriftAt(unittest.TestCase):
    """stack_plan.drift_at(repo, ref): the drift of one tree at a ref, no base (session start, #57). Git only."""

    def test_a_repo_with_no_plan_has_nothing(self):
        repo = Repo(self)
        repo.commit({"package.json": "{}"})
        self.assertEqual(stack_plan.drift_at(repo.path, "HEAD"), stack_plan.Drift(False, [], []))

    def test_the_tracked_tree_at_the_ref_against_its_own_plan(self):
        repo = Repo(self)
        repo.commit({"api/pyproject.toml": "[project]\n", "web/package.json": "{}", "cli/x.rs": "",
                     PLAN: plan(("api", "api", "python", "current"), ("cli", "cli", "rust", "current"))})
        self.assertEqual(stack_plan.drift_at(repo.path, "HEAD"),
                         stack_plan.Drift(True, ["web/package.json"],
                                          [f"stack `cli` (cli): no Cargo.toml in cli any more: remove the entry `cli` "
                                           f"from {PLAN}"]))

    def test_the_retiring_reminder_counts_to_now(self):
        repo = Repo(self)
        now = time.time()
        repo.commit({"package.json": "{}", PLAN: plan(("js", ".", "ts", "retiring"))}, when=now - 40 * DAY)
        [m] = stack_plan.drift_at(repo.path, "HEAD", now=now).messages
        self.assertIn("retiring for 40 days (over 30)", m)
        [m] = stack_plan.drift_at(repo.path, "HEAD", now=now - 20 * DAY).messages
        self.assertNotIn("days", m)


if __name__ == "__main__":
    unittest.main()
