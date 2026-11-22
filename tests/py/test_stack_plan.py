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



class ManifestNamesFromBothPlans(unittest.TestCase):
    """Review round 2, findings 1-3: a file is a manifest when a built-in or the base or the head plan's adapter files
    list its name, whichever plan judges, so a PR cannot hide a manifest by adding or dropping the adapter that lists it."""

    def setUp(self):
        self.repo = Repo(self)
        self.lib = ("lib", "lib", ".ekit/adapters/mini.toml", "current")
        self.api = ("api", "api", "python", "current")

    def test_a_new_adapter_its_entry_and_its_manifest_together_are_blocked(self):
        base = self.repo.commit({"api/pyproject.toml": "[project]\n", PLAN: plan(self.api)})
        head = self.repo.commit({".ekit/adapters/mini.toml": mini(), "lib/mini.json": "{}", PLAN: plan(self.api, self.lib)})
        r, env = drift(self.repo, base, head)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(fails(env)[0]["problem"], f"manifests no stack in {PLAN} covers: lib/mini.json")

    def test_the_same_with_no_plan_on_base_is_blocked(self):
        base = self.repo.commit({"README.md": "x\n"})
        head = self.repo.commit({".ekit/adapters/mini.toml": mini(), "lib/mini.json": "{}", PLAN: plan(self.lib)})
        r, env = drift(self.repo, base, head)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(fails(env)[0]["problem"], f"manifests no stack in {PLAN} covers: lib/mini.json")

    def test_an_uncovered_manifest_of_a_new_adapter_cannot_reach_the_base(self):
        base = self.repo.commit({"api/pyproject.toml": "[project]\n", PLAN: plan(self.api)})
        head = self.repo.commit({".ekit/adapters/mini.toml": mini(), "lib/mini.json": "{}", "other/mini.json": "{}",
                                 PLAN: plan(self.api, self.lib)})
        r, env = drift(self.repo, base, head)
        self.assertEqual(r.returncode, 1)
        self.assertIn("other/mini.json", fails(env)[0]["problem"])

    def test_a_manifest_name_added_to_an_adapter_counts_outside_its_entrys_folder(self):
        base = self.repo.commit({"api/pyproject.toml": "[project]\n", ".ekit/adapters/mini.toml": mini(),
                                 "lib/mini.json": "{}", PLAN: plan(self.api, self.lib)})
        head = self.repo.commit({".ekit/adapters/mini.toml": mini().replace('manifests = ["mini.json"]',
                                                                           'manifests = ["mini.json", "x.json"]'),
                                 "zzz/x.json": "{}"})
        r, env = drift(self.repo, base, head)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(fails(env)[0]["problem"], f"manifests no stack in {PLAN} covers: zzz/x.json")

    def test_dropping_an_adapter_file_entry_while_its_code_stays_leaves_the_manifest_uncovered(self):
        base = self.repo.commit({"api/pyproject.toml": "[project]\n", ".ekit/adapters/mini.toml": mini(),
                                 "lib/mini.json": "{}", PLAN: plan(self.api, self.lib)})
        head = self.repo.commit({PLAN: plan(self.api)})
        r, env = drift(self.repo, base, head)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(fails(env)[0]["problem"], f"manifests no stack in {PLAN} covers: lib/mini.json")


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

    def test_a_planned_stack_may_name_an_adapter_file_not_written_yet(self):
        # review round 2, finding 7 (the owner's decision): a planned entry's adapter file may not exist or not read yet
        for adapter in ({}, {".ekit/adapters/kotlin.toml": mini().replace("format = 1\n", "format = 9\n")}):
            with self.subTest(adapter=sorted(adapter)):
                base = self.repo.commit(dict(adapter, **{
                    "api/pyproject.toml": "[project]\n",
                    PLAN: plan(("api", "api", "python", "current"), ("mob", "mobile", ".ekit/adapters/kotlin.toml",
                                                                    "planned"))}))
                r, env = drift(self.repo, base, base)
                self.assertEqual((r.returncode, env["entries"], messages(env)), (0, [], []), r.stderr)

    def test_a_manifest_of_a_planned_stack_whose_adapter_is_not_proven_is_uncovered(self):
        base = self.repo.commit({"mobile/package.json": "{}", PLAN: plan(("mob", "mobile", ".ekit/adapters/kotlin.toml",
                                                                          "planned"))})
        r, env = drift(self.repo, base, base)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(fails(env)[0]["problem"], f"manifests no stack in {PLAN} covers: mobile/package.json")
        self.assertEqual(messages(env), [])

    def test_a_planned_stack_whose_adapter_file_lands_is_proven(self):
        base = self.repo.commit({"mobile/mini.json": "{}", PLAN: plan(("mob", "mobile", ".ekit/adapters/mini.toml",
                                                                       "planned"))})
        head = self.repo.commit({".ekit/adapters/mini.toml": mini()})
        r, env = drift(self.repo, base, head)
        self.assertEqual((r.returncode, env["entries"]), (0, []), r.stderr)
        self.assertEqual(messages(env), ["planned stack `mob` (mobile): its manifest mobile/mini.json is here and its "
                                         "adapter `.ekit/adapters/mini.toml` is proven, so its checks start: set its "
                                         "status to current"])

    def test_a_current_stack_still_needs_its_adapter_file(self):
        base = self.repo.commit({PLAN: plan(("mob", "mobile", ".ekit/adapters/kotlin.toml", "current"))})
        r = _kit.run_cli(["drift", "--repo", self.repo.path, "--base", base, "--head", base])
        self.assertEqual(r.returncode, 2)
        self.assertIn("stack[0] `mob`, field adapter: `.ekit/adapters/kotlin.toml` is not a built-in stack", r.stderr)

    def test_a_planned_stack_with_no_manifest_yet_is_quiet(self):
        base = self.repo.commit({PLAN: plan(("web", "web", "ts", "planned"))})
        r, env = drift(self.repo, base, base)
        self.assertEqual((r.returncode, env["entries"], messages(env)), (0, [], []))


    def test_the_text_format_gives_the_summary_the_entry_and_each_message(self):
        base = self.repo.commit({"web/package.json": "{}", "cli/Cargo.toml": "[package]\n",
                                 PLAN: plan(("web", "web", "ts", "planned"), ("api", "api", "python", "current"))})
        r = _kit.run_cli(["drift", "--repo", self.repo.path, "--base", base, "--head", base, "--format", "text"])
        self.assertEqual(r.returncode, 1, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], f"fail {base} (1 fail, 0 confirm; ran: D; skipped: R1 R2 R3 R4)")
        self.assertRegex(lines[1], rf"^fail D-[0-9a-f]{{8}} {PLAN}:0 manifests no stack in {PLAN} covers: cli/Cargo.toml$")
        self.assertEqual(lines[4:], [
            "message: planned stack `web` (web): its manifest web/package.json is here and its adapter `ts` is proven, so "
            "its checks start: set its status to current",
            f"message: stack `api` (api): no pyproject.toml, setup.py or setup.cfg in api any more: remove the entry `api` "
            f"from {PLAN}"])

    def test_the_text_format_without_a_plan_has_no_message_line(self):
        base = self.repo.commit({"pyproject.toml": ""})
        r = _kit.run_cli(["drift", "--repo", self.repo.path, "--base", base, "--head", base, "--format", "text"])
        self.assertEqual((r.returncode, r.stdout), (0, f"pass {base} (0 fail, 0 confirm; ran: none; skipped: R1 R2 R3 R4)\n"))


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
                                          "migration, then remove its entry; retiring for 41 days (30 or more): finish "
                                          "the migration or drop it"])

    def test_the_time_counts_from_when_it_became_retiring_not_from_the_last_plan_edit(self):
        base = self.history((90, "current"), (45, "retiring"))
        self.repo.commit({PLAN: plan(("js", ".", "ts", "retiring"), ("app", ".", "ts", "current"), ("x", "x", "rust",
                                                                                                    "planned"))},
                         "plan edit", when=self.now - 2 * DAY)
        self.assertIn("retiring for 45 days (30 or more)", self.text("HEAD")[0])

    def test_the_reminder_starts_at_exactly_30_days(self):
        # review round 2, finding 12: "once an entry has been retiring for 30 days"
        self.history((90, "current"))
        sha = self.repo.commit(dict(self.files, **{PLAN: plan(("js", ".", "ts", "retiring"), ("app", ".", "ts", "current"))}),
                               when=int(self.now) - 40 * DAY)
        start = int(self.now) - 40 * DAY
        at = lambda t: stack_plan.drift_at(self.repo.path, sha, now=t).messages[0]
        self.assertIn("retiring for 30 days (30 or more)", at(start + 30 * DAY))
        self.assertNotIn("days", at(start + 30 * DAY - 1))

    def test_retiring_for_30_days_or_less_is_no_reminder(self):
        sha = self.history((90, "current"), (29, "retiring"))
        self.assertNotIn("days", self.text(sha)[0])

    def test_an_older_plan_that_does_not_read_ends_the_count(self):
        for broken in ("stack = 1\n", "[[stack]\n", "[[stack]]\nname = \"other\"\n", "stack = [1]\n"):
            with self.subTest(broken=broken):
                self.repo.commit({PLAN: broken}, "broken", when=self.now - 200 * DAY)
                sha = self.history((41, "retiring"))
                self.assertIn("retiring for 41 days (30 or more)", self.text(sha)[0])

    def test_a_merged_side_branch_that_edited_the_plan_does_not_reset_the_count(self):
        # review round 2, finding 4: the count follows the branch's own (first-parent) history
        t0 = self.now - 100 * DAY
        two = lambda status, **kw: plan(("js", ".", "ts", status), ("app", ".", "ts", "current"), **kw)
        self.repo.commit(dict(self.files, **{PLAN: two("current")}), "start", when=t0)
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.commit({PLAN: two("current", ignore=["docs"])}, "side edit", when=t0 + 40 * DAY)
        self.repo.git("checkout", "-q", "main")
        self.repo.commit({PLAN: two("retiring")}, "retire js", when=t0 + DAY)
        stamp = {"GIT_COMMITTER_DATE": f"@{int(t0 + 46 * DAY)} +0000", "GIT_AUTHOR_DATE": f"@{int(t0 + 46 * DAY)} +0000"}
        try:
            self.repo.git("merge", "-q", "--no-edit", "side", env=stamp)
        except subprocess.CalledProcessError:
            with open(os.path.join(self.repo.path, PLAN), "w") as f:
                f.write(two("retiring", ignore=["docs"]))
            self.repo.git("add", "-A")
            self.repo.git("commit", "-q", "--no-edit", env=stamp)
        [m] = [m for m in stack_plan.drift_at(self.repo.path, "HEAD", now=t0 + 50 * DAY).messages if "`js`" in m]
        self.assertIn("retiring for 49 days (30 or more)", m)

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
            ('[[stack]]\nname = "mob"\nfolder = "m"\nadapter = 3\nstatus = "planned"\n',
             "stack[0] `mob`, field adapter: want a built-in stack (python, rust, ts) or an adapter file path"),
            ('[[stack]]\nname = "mob"\nfolder = "m"\nadapter = ""\nstatus = "planned"\n',
             "stack[0] `mob`, field adapter: want a built-in stack (python, rust, ts) or an adapter file path"),
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

    def test_two_entries_for_one_stack_folder_and_status_are_named(self):
        # review round 2, finding 5: which one sets the target OS would hang on their order
        for a, b in ((("a", "api", "python", "current", "linux"), ("b", "api", "python", "current", "windows")),
                     (("a", "api", "python", "retiring"), ("b", "./api/", "python", "retiring"))):
            with self.subTest(b=b):
                self.assertEqual(self.err(plan(a, b)), "stack[1] `b`, field folder: stack `python` in api is "
                                                       "already stack[0] `a` with status " + a[3])

    def test_the_same_stack_and_folder_in_another_status_is_a_migration_not_a_duplicate(self):
        sha = self.repo.commit({PLAN: plan(("js", "api", "python", "retiring"), ("py", "api", "python", "current"))})
        r, env = drift(self.repo, sha, sha)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_entry_folder_the_check_never_reads_is_named(self):
        # review round 2, finding 6: its manifests would never count, so it would always read vanished
        cases = [
            (plan(("api", "api", "python", "current"), ignore=["api"]),
             "stack[0] `api`, field folder: `api` is under ignore[0] `api`: the drift check reads no manifest there"),
            (plan(("app", "web/app", "ts", "planned"), ignore=["web"]),
             "stack[0] `app`, field folder: `web/app` is under ignore[0] `web`: the drift check reads no manifest there"),
            (plan(("demo", "examples/app", "ts", "planned")),
             "stack[0] `demo`, field folder: `examples/app` is under `examples`, a fixture, vendor or build folder: the "
             "drift check reads no manifest there"),
        ]
        for text, want in cases:
            with self.subTest(want=want):
                self.assertEqual(self.err(text), want)

    def test_an_ignore_folder_inside_an_entry_folder_is_fine(self):
        sha = self.repo.commit({PLAN: plan(("api", "api", "python", "current"), ignore=["api/demo"])})
        self.assertEqual(drift(self.repo, sha, sha)[0].returncode, 0)

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


