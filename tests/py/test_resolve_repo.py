"""Stack resolution finds the stacks and adapters defined in the repo (#17): the base branch's stack plan first (its
current and retiring stacks, and planned ones whose manifest is there, each with the adapter the plan names), else
detection over the built-ins and the repo's adapter files (`.ekit/adapters/<name>.toml`, a file named like a built-in
in place of it). Both are read at the PR's base, so a PR cannot change which adapter judges it. Every call goes through
cli.main in this process (_kit.run_cli)."""
import json
import os
import tempfile
import unittest

import _kit
from test_stack_plan import MINI_ADAPTER, PLAN, Repo, mini, plan


def resolve(repo, base, head, *args):
    r = _kit.run_cli(["resolve", "--repo", repo.path, "--base", base, "--head", head, *args])
    return r, (json.loads(r.stdout) if r.stdout else None)


class FromThePlan(unittest.TestCase):
    """S1, S2: a repo with a plan resolves to the stacks it lists; detection is not used."""

    def setUp(self):
        self.repo = Repo(self)

    def test_every_current_or_retiring_stack_with_the_adapter_the_plan_names(self):
        sha = self.repo.commit({"api/pyproject.toml": "", "web/package.json": "{}", "lib/mini.json": "{}",
                                ".ekit/adapters/mini.toml": mini("macos"),
                                PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "retiring"),
                                           ("lib", "lib", ".ekit/adapters/mini.toml", "current"))})
        r, got = resolve(self.repo, sha, sha)
        self.assertEqual((r.returncode, got), (0, {
            "stack": None, "project_dir": ".", "error": None, "target_os": None,
            "stacks": [
                {"name": "api", "stack": "python", "project_dir": "api", "adapter": "python", "target_os": "linux"},
                {"name": "web", "stack": "ts", "project_dir": "web", "adapter": "ts", "target_os": "linux"},
                {"name": "lib", "stack": "mini", "project_dir": "lib", "adapter": ".ekit/adapters/mini.toml",
                 "target_os": "macos"},
            ]}), r.stderr)

    def test_a_plan_that_reads_says_nothing_on_stderr(self):
        sha = self.repo.commit({"api/pyproject.toml": "", PLAN: plan(("api", "api", "python", "current"))})
        for args in ((), ("--stack", "python", "--project-dir", "api")):
            with self.subTest(args):
                r, got = resolve(self.repo, sha, sha, *args)
                self.assertEqual((r.returncode, got["stack"], r.stderr), (0, "python", ""))

    def test_a_planned_stack_whose_manifest_is_missing_is_not_run(self):
        # detection is not used: the root Cargo.toml no entry covers is the drift check's, not a second project here
        sha = self.repo.commit({"api/pyproject.toml": "", "Cargo.toml": "",
                                PLAN: plan(("api", "api", "python", "current", "windows"), ("web", "web", "ts", "planned"),
                                           ("mob", "mob", ".ekit/adapters/kotlin.toml", "planned"))})
        r, got = resolve(self.repo, sha, sha)
        self.assertEqual((r.returncode, got), (0, {"stack": "python", "project_dir": "api", "error": None,
                                                   "target_os": "windows"}), r.stderr)

    def test_a_planned_stack_runs_once_its_manifest_is_there(self):
        base = self.repo.commit({"api/pyproject.toml": "",
                                 PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "planned"))})
        head = self.repo.commit({"web/package.json": "{}"})
        r, got = resolve(self.repo, base, head)
        self.assertEqual((r.returncode, [(s["name"], s["stack"], s["project_dir"]) for s in got["stacks"]]),
                         (0, [("api", "python", "api"), ("web", "ts", "web")]), r.stderr)

    def test_a_current_stack_whose_manifest_the_pr_deletes_still_runs(self):
        # the base tree counts too: a PR cannot stop its own checks by deleting the manifest
        base = self.repo.commit({"api/pyproject.toml": "", "web/package.json": "{}",
                                 PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "current"))})
        head = self.repo.commit({"web/package.json": None})
        r, got = resolve(self.repo, base, head)
        self.assertEqual((r.returncode, [s["name"] for s in got["stacks"]]), (0, ["api", "web"]), r.stderr)

    def test_a_plan_with_no_stack_to_run_fails_naming_it_and_the_inputs(self):
        sha = self.repo.commit({"pyproject.toml": "", PLAN: plan(("web", "web", "ts", "planned"))})
        r, got = resolve(self.repo, sha, sha)
        self.assertEqual((r.returncode, got), (1, {
            "stack": None, "project_dir": ".", "target_os": None,
            "error": "stack auto: the stack plan has no stack to run (no current, retiring or planned stack whose "
                     "manifest is here); set the stack and project-dir inputs in the mech-review caller"}), r.stderr)

    def test_a_set_project_dir_keeps_the_plans_stack_for_it(self):
        sha = self.repo.commit({"api/pyproject.toml": "", "web/package.json": "{}",
                                PLAN: plan(("api", "api", "python", "current"), ("web", "web", "ts", "current", "macos"))})
        r, got = resolve(self.repo, sha, sha, "--project-dir", "web")
        self.assertEqual((r.returncode, got), (0, {"stack": "ts", "project_dir": "web", "error": None,
                                                   "target_os": "macos"}), r.stderr)
        r, got = resolve(self.repo, sha, sha, "--project-dir", "lib")
        self.assertEqual((r.returncode, got["error"]), (1, "stack auto: the stack plan has no stack to run in lib (no "
                                                           "current, retiring or planned stack whose manifest is here); "
                                                           "set the stack and project-dir inputs in the mech-review caller"))

    def test_the_plan_is_read_from_the_base(self):
        # S6: a PR that adds a plan (or edits one) does not pick its own stacks; with none on base, detection as before
        base = self.repo.commit({"pyproject.toml": ""})
        head = self.repo.commit({"web/package.json": "{}", PLAN: plan(("web", "web", "ts", "current"))})
        r, got = resolve(self.repo, base, head)
        self.assertEqual((r.returncode, got["stack"], got["project_dir"]), (0, "python", "."), r.stderr)
        base = self.repo.commit({PLAN: plan(("app", ".", "python", "current"))})
        head = self.repo.commit({PLAN: plan(("app", ".", "python", "current"), ("web", "web", "ts", "current"))})
        r, got = resolve(self.repo, base, head)
        self.assertEqual((r.returncode, got["stack"], got["project_dir"]), (0, "python", "."), r.stderr)


