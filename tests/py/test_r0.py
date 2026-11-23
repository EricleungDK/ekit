"""R0 static half (#20): `mech-review.py r0` proves the stack adapter against the cheat suite and the negative controls,
git and adapter only. Through cli.main in this process (R3's mutmut sees only in-process calls)."""
import json
import os
import subprocess
import tempfile
import unittest

import _kit
from scripts.mech_review import comment, waiver

CHEATS = ["delete", "comment-out", "rename", "skip", "expected-value", "weaken-assert", "suppression"]
CONTROLS = ["rename-same-asserts", "reorder-asserts", "helper-asserts", "empty-diff"]
SOURCE_CASES = ["source-ident-chars", "source-empty-asserts", "source-unbalanced-brackets"]


class Repo:
    def __init__(self, tmp):
        self.path = tmp
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.path, "-c", "user.email=t@t", "-c", "user.name=t",
                               "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout

    def commit(self, files, msg="c"):
        for rel, text in files.items():
            full = os.path.join(self.path, rel)
            if text is None:
                os.remove(full)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", newline="\n") as f:
                f.write(text)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()


def tmp_repo(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    repo = Repo(tmp.name)
    return repo, repo.commit({"README.md": "x\n"}, "base")


def r0(repo, base, head, *extra):
    return _kit.run_cli(["r0", "--repo", repo.path, "--base", base, "--head", head, *extra])


class BuiltinsPass(unittest.TestCase):
    """C1: the static half passes against every built-in stack: each cheat caught, each control clean."""

    def check_stack(self, stack):
        repo, base = tmp_repo(self)
        r = r0(repo, base, base, "--stack", stack)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = json.loads(r.stdout)
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual(c["half"], "static")
        self.assertEqual({x["case"]: x["status"] for x in c["cases"] if x["kind"] in ("cheat", "control")},
                         dict.fromkeys(CHEATS + CONTROLS, "pass"))
        self.assertEqual({x["case"]: x["status"] for x in c["cases"] if x["case"].startswith("source-")},
                         dict.fromkeys(SOURCE_CASES, "pass"))
        self.assertEqual(env["entries"], [])
        self.assertEqual(env["summary"], f"pass {base} (0 fail, 0 confirm; ran: R0; skipped: R1 R2 R3 R4)")

    def test_rust(self):
        self.check_stack("rust")

    def test_python(self):
        self.check_stack("python")

    def test_ts(self):
        self.check_stack("ts")


MINI = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.toml")
MINI_FIXTURES = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.r0")
FUNCTIONS = '\n[functions]\nshapes = ["fn NAME (...) ...{...}"]\n'


def adapter_copy(case, text):
    """an adapter file with this text in a temp dir (no fixture dir beside it): its path."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    path = os.path.join(tmp.name, "mini.toml")
    with open(path, "w", newline="\n") as f:
        f.write(text)
    return path


def mini_text():
    with open(MINI) as f:
        return f.read()


class AdapterFiles(unittest.TestCase):
    """C2, C3: R0 proves an adapter file the same way; a weak one fails and names the cheat or control it got wrong."""

    def run_r0(self, adapter, fixtures=MINI_FIXTURES):
        repo, base = tmp_repo(self)
        r = r0(repo, base, base, "--stack", "mini", "--adapter", adapter, "--fixtures", fixtures)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return r.returncode, json.loads(r.stdout)

    def test_a_good_adapter_file_passes_and_each_malformed_table_fails_to_load_cleanly(self):
        rc, env = self.run_r0(adapter_copy(self, mini_text() + FUNCTIONS))
        c = env["checks"]["R0"]
        self.assertEqual((rc, c["status"], env["entries"]), (0, "pass", []), c)
        got = {x["case"]: (x["status"], x["got"]) for x in c["cases"] if x["kind"] == "malformed-table"}
        self.assertEqual({k: v[0] for k, v in got.items()},
                         {"ident-chars": "pass", "empty-asserts": "pass", "unbalanced-brackets": "pass"})
        self.assertIn("(ident-chars): lexer.ident_chars: `(` cannot be part of a word", got["ident-chars"][1])
        self.assertIn("(empty-asserts): asserts: no assert shape", got["empty-asserts"][1])
        self.assertIn("(unbalanced-brackets): lexer.brackets[0]: `(`: want an opener and a closer",
                      got["unbalanced-brackets"][1])

    def test_an_adapter_that_misses_a_skip_marker_fails_and_names_the_skip_cheat(self):
        weak = mini_text().replace('skip = ["xtest"]\n', "") + FUNCTIONS
        rc, env = self.run_r0(adapter_copy(self, weak))
        c = env["checks"]["R0"]
        self.assertEqual((rc, c["status"]), (1, "fail"))
        self.assertEqual([x["case"] for x in c["cases"] if x["status"] == "fail"], ["skip"])
        self.assertEqual([(e["check"], e["class"], e["severity"]) for e in env["entries"]],
                         [("R0", "adapter-fix", "fail")])
        self.assertIn("cheat `skip` gave no R2 fail: #[ignore] / skip / xfail / only on a test entry",
                      env["entries"][0]["problem"])

    def test_an_adapter_that_flags_an_honest_helper_fails_and_names_the_control(self):
        rc, env = self.run_r0(MINI)  # mini.toml has no [functions]: asserts moved into a helper read as dropped
        c = env["checks"]["R0"]
        self.assertEqual((rc, c["status"]), (1, "fail"))
        self.assertEqual([x["case"] for x in c["cases"] if x["status"] == "fail"], ["helper-asserts"])
        self.assertEqual(len(env["entries"]), 1)
        self.assertIn("control `helper-asserts` gave 1 entries: assertions in test `adds` dropped from 2 to 0 "
                      "(want no entry)", env["entries"][0]["problem"])

    def test_a_cheat_with_no_fixture_reads_unproven_and_never_all_pass(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for fn in os.listdir(MINI_FIXTURES):
            if not fn.startswith("suppression."):
                with open(os.path.join(MINI_FIXTURES, fn)) as src, open(os.path.join(tmp.name, fn), "w") as dst:
                    dst.write(src.read())
        rc, env = self.run_r0(adapter_copy(self, mini_text() + FUNCTIONS), fixtures=tmp.name)
        c = env["checks"]["R0"]
        self.assertEqual((rc, c["status"], env["entries"]), (0, "unproven", []))
        self.assertEqual([(x["case"], x["got"]) for x in c["cases"] if x["status"] == "unproven"],
                         [("suppression", "no fixture `suppression.mini.r0`")])
        self.assertIn("unproven (no fixture): suppression", c["note"])
        self.assertFalse(env["summary"].startswith("all pass"))
        self.assertIn("unproven: R0", env["summary"])


SCENARIO_HELPER = {  # a helper outside any test fn, two asserts: only a test path counts them all
    "rust": ("h.rs", "fn check(x: i32) {\n    assert_eq!(x, 3);\n    assert_ne!(x, 4);\n}\n"),
    "python": ("h.py", "def check(x):\n    assert x == 3\n    assert x != 4\n"),
    "ts": ("h.ts", "function check(x: number) {\n  expect(x).toBe(3);\n  expect(x).not.toBe(4);\n}\n"),
}


class ScenariosAreTestPaths(unittest.TestCase):
    """C4: the core adds `.ekit/scenarios/**` to the test paths of every stack, whatever --test-paths says."""

    def test_every_stack(self):
        for stack, (name, text) in SCENARIO_HELPER.items():
            with self.subTest(stack=stack):
                repo, _ = tmp_repo(self)
                path = f".ekit/scenarios/x/{name}"
                base = repo.commit({path: text})
                lines = text.splitlines(keepends=True)
                head = repo.commit({path: "".join(ln for ln in lines if "4" not in ln)})
                r = _kit.run_cli(["r2", "--repo", repo.path, "--base", base, "--head", head, "--stack", stack,
                                  "--test-paths", "tests/**"])
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertEqual([(e["file"], e["problem"]) for e in json.loads(r.stdout)["entries"]],
                                 [(path, f"assertions outside test fns in `{path}` dropped from 2 to 1")])


BUILTIN_PY = os.path.join(_kit.ROOT, "scripts", "mech_review", "r0_fixtures", "python")


def broken_python_fixtures(case):
    """the python fixtures with `skip.py.r0` the seed itself: the skip cheat then gives no entry and R0 fails."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    for fn in os.listdir(BUILTIN_PY):
        with open(os.path.join(BUILTIN_PY, "seed.py.r0" if fn == "skip.py.r0" else fn)) as src:
            text = src.read()
        with open(os.path.join(tmp.name, fn), "w") as dst:
            dst.write(text)
    return tmp.name


class AllRunsR0First(unittest.TestCase):
    """C5, C7: `all` runs R0 first. A failed R0 is exactly one adapter-fix entry and blocks R1, R2 and R4 (n/a, the cause
    named); a passed R0 leaves them to run as before. Subcommands that do not run R0 hold no R0."""

    def setUp(self):
        self.repo, _ = tmp_repo(self)
        self.base = self.repo.commit({"tests/test_a.py": "def test_a():\n    assert 1 == 1\n"})
        self.head = self.repo.commit({"tests/test_a.py": "def test_b():\n    assert 2 == 2\n"})  # removed test_a

    def run_all(self, *extra):
        return _kit.run_cli(["all", "--repo", self.repo.path, "--base", self.base, "--head", self.head, "--stack",
                             "python", "--test-paths", "tests/**", *extra])

    def test_a_failed_r0_is_one_adapter_fix_entry_and_blocks_the_checks_that_read_tests(self):
        r = self.run_all("--fixtures", broken_python_fixtures(self))
        self.assertEqual(r.returncode, 1, r.stderr)
        env = json.loads(r.stdout)
        self.assertEqual([e for e in env["entries"] if e["class"] == "adapter-fix"],
                         [e for e in env["entries"] if e["check"] == "R0"])
        self.assertEqual(len([e for e in env["entries"] if e["check"] == "R0"]), 1)
        self.assertEqual(env["checks"]["R0"]["status"], "fail")
        for c in ("R2", "R4"):
            self.assertEqual(env["checks"][c]["status"], "n/a", c)
            self.assertTrue(env["checks"][c]["note"].startswith("blocked: R0 failed (R0 static half failed for the "
                                                                "`python` adapter: cheat `skip` gave no"), env["checks"][c])
        self.assertEqual(env["checks"]["R1"]["status"], "skipped")  # it did not run: nothing to block
        self.assertEqual(env["checks"]["R3"]["status"], "skipped")

    def test_a_failed_r0_hides_no_entry_and_its_waiver_never_passes_the_blocked_ones(self):
        head = self.repo.commit({".github/x.yml": "x\n"})
        r = _kit.run_cli(["all", "--repo", self.repo.path, "--base", self.base, "--head", head, "--stack", "python",
                          "--test-paths", "tests/**", "--protected-paths", ".github/**",
                          "--fixtures", broken_python_fixtures(self)])
        env = json.loads(r.stdout)
        got = sorted((e["check"], e["class"], e["severity"], e.get("blocked")) for e in env["entries"])
        self.assertEqual(got, [("R0", "adapter-fix", "fail", None), ("R2", "agent-fixable", "fail", "R0"),
                               ("R2", "needs-human", "fail", "R0")])
        r0e = next(e for e in env["entries"] if e["check"] == "R0")
        out = waiver.apply(env, {r0e["id"]: {"by": "owner", "reason": "urgent", "url": ""}})
        self.assertTrue(out["summary"].startswith(f"fail {head} (2 fail, 0 confirm, 1 waived;"), out["summary"])
        self.assertEqual(comment.exit_code(out), 1)

    def test_a_passed_r0_runs_the_rest_as_before(self):
        r = self.run_all()
        env = json.loads(r.stdout)
        self.assertEqual(env["checks"]["R0"]["status"], "pass")
        self.assertEqual(env["checks"]["R2"]["status"], "fail")
        self.assertEqual([(e["check"], e["problem"]) for e in env["entries"]], [("R2", "test fn `test_a` removed")])
        self.assertTrue(env["summary"].startswith(f"fail {self.head} (1 fail, 0 confirm; ran: R0 R2"), env["summary"])

    def test_r2_holds_no_r0(self):
        r = _kit.run_cli(["r2", "--repo", self.repo.path, "--base", self.base, "--head", self.head, "--stack", "python",
                          "--test-paths", "tests/**"])
        env = json.loads(r.stdout)
        self.assertNotIn("R0", env["checks"])
        self.assertEqual(env["summary"], f"fail {self.head} (1 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)")


PLAN = """ignore = ["examples"]

[[stack]]
name = "app"
folder = "."
adapter = "python"
status = "current"
target-os = "linux"

[[stack]]
name = "mini"
folder = "m"
adapter = ".ekit/adapters/mini.toml"
status = "current"
"""
def adapter_with(limits="max-mutants = 40\nmutation-budget = 10\ncensus = 100\nassert-density = 10\n", top=""):
    """mini.toml with these [limits] (and top-level lines before its first key)."""
    return top + mini_text() + "\n[limits]\n" + limits


LIMITS = adapter_with()
CALLER = """name: mech-review
on: pull_request
jobs:
  mech:
    uses: EricleungDK/ekit/.github/workflows/mech-review.yml@v0
    with:
      stack: python
      max-mutants: "40"
      mutation-budget: 10
"""


class EditingRules(unittest.TestCase):
    """C6: editing the plan or an adapter file needs no person, except loosening a limit (an adapter file's [limits]:
    max-mutants, mutation-budget, census, assert-density; the caller workflow's max-mutants and mutation-budget inputs;
    the plan's ignore list) or changing a target OS: exactly one needs-human entry naming each. Tightening gives none.
    Stacks are matched by folder, each side's adapter read through its own plan."""

    def setUp(self):
        self.repo, _ = tmp_repo(self)
        self.base = self.repo.commit({".ekit/stack-plan.toml": PLAN, ".ekit/adapters/mini.toml": LIMITS,
                                      ".github/workflows/mech.yml": CALLER})

    def entries(self, plan=PLAN, limits=LIMITS, caller=CALLER, extra=None):
        files = {".ekit/stack-plan.toml": plan, ".ekit/adapters/mini.toml": limits, ".github/workflows/mech.yml": caller}
        head = self.repo.commit(dict(files, **(extra or {})))
        r = r0(self.repo, self.base, head, "--stack", "python")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        env = json.loads(r.stdout)
        return r.returncode, env["entries"], env

    def test_tightening_every_limit_needs_no_person(self):
        tight = adapter_with("max-mutants = 60\nmutation-budget = 20\ncensus = 100\nassert-density = 5\n")
        rc, ents, env = self.entries(plan=PLAN.replace('ignore = ["examples"]', "ignore = []"), limits=tight,
                                     caller=CALLER.replace('"40"', '"80"').replace("budget: 10", "budget: 15"))
        self.assertEqual((rc, ents, env["checks"]["R0"]["status"]), (0, [], "pass"))

    def test_a_removed_limit_reads_its_default(self):
        rc, ents, _ = self.entries(limits=adapter_with("mutation-budget = 10\ncensus = 100\nassert-density = 10\n"))
        self.assertEqual(ents, [])  # max-mutants' default is 40: not looser

    def test_loosening_a_limit_and_changing_a_target_os_give_exactly_one_needs_human_entry(self):
        loose = adapter_with("max-mutants = 20\nmutation-budget = 10\ncensus = 100\nassert-density = 30\n")
        plan = PLAN.replace('ignore = ["examples"]', 'ignore = ["examples", "src"]').replace(
            'target-os = "linux"', 'target-os = "windows"')
        rc, ents, env = self.entries(plan=plan, limits=loose)
        self.assertEqual(rc, 1)
        self.assertEqual([(e["check"], e["class"], e["severity"], e["file"]) for e in ents],
                         [("R0", "needs-human", "fail", ".ekit/stack-plan.toml")])
        self.assertEqual(ents[0]["problem"], "a person decides: `ignore` gains `src` in .ekit/stack-plan.toml; stack in "
                                             "folder `.` target-os linux -> windows in .ekit/stack-plan.toml; "
                                             "`limits.assert-density` 10 -> 30 for the stack in folder `m` "
                                             "(.ekit/adapters/mini.toml); `limits.max-mutants` 40 -> 20 for the stack "
                                             "in folder `m` (.ekit/adapters/mini.toml)")

    def test_each_loosening_alone_is_named(self):
        cases = [
            ({"limits": adapter_with("mutation-budget = 5\n")},
             "`limits.mutation-budget` 10 -> 5 for the stack in folder `m`"),
            ({"limits": adapter_with("census = 90\n")}, "`limits.census` 100 -> 90 for the stack in folder `m`"),
            ({"limits": adapter_with(top='target-os = "macos"\n')},
             "stack in folder `m` target-os linux -> macos in .ekit/adapters/mini.toml"),
            ({"caller": CALLER.replace('"40"', '"20"')},
             "`max-mutants` 40 -> 20 in .github/workflows/mech.yml (the mech-review inputs)"),
            ({"caller": CALLER.replace("budget: 10", "budget: 2")},
             "`mutation-budget` 10 -> 2 in .github/workflows/mech.yml (the mech-review inputs)"),
            # a new adapter file: its limits compare with the old one's, through each side's plan
            ({"plan": PLAN.replace(".ekit/adapters/mini.toml", ".ekit/adapters/n.toml"),
              "extra": {".ekit/adapters/n.toml": adapter_with("max-mutants = 5\n")}},
             "`limits.max-mutants` 40 -> 5 for the stack in folder `m` (.ekit/adapters/n.toml)"),
            # a renamed stack keeps its folder: the target OS change is still seen
            ({"plan": PLAN.replace('name = "app"', 'name = "app2"').replace('target-os = "linux"',
                                                                             'target-os = "windows"')},
             "stack in folder `.` target-os linux -> windows"),
            ({"limits": adapter_with('max-mutants = "60"\n')},
             "limits.max-mutants: want a whole number >= 1"),
        ]
        for kw, want in cases:
            with self.subTest(want=want):
                rc, ents, _ = self.entries(**kw)
                self.assertEqual(len(ents), 1, ents)
                self.assertEqual(ents[0]["class"], "needs-human")
                self.assertIn(want, ents[0]["problem"])


class RustUnbalanced(unittest.TestCase):
    """the rust adapter reports a file whose brackets do not balance, as python and ts do: R2 names it, never silent."""

    def test_an_unclosed_brace_is_an_unparseable_entry(self):
        repo, _ = tmp_repo(self)
        base = repo.commit({"tests/a.rs": "#[test]\nfn one() {\n    assert_eq!(1, 1);\n}\n"})
        head = repo.commit({"tests/a.rs": "#[test]\nfn one() {{\n    assert_eq!(1, 1);\n}\n"})
        r = _kit.run_cli(["r2", "--repo", repo.path, "--base", base, "--head", head, "--stack", "rust",
                          "--test-paths", "tests/**"])
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual([(e["line"], e["problem"]) for e in json.loads(r.stdout)["entries"]],
                         [(2, "file does not parse: `{` is never closed (line 2)")])


def fixture_copy(case, src, replace):
    """a copy of the fixture dir src with replace's {file name: text} written over it: its path."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    for fn in os.listdir(src):
        with open(os.path.join(src, fn)) as f, open(os.path.join(tmp.name, fn), "w") as dst:
            dst.write(f.read())
    for fn, text in replace.items():
        with open(os.path.join(tmp.name, fn), "w") as dst:
            dst.write(text)
    return tmp.name


class BadFixturesFailCleanly(unittest.TestCase):
    """a seed or fixture the adapter cannot parse is an R0 fail naming it (fixture dirs may come from the PR), never a
    crash; a built-in's entry points at its fixture dir."""

    def run_r0(self, fixtures):
        repo, base = tmp_repo(self)
        r = r0(repo, base, base, "--stack", "python", "--fixtures", fixtures)
        self.assertEqual(r.returncode, 1, r.stderr)
        return json.loads(r.stdout)

    def test_a_seed_that_does_not_parse(self):
        env = self.run_r0(fixture_copy(self, BUILTIN_PY, {"seed.py.r0": "# x\ndef test_a(:\n"}))
        [e] = env["entries"]
        self.assertEqual(e["class"], "adapter-fix")
        self.assertIn("`seed.py.r0` does not parse: ", e["problem"])
        self.assertEqual({x["status"] for x in env["checks"]["R0"]["cases"] if x["kind"] != "malformed-table"}, {"fail"})

    def test_a_fixture_that_does_not_parse(self):
        env = self.run_r0(fixture_copy(self, BUILTIN_PY, {"skip.py.r0": "def test_a(:\n"}))
        c = env["checks"]["R0"]
        self.assertEqual([x["case"] for x in c["cases"] if x["status"] == "fail"], ["skip"])
        self.assertIn("fixture `skip.py.r0` does not parse: ", env["entries"][0]["problem"])

    def test_the_entry_names_the_fixture_dir(self):
        fixtures = broken_python_fixtures(self)
        env = self.run_r0(fixtures)
        self.assertEqual(env["entries"][0]["file"], fixtures)

    def test_a_built_in_entry_names_ekit_s_fixture_dir(self):
        from scripts.mech_review import r0 as r0_mod
        from scripts.mech_review.stack import ADAPTERS

        class SkipBlind(ADAPTERS["python"]):
            def test_fns(self, text):
                return [f._replace(markers=[]) for f in super().test_fns(text)]

        _, entries = r0_mod.static(SkipBlind(), r0_mod.load_fixtures(BUILTIN_PY))
        self.assertEqual(entries[0]["file"], "ekit:scripts/mech_review/r0_fixtures/python")

    def test_an_internal_error_is_a_usage_exit_with_no_result_never_exit_1(self):
        from unittest import mock
        from scripts.mech_review import r0 as r0_mod
        repo, base = tmp_repo(self)
        with mock.patch.object(r0_mod, "static", side_effect=RuntimeError("boom")):
            r = r0(repo, base, base, "--stack", "python")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("mech-review: r0 crashed: RuntimeError: boom", r.stderr)


class LimitsTable(unittest.TestCase):
    """the adapter file's optional [limits] table (#20): max-mutants, mutation-budget, assert-density, census; whole
    numbers, validated like every other key."""

    def load(self, table):
        from scripts.mech_review import adapter_file
        return adapter_file.loads((mini_text() + "\n[limits]\n" + table).encode(), "x.toml")

    def test_whole_numbers_load_and_read_back(self):
        a = self.load("max-mutants = 20\nmutation-budget = 5\nassert-density = 10\ncensus = 100\n")
        self.assertEqual(a.limits, {"max-mutants": 20, "mutation-budget": 5, "assert-density": 10, "census": 100})
        self.assertEqual(self.load("").limits, {})

    def test_a_bad_value_or_key_is_a_load_error_naming_it(self):
        from scripts.mech_review import adapter_file
        for table, want in [('max-mutants = "60"\n', "limits.max-mutants: want a whole number >= 1"),
                            ("census = 101\n", "limits.census: want a whole number from 0 to 100"),
                            ("maxMutants = 3\n", "limits.maxMutants: unknown key"),
                            ("mutation-budget = true\n", "limits.mutation-budget: want a whole number >= 1")]:
            with self.subTest(table=table):
                with self.assertRaises(adapter_file.AdapterFileError) as e:
                    self.load(table)
                self.assertIn(want, str(e.exception))


if __name__ == "__main__":
    unittest.main()