class ResolveTargetOs(unittest.TestCase):
    """#58 with a plan: the base plan's entry for the settled stack and dir gives the target OS; its own target-os wins
    over its adapter's, and the adapter's applies when it names none."""

    def setUp(self):
        self.repo = Repo(self)

    def resolve(self, base, head, *args):
        r = _kit.run_cli(["resolve", "--repo", self.repo.path, "--base", base, "--head", head, *args])
        return r, (json.loads(r.stdout) if r.stdout else None)

    def test_the_entrys_target_os_is_the_output(self):
        sha = self.repo.commit({"pyproject.toml": "", PLAN: plan(("app", ".", "python", "current", "macos"))})
        r, got = self.resolve(sha, sha)
        self.assertEqual((r.returncode, got), (0, {"stack": "python", "project_dir": ".", "error": None,
                                                   "target_os": "macos"}))
        r, got = self.resolve(sha, sha, "--stack", "python")
        self.assertEqual((r.returncode, got["target_os"]), (0, "macos"))

    def test_the_entrys_target_os_wins_over_its_adapter_files(self):
        sha = self.repo.commit({"lib/mini.json": "{}", ".ekit/adapters/mini.toml": mini("windows"),
                                PLAN: plan(("lib", "lib", ".ekit/adapters/mini.toml", "current", "macos"))})
        r, got = self.resolve(sha, sha, "--stack", "mini", "--project-dir", "lib", "--adapter", MINI_ADAPTER)
        self.assertEqual((r.returncode, got["target_os"]), (0, "macos"))

    def test_the_entrys_adapter_applies_when_the_entry_names_none(self):
        sha = self.repo.commit({"lib/mini.json": "{}", ".ekit/adapters/mini.toml": mini("windows"),
                                PLAN: plan(("lib", "lib", ".ekit/adapters/mini.toml", "current"))})
        r, got = self.resolve(sha, sha, "--stack", "mini", "--project-dir", "lib", "--adapter", MINI_ADAPTER)
        self.assertEqual((r.returncode, got["target_os"]), (0, "windows"))

    def test_the_plan_is_read_from_the_base_so_a_pr_cannot_move_its_own_runner(self):
        base = self.repo.commit({"pyproject.toml": "", PLAN: plan(("app", ".", "python", "current"))})
        head = self.repo.commit({PLAN: plan(("app", ".", "python", "current", "windows"))})
        r, got = self.resolve(base, head)
        self.assertEqual((r.returncode, got["target_os"]), (0, "linux"))

    def test_an_entry_for_another_folder_or_stack_does_not_apply(self):
        sha = self.repo.commit({"pyproject.toml": "", "web/package.json": "{}",
                                PLAN: plan(("web", "web", "ts", "current", "macos"), ("app", ".", "rust", "planned",
                                                                                      "windows"))})
        r, got = self.resolve(sha, sha, "--stack", "python")
        self.assertEqual((r.returncode, got["target_os"]), (0, "linux"))

    def test_a_current_entry_wins_over_a_retiring_one_in_the_same_folder(self):
        sha = self.repo.commit({"package.json": "{}", PLAN: plan(("js", ".", "ts", "retiring", "windows"),
                                                                 ("app", ".", "ts", "current", "macos"))})
        r, got = self.resolve(sha, sha)
        self.assertEqual((r.returncode, got["stack"], got["target_os"]), (0, "ts", "macos"))

    def test_a_bad_base_plan_is_a_usage_error(self):
        sha = self.repo.commit({"pyproject.toml": "", PLAN: plan(("app", ".", "python", "current", "amiga"))})
        r, got = self.resolve(sha, sha)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("stack[0] `app`, field target-os: `amiga`: want linux, macos or windows", r.stderr)

    def test_an_explicit_stack_with_no_checkout_reads_no_plan_as_before(self):
        # the workflow's stack job checks the caller out only for stack auto
        missing = os.path.join(self.repo.path, "no-checkout")
        r = _kit.run_cli(["resolve", "--repo", missing, "--base", "b" * 40, "--head", "a" * 40, "--stack", "rust"])
        self.assertEqual((r.returncode, json.loads(r.stdout)), (0, {"stack": "rust", "project_dir": ".", "error": None,
                                                                    "target_os": "linux"}))


    def test_an_explicit_stack_in_a_directory_that_is_not_a_git_repo_reads_no_plan_as_before(self):
        # review round 2, finding 9: `--repo .` (the default) in a directory with no git repo
        plain = tempfile.TemporaryDirectory()
        self.addCleanup(plain.cleanup)
        r = _kit.run_cli(["resolve", "--repo", plain.name, "--base", "main", "--head", "HEAD", "--stack", "python"])
        self.assertEqual((r.returncode, json.loads(r.stdout)), (0, {"stack": "python", "project_dir": ".", "error": None,
                                                                    "target_os": "linux"}))

    def test_a_missing_base_ref_in_a_real_repo_is_a_git_error(self):
        self.repo.commit({"pyproject.toml": ""})
        r = _kit.run_cli(["resolve", "--repo", self.repo.path, "--base", "nosuch", "--head", "HEAD", "--stack", "python"])
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("unknown ref: nosuch", r.stderr)


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
        self.assertIn("retiring for 40 days (30 or more)", m)
        [m] = stack_plan.drift_at(repo.path, "HEAD", now=now - 20 * DAY).messages
        self.assertNotIn("days", m)


if __name__ == "__main__":
    unittest.main()