def adapter(name, manifests, target_os=None):
    """an adapter file's text: the mini fixture under another name, listing other manifests."""
    text = mini(target_os).replace('name = "mini"', f'name = "{name}"')
    return text.replace('manifests = ["mini.json"]', "manifests = " + json.dumps(manifests))


class RepoAdapters(unittest.TestCase):
    """S3, S4, S5: with no plan, auto detects the manifests of the repo's adapter files too (.ekit/adapters/*.toml)."""

    def setUp(self):
        self.repo = Repo(self)

    def test_a_repo_adapter_is_found_by_its_declared_manifest(self):
        sha = self.repo.commit({"pom.xml": "<project/>", ".ekit/adapters/maven.toml": adapter("maven", ["pom.xml"], "macos")})
        r, got = resolve(self.repo, sha, sha)
        self.assertEqual((r.returncode, got), (0, {"stack": "maven", "project_dir": ".", "error": None,
                                                   "target_os": "macos"}), r.stderr)

    def test_a_repo_adapter_named_like_a_built_in_is_used_in_its_place(self):
        # S4: its manifests replace the built-in's, so a package.json is no ts project any more, and its target-os applies
        sha = self.repo.commit({"web/deno.json": "{}", "tools/package.json": "{}",
                                ".ekit/adapters/ts.toml": adapter("ts", ["deno.json"], "windows")})
        r, got = resolve(self.repo, sha, sha)
        self.assertEqual((r.returncode, got), (0, {"stack": "ts", "project_dir": "web", "error": None,
                                                   "target_os": "windows"}), r.stderr)

    def test_several_projects_with_a_repo_adapter_are_named_never_a_guess(self):
        sha = self.repo.commit({"pom.xml": "", "pyproject.toml": "", ".ekit/adapters/maven.toml": adapter("maven", ["pom.xml"])})
        r, got = resolve(self.repo, sha, sha)
        self.assertEqual((r.returncode, got), (1, {
            "stack": None, "project_dir": ".", "target_os": None,
            "error": "stack auto, base: several projects: maven in ., python in .; set the stack and project-dir inputs "
                     "in the mech-review caller"}))

    def test_no_project_names_the_repo_adapters_manifests_too(self):
        sha = self.repo.commit({"README.md": "", ".ekit/adapters/maven.toml": adapter("maven", ["pom.xml"])})
        r, got = resolve(self.repo, sha, sha)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(got["error"], "stack auto, base: no project found (no pyproject.toml, setup.py, setup.cfg, "
                                       "Cargo.toml, package.json, pom.xml); set the stack and project-dir inputs in the "
                                       "mech-review caller")

    def test_a_repo_adapter_file_that_does_not_read_is_named_never_skipped(self):
        for text, why in ((adapter("maven", ["pom.xml"]).replace("format = 1", "format = 2"), "format: `2`: want 1"),
                          (adapter("gradle", ["pom.xml"]), "name: `gradle`: want `maven`, its file name")):
            with self.subTest(why):
                sha = self.repo.commit({"pom.xml": "", ".ekit/adapters/maven.toml": text})
                r, got = resolve(self.repo, sha, sha)
                self.assertEqual((r.returncode, got), (1, {
                    "stack": None, "project_dir": ".", "target_os": None,
                    "error": f"stack auto: adapter file .ekit/adapters/maven.toml: {why}; set the stack and project-dir "
                             f"inputs in the mech-review caller"}))

    def test_only_toml_files_directly_in_the_adapters_folder_count(self):
        sha = self.repo.commit({"pom.xml": "", "pyproject.toml": "", ".ekit/adapters/old/maven.toml": adapter("maven", ["pom.xml"]),
                                ".ekit/adapters/maven.toml.txt": adapter("maven", ["pom.xml"]), ".ekit/adapters/README.md": "x"})
        r, got = resolve(self.repo, sha, sha)
        self.assertEqual((r.returncode, got["stack"]), (0, "python"), r.stderr)

    def test_an_explicit_name_the_repo_defines_is_its_adapter(self):
        sha = self.repo.commit({"pom.xml": "", ".ekit/adapters/maven.toml": adapter("maven", ["pom.xml"], "macos"),
                                ".ekit/adapters/ts.toml": adapter("ts", ["deno.json"], "windows")})
        for stack, want in (("maven", "macos"), ("ts", "windows"), ("python", "linux")):
            with self.subTest(stack):
                r, got = resolve(self.repo, sha, sha, "--stack", stack, "--project-dir", "app")
                self.assertEqual((r.returncode, got), (0, {"stack": stack, "project_dir": "app", "error": None,
                                                           "target_os": want}), r.stderr)
        r, got = resolve(self.repo, sha, sha, "--stack", "gradle")
        self.assertEqual((r.returncode, got["error"]), (1, "stack gradle: want auto, maven, python, rust or ts"))

    def test_an_explicit_name_is_known_only_from_a_toml_file_in_the_adapters_folder(self):
        # a .toml elsewhere (build/gradle.toml) or another file in the folder (.ekit/adapters/notes.txt) names no stack
        sha = self.repo.commit({".ekit/adapters/maven.toml": adapter("maven", ["pom.xml"]), "build/gradle.toml": "",
                                ".ekit/adapters/notes.txt": ""})
        for stack in ("gradle", "notes"):
            with self.subTest(stack):
                r, got = resolve(self.repo, sha, sha, "--stack", stack)
                self.assertEqual((r.returncode, got["error"]), (1, f"stack {stack}: want auto, maven, python, rust or ts"))

    def test_the_adapter_is_read_from_the_base(self):
        # S6: a PR that adds an adapter file (or edits one) does not change what auto finds for it
        base = self.repo.commit({"pyproject.toml": ""})
        head = self.repo.commit({".ekit/adapters/python.toml": adapter("python", ["pom.xml"], "macos")})
        r, got = resolve(self.repo, base, head)
        self.assertEqual((r.returncode, got), (0, {"stack": "python", "project_dir": ".", "error": None,
                                                   "target_os": "linux"}), r.stderr)
        base = self.repo.commit({"pom.xml": "", "pyproject.toml": None})
        head = self.repo.commit({".ekit/adapters/python.toml": adapter("python", ["pyproject.toml"])})
        r, got = resolve(self.repo, base, head)
        self.assertEqual((r.returncode, got["stack"], got["target_os"]), (0, "python", "macos"), r.stderr)


