"""R0 static half (#20): `mech-review.py r0` proves the stack adapter against the cheat suite and the negative controls,
git and adapter only. Through cli.main in this process (R3's mutmut sees only in-process calls)."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest

import _kit

CHEATS = ["delete", "comment-out", "rename", "skip", "expected-value", "weaken-assert", "suppression"]
CONTROLS = ["rename-same-asserts", "reorder-asserts", "helper-asserts", "empty-diff"]


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


def has_tomllib():
    return importlib.util.find_spec("tomllib") is not None  # adapter files need python 3.11+


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


@unittest.skipUnless(has_tomllib(), "adapter files need python 3.11+ (tomllib)")
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
        got = {x["case"]: (x["status"], x["got"]) for x in c["cases"] if x["kind"] == "malformed"}
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
        self.assertEqual([(e["check"], e["class"], e["severity"]) for e in env["entries"]],
                         [("R0", "adapter-fix", "fail")])
        self.assertEqual(env["checks"]["R0"]["status"], "fail")
        for c in ("R1", "R2", "R4"):
            self.assertEqual(env["checks"][c]["status"], "n/a", c)
            self.assertTrue(env["checks"][c]["note"].startswith("blocked: R0 failed (R0 static half failed for the "
                                                                "`python` adapter: cheat `skip` gave no"), env["checks"][c])
        self.assertEqual(env["checks"]["R3"]["status"], "skipped")
        self.assertEqual(env["summary"], f"fail {self.head} (1 fail, 0 confirm; ran: R0; skipped: R3; n/a: R1 R2 R4)")

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
LIMITS = "max-mutants = 40\nmutation-budget = 10\n\n[proof]\ncensus = 100\nassert-density = 10\n"


@unittest.skipUnless(has_tomllib(), "the plan and adapter files need python 3.11+ (tomllib)")
class EditingRules(unittest.TestCase):
    """C6: editing the plan or an adapter file needs no person, except loosening a limit (max-mutants, mutation budget,
    census or assert-density threshold, the plan's ignore list) or changing a target OS: exactly one needs-human entry
    naming each. Tightening gives none."""

    def setUp(self):
        self.repo, _ = tmp_repo(self)
        self.base = self.repo.commit({".ekit/stack-plan.toml": PLAN, ".ekit/adapters/mini.toml": LIMITS})

    def entries(self, plan=PLAN, limits=LIMITS):
        head = self.repo.commit({".ekit/stack-plan.toml": plan, ".ekit/adapters/mini.toml": limits})
        r = r0(self.repo, self.base, head, "--stack", "python")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        env = json.loads(r.stdout)
        return r.returncode, [e for e in env["entries"]], env

    def test_a_removed_limit_reads_its_default(self):
        rc, ents, _ = self.entries(limits=LIMITS.replace("max-mutants = 40\n", ""))  # the default is 40: not looser
        self.assertEqual(ents, [])
        rc, ents, _ = self.entries(limits=LIMITS.replace("census = 100\n", "census = 100\nmax-mutants = 80\n").replace(
            "max-mutants = 40\n", ""))
        self.assertEqual(ents, [])

    def test_tightening_every_limit_needs_no_person(self):
        tight = LIMITS.replace("40", "60").replace("mutation-budget = 10", "mutation-budget = 20").replace(
            "census = 100", "census = 100").replace("assert-density = 10", "assert-density = 5")
        rc, ents, env = self.entries(plan=PLAN.replace('ignore = ["examples"]', "ignore = []"), limits=tight)
        self.assertEqual((rc, ents, env["checks"]["R0"]["status"]), (0, [], "pass"))

    def test_loosening_a_limit_and_changing_a_target_os_give_exactly_one_needs_human_entry(self):
        loose = LIMITS.replace("max-mutants = 40", "max-mutants = 20").replace("assert-density = 10",
                                                                              "assert-density = 30")
        plan = PLAN.replace('ignore = ["examples"]', 'ignore = ["examples", "src"]').replace(
            'target-os = "linux"', 'target-os = "windows"')
        rc, ents, env = self.entries(plan=plan, limits=loose)
        self.assertEqual(rc, 1)
        self.assertEqual([(e["check"], e["class"], e["severity"], e["file"]) for e in ents],
                         [("R0", "needs-human", "fail", ".ekit/stack-plan.toml")])
        self.assertEqual(ents[0]["problem"], "a person decides: `ignore` gains `src` in .ekit/stack-plan.toml; stack `app` "
                                             "target-os linux -> windows in .ekit/stack-plan.toml; `max-mutants` 40 -> 20 "
                                             "in .ekit/adapters/mini.toml; `proof.assert-density` 10 -> 30 in "
                                             ".ekit/adapters/mini.toml")

    def test_each_loosening_alone_is_named(self):
        cases = [
            (LIMITS.replace("mutation-budget = 10", "mutation-budget = 5"),
             "`mutation-budget` 10 -> 5 in .ekit/adapters/mini.toml"),
            (LIMITS.replace("census = 100", "census = 90"), "`proof.census` 100 -> 90 in .ekit/adapters/mini.toml"),
            (LIMITS.replace("max-mutants = 40\n", "max-mutants = 41\n").replace("[proof]\n", "[proof]\nmax_mutants = 3\n"),
             "`proof.max_mutants` 40 (default) -> 3 in .ekit/adapters/mini.toml"),
            ('target-os = "macos"\n' + LIMITS, "adapter file .ekit/adapters/mini.toml target-os linux -> macos"),
        ]
        for limits, want in cases:
            with self.subTest(want=want):
                rc, ents, _ = self.entries(limits=limits)
                self.assertEqual(len(ents), 1)
                self.assertEqual(ents[0]["class"], "needs-human")
                self.assertIn(want, ents[0]["problem"])


if __name__ == "__main__":
    unittest.main()