CALC = 'suite("Calc", {\n  test("adds", {\n    assertEquals(3, add(1, 2))\n  })\n  test("subtracts", {\n    assertTrue(1)\n  })\n})\n'
NO_SUB = CALC.replace('  test("subtracts", {\n    assertTrue(1)\n  })\n', "")
REMOVED = "test fn `Calc / subtracts` removed"


def r2(repo, base, head, stack, *extra):
    return _kit.run_cli(["r2", "--repo", repo.path, "--base", base, "--head", head, "--stack", stack,
                         "--test-paths", "tests/**", *extra])


def problems(r):
    return [e["problem"] for e in json.loads(r.stdout)["entries"]] if r.stdout else None


class RepoAdapterByName(unittest.TestCase):
    """S4, S6 at another check: `r2 --stack <name>` takes the repo's adapter file for that name from the PR's base."""

    def setUp(self):
        self.repo = Repo(self)

    def test_a_repo_adapter_named_like_a_built_in_judges_in_its_place(self):
        # the built-in ts reads no .mini file; the repo's ts.toml (the mini language under the name ts) does
        base = self.repo.commit({"tests/calc.mini": CALC, ".ekit/adapters/ts.toml": adapter("ts", ["mini.json"])})
        head = self.repo.commit({"tests/calc.mini": NO_SUB})
        r = r2(self.repo, base, head, "ts")
        self.assertEqual((r.returncode, problems(r)), (1, [REMOVED]), r.stderr)

    def test_a_stack_only_the_repo_defines_is_found_by_its_name(self):
        base = self.repo.commit({"tests/calc.mini": CALC, ".ekit/adapters/mini.toml": mini()})
        head = self.repo.commit({"tests/calc.mini": NO_SUB})
        r = r2(self.repo, base, head, "mini")
        self.assertEqual((r.returncode, problems(r)), (1, [REMOVED]), r.stderr)

    def test_the_adapter_is_the_bases_so_a_pr_cannot_change_which_adapter_judges_it(self):
        base = self.repo.commit({"tests/calc.mini": CALC, ".ekit/adapters/mini.toml": mini()})
        # the PR drops `test` from the cases, so its own file would see no test to remove
        head = self.repo.commit({".ekit/adapters/mini.toml": mini().replace('cases = ["test", "xtest"]', 'cases = ["xtest"]'),
                                 "tests/calc.mini": NO_SUB})
        r = r2(self.repo, base, head, "mini")
        self.assertEqual((r.returncode, problems(r)), (1, [REMOVED]), r.stderr)
        # and a PR that adds an adapter file named like a built-in is still judged by the built-in
        base = self.repo.commit({"tests/a.test.ts": 'it("x", () => { expect(1).toBe(1) })\n'})
        head = self.repo.commit({".ekit/adapters/ts.toml": adapter("ts", ["package.json"]), "tests/a.test.ts": "\n"})
        r = r2(self.repo, base, head, "ts")
        self.assertEqual((r.returncode, problems(r)), (1, ["test fn `x` removed"]), r.stderr)

    def test_the_plans_adapter_file_for_the_stack_and_dir_is_used(self):
        base = self.repo.commit({"lib/mini.json": "{}", "tests/calc.mini": CALC, "build/m.toml": mini(),
                                 PLAN: plan(("lib", "lib", "build/m.toml", "current"))})
        head = self.repo.commit({"tests/calc.mini": NO_SUB})
        r = r2(self.repo, base, head, "mini", "--project-dir", "lib")
        self.assertEqual((r.returncode, problems(r)), (1, [REMOVED]), r.stderr)

    def test_an_explicit_adapter_file_still_wins(self):
        base = self.repo.commit({"tests/calc.mini": CALC, ".ekit/adapters/mini.toml":
                                 mini().replace('cases = ["test", "xtest"]', 'cases = ["xtest"]')})
        head = self.repo.commit({"tests/calc.mini": NO_SUB})
        r = r2(self.repo, base, head, "mini", "--adapter", MINI_ADAPTER)
        self.assertEqual((r.returncode, problems(r)), (1, [REMOVED]), r.stderr)

    def test_a_repo_adapter_that_does_not_read_is_a_usage_error_naming_it(self):
        base = self.repo.commit({"tests/calc.mini": CALC, ".ekit/adapters/mini.toml": mini().replace("format = 1", "format = 2")})
        r = r2(self.repo, base, base, "mini")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("adapter file .ekit/adapters/mini.toml: format: `2`: want 1", r.stderr)

    def test_an_unknown_name_is_still_a_usage_error(self):
        base = self.repo.commit({"tests/calc.mini": CALC})
        r = r2(self.repo, base, base, "mini")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("argument --stack: invalid choice: 'mini'", r.stderr)


BOGUS = "bogus = 1\n"  # an unknown top-level key: the plan does not read


class BadBasePlan(unittest.TestCase):
    """Review round 1, finding 1 (S6): stacks and adapters come only from a base plan that reads. When the base plan does
    not read, auto detects on the base tree with the base's adapter files; the PR's own plan never picks the stack or
    the adapter (it may still set target_os, as #56 has it, for the PR that fixes the plan)."""

    def setUp(self):
        self.repo = Repo(self)

    def test_a_pr_that_rewrites_a_bad_base_plan_does_not_pick_its_stack(self):
        base = self.repo.commit({"api/pyproject.toml": "", "api/package.json": "{}",
                                 PLAN: BOGUS + plan(("api", "api", "python", "current"))})
        head = self.repo.commit({PLAN: plan(("api", "api", "ts", "current"))})
        r, got = resolve(self.repo, base, head)
        self.assertEqual((r.returncode, got), (1, {
            "stack": None, "project_dir": ".", "target_os": None,
            "error": "stack auto, base: several projects: python in api, ts in api; set the stack and project-dir inputs "
                     "in the mech-review caller"}), r.stderr)

    def test_a_pr_cannot_bring_its_own_adapter_file_through_a_fixed_plan(self):
        base = self.repo.commit({"pyproject.toml": "", "lib/mini.json": "{}", PLAN: BOGUS})
        head = self.repo.commit({".ekit/x/evil.toml": mini("windows"),
                                 PLAN: plan(("lib", "lib", ".ekit/x/evil.toml", "current"))})
        r, got = resolve(self.repo, base, head)
        self.assertEqual((r.returncode, got), (0, {"stack": "python", "project_dir": ".", "error": None,
                                                   "target_os": "linux"}), r.stderr)


class BadAdapterNames(unittest.TestCase):
    """Review round 1, findings 2 and 6: a repo adapter's name is a stack name (letters, digits, _ or -), checked one
    way everywhere; a bad one is a named error, never a traceback."""

    def setUp(self):
        self.repo = Repo(self)

    def test_a_dotted_file_name_is_no_stack_an_explicit_stack_can_name(self):
        sha = self.repo.commit({"pyproject.toml": "", ".ekit/adapters/a.b.toml": mini().replace('"mini"', '"a.b"')})
        r, got = resolve(self.repo, sha, sha, "--stack", "a.b")
        self.assertEqual((r.returncode, got), (1, {"stack": None, "project_dir": ".", "target_os": None,
                                                   "error": "stack a.b: want auto, python, rust or ts"}), r.stderr)
        r = r2(self.repo, sha, sha, "a.b")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("argument --stack: invalid choice: 'a.b'", r.stderr)

    def test_a_file_whose_name_only_starts_like_a_stack_name_lists_no_stack(self):
        sha = self.repo.commit({"pyproject.toml": "", ".ekit/adapters/maven.x.toml": mini()})
        r, got = resolve(self.repo, sha, sha, "--stack", "gradle")
        self.assertEqual((r.returncode, got["error"]), (1, "stack gradle: want auto, python, rust or ts"), r.stderr)

    def test_auto_names_a_file_whose_name_is_no_stack_name(self):
        for file, why in (("a.b.toml", "file name `a.b.toml`: want <stack>.toml, the stack letters, digits, _ or -"),
                          (".toml", "file name `.toml`: want <stack>.toml, the stack letters, digits, _ or -")):
            with self.subTest(file):
                repo = Repo(self)
                sha = repo.commit({"pyproject.toml": "", f".ekit/adapters/{file}": mini()})
                r, got = resolve(repo, sha, sha)
                self.assertEqual((r.returncode, got), (1, {
                    "stack": None, "project_dir": ".", "target_os": None,
                    "error": f"stack auto: adapter file .ekit/adapters/{file}: {why}; set the stack and project-dir "
                             f"inputs in the mech-review caller"}), r.stderr)


NOT_BUILT = "stack `mini` is the repo's adapter file: {} through an adapter file is not built yet (#18, #19)"


class RunSideNotBuilt(unittest.TestCase):
    """Review round 1, finding 3: red, mutants and baseline on a stack the repo's adapter file describes (by name, or
    the plan's entry) report their checks n/a with the reason, never a usage error or a silent built-in run."""

    def setUp(self):
        self.repo = Repo(self)
        self.base = self.repo.commit({"tests/calc.mini": CALC, "src/calc.mini": "fn add(a, b) { a + b }\n",
                                      ".ekit/adapters/mini.toml": mini()})
        self.head = self.repo.commit({"src/calc.mini": "fn add(a, b) { a - b }\n"})

    def cli(self, check, stack="mini", *extra):
        r = _kit.run_cli([check, "--repo", self.repo.path, "--base", self.base, "--head", self.head, "--stack", stack,
                          "--test-paths", "tests/**", *extra])
        return r, (json.loads(r.stdout) if r.stdout else None)

    def test_red_reports_r1_and_r4_n_a(self):
        r, env = self.cli("red")
        self.assertEqual((r.returncode, env["entries"]), (0, []), r.stderr)
        self.assertEqual({c: env["checks"][c] for c in ("R1", "R4")},
                         {"R1": {"status": "n/a", "note": NOT_BUILT.format("R1")},
                          "R4": {"status": "n/a", "note": NOT_BUILT.format("R4")}})
        self.assertEqual(env["summary"], f"pass {self.head} (0 fail, 0 confirm; ran: none; skipped: R2 R3; n/a: R1 R4)")

    def test_red_prints_text_when_asked(self):
        r, _ = _kit.run_cli(["red", "--repo", self.repo.path, "--base", self.base, "--head", self.head, "--stack", "mini",
                             "--test-paths", "tests/**", "--format", "text"]), None
        self.assertEqual((r.returncode, r.stdout), (0, f"pass {self.head} (0 fail, 0 confirm; ran: none; skipped: R2 R3; "
                                                       f"n/a: R1 R4)\n"), r.stderr)

    def test_all_runs_r2_through_the_file_and_r1_r4_n_a(self):
        r, env = self.cli("all")
        self.assertEqual((r.returncode, env["checks"]["R2"]["status"], env["checks"]["R1"]["status"],
                          env["checks"]["R4"]["status"]), (0, "pass", "n/a", "n/a"), r.stderr)

    def test_mutants_reports_r3_n_a(self):
        r, env = self.cli("mutants")
        self.assertEqual((r.returncode, env["checks"]["R3"], env["entries"]),
                         (0, {"status": "n/a", "note": NOT_BUILT.format("R3")}, []), r.stderr)
        self.assertEqual(env["shard"], {"k": 0, "n": 1, "max_mutants": 40})

    def test_baseline_reports_r3_n_a_and_runs_no_shard(self):
        r, env = self.cli("baseline")
        self.assertEqual((r.returncode, env["checks"]["R3"], env["run"], env["count"]),
                         (0, {"status": "n/a", "note": NOT_BUILT.format("R3")}, False, 0), r.stderr)

    def test_plan_lets_the_baseline_say_why(self):
        r, env = self.cli("plan")
        self.assertEqual((r.returncode, env), (0, {"run": True}), r.stderr)

    def test_the_plans_adapter_file_is_not_run_either(self):
        base = self.repo.commit({"lib/mini.json": "{}", "build/m.toml": mini(), ".ekit/adapters/mini.toml": None,
                                 PLAN: plan(("lib", "lib", "build/m.toml", "current"))})
        self.base, self.head = base, self.repo.commit({"src/calc.mini": "fn add(a, b) { b }\n"})
        r, env = self.cli("red", "mini", "--project-dir", "lib")
        self.assertEqual((r.returncode, env["checks"]["R1"]["status"]), (0, "n/a"), r.stderr)


class OverrideKeepsTheBuiltInRunSide(unittest.TestCase):
    """Review round 2, B (orchestrator's decision): until adapter files have a run side (#18, #19), a repo adapter named
    like a built-in (.ekit/adapters/ts.toml) judges R2 and resolution only; red, mutants, baseline and plan run the
    built-in, with the same verdict as with no override, so adding the file turns no check off."""

    def pr(self, override):
        repo = Repo(self)
        files = {"package.json": "{}", "src/x.ts": "export const a = 1\n",
                 "tests/a.test.ts": 'it("x", () => { expect(1).toBe(1) })\n'}
        if override:
            files[".ekit/adapters/ts.toml"] = adapter("ts", ["package.json"])
        base = repo.commit(files)
        return repo, base, repo.commit({"src/x.ts": "export const a = 2\n"})

    def run_check(self, check, override):
        repo, base, head = self.pr(override)
        r = _kit.run_cli([check, "--repo", repo.path, "--base", base, "--head", head, "--stack", "ts",
                          "--test-paths", "tests/**"])
        self.assertIn(r.returncode, (0, 1), r.stderr)
        env = json.loads(r.stdout)
        return {k: env[k] for k in ("checks", "run", "count") if k in env}

    def test_red_runs_the_built_in(self):
        got = self.run_check("red", True)
        self.assertEqual(got["checks"]["R4"], {"status": "pass", "note": "0 new or changed tests"})
        self.assertEqual(got, self.run_check("red", False))

    def test_baseline_and_plan_run_the_built_in(self):
        got = self.run_check("baseline", True)
        self.assertEqual((got["run"], got["count"], got["checks"]["R3"]["note"]),
                         (True, 1, "1 changed production file(s) in 1 shard(s)"))
        self.assertEqual(got, self.run_check("baseline", False))
        repo, base, head = self.pr(True)
        r = _kit.run_cli(["plan", "--repo", repo.path, "--base", base, "--head", head, "--stack", "ts",
                          "--test-paths", "tests/**"])
        self.assertEqual((r.returncode, json.loads(r.stdout)), (0, {"run": True}), r.stderr)

    def test_all_runs_r2_through_the_file_and_r1_r4_on_the_built_in(self):
        # the file is the mini language under the name ts: R2 reads .mini files (the built-in ts reads none), R1 and R4
        # are the built-in's, as with no override
        def run(override):
            repo = Repo(self)
            files = {"package.json": "{}", "tests/calc.mini": CALC, "tests/a.test.ts": 'it("x", () => { expect(1).toBe(1) })\n'}
            if override:
                files[".ekit/adapters/ts.toml"] = adapter("ts", ["package.json"])
            base = repo.commit(files)
            head = repo.commit({"tests/calc.mini": NO_SUB, "tests/a.test.ts": 'it("x", () => { expect(2).toBe(2) })\n'})
            r = _kit.run_cli(["all", "--repo", repo.path, "--base", base, "--head", head, "--stack", "ts",
                              "--test-paths", "tests/**"])
            return r, json.loads(r.stdout)
        r, env = run(True)
        self.assertEqual((r.returncode, env["checks"]["R2"]["status"], [e["problem"] for e in env["entries"] if e["check"] == "R2"]),
                         (1, "fail", [REMOVED]), r.stderr)
        _, plain = run(False)
        self.assertEqual(plain["checks"]["R2"]["status"], "pass")
        self.assertEqual({c: env["checks"][c] for c in ("R1", "R3", "R4")}, {c: plain["checks"][c] for c in ("R1", "R3", "R4")})


class MergeOnARepoStack(unittest.TestCase):
    """Review round 2, A: the report job's merge (no checkout there) takes a repo-only stack name, and carries the
    baseline's R3 n/a through."""

    def test_the_baselines_n_a_is_the_merged_r3(self):
        repo = Repo(self)
        base = repo.commit({"tests/calc.mini": CALC, "src/calc.mini": "fn add(a, b) { a + b }\n",
                            ".ekit/adapters/mini.toml": mini()})
        head = repo.commit({"src/calc.mini": "fn add(a, b) { a - b }\n"})
        r = _kit.run_cli(["baseline", "--repo", repo.path, "--base", base, "--head", head, "--stack", "mini",
                          "--test-paths", "tests/**"])
        path = os.path.join(repo.path, "..", os.path.basename(repo.path) + "-baseline.json")
        with open(path, "w") as f:
            f.write(r.stdout)
        self.addCleanup(os.remove, path)
        nowhere = tempfile.TemporaryDirectory()  # the report job has no checkout: full SHAs, no repo
        self.addCleanup(nowhere.cleanup)
        r = _kit.run_cli(["merge", "--repo", nowhere.name, "--base", base, "--head", head, "--stack", "mini",
                          "--shards", "0", "--baseline", path])
        env = json.loads(r.stdout) if r.stdout else None
        self.assertEqual((r.returncode, env and env["checks"]["R3"], env and env["entries"]),
                         (0, {"status": "n/a", "note": NOT_BUILT.format("R3")}, []), r.stderr)

    def test_a_name_that_is_no_stack_name_is_still_a_usage_error(self):
        r = _kit.run_cli(["merge", "--base", "a" * 40, "--head", "b" * 40, "--stack", "a.b", "--shards", "0"])
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("argument --stack: invalid choice: 'a.b'", r.stderr)


if __name__ == "__main__":
    unittest.main()
