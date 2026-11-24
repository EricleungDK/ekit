"""R1 and R4 through an adapter file (#18): `mech-review.py red --stack <name> --adapter <file>` on fixture git repos,
through cli.main in this process. The runner is a stub (MECH_TEST_STUB) that replays captured vitest and jest output
(tests/fixtures/vitest, tests/fixtures/jest) for the outcome each test is given in the repo's tests/outcomes file.
Each TS case also runs the built-in `ts` adapter on the same repo: the file must give the built-in's checks and entries."""
import json
import os
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

import _kit
from scripts.mech_review import adapter_file

TS_FILE = os.path.join(_kit.ROOT, "scripts", "mech_review", "adapters", "ts.toml")
MINI = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.toml")
FX = os.path.join(_kit.ROOT, "tests", "fixtures")

# the runner: argv is the test command's words after argv[0], then the adapter's one-test words. Logs `cwd | argv`.
# tests/outcomes (a test-path file, so on the base's code too): `<leaf> <outcome on the base> <outcome at head>`;
# head is the checkout whose src/calc.ts says `fixed`. A leaf not listed passes.
STUB = r'''
import os, sys
FX, LOG = os.environ["STUB_FX"], os.environ["STUB_LOG"]
args = sys.argv[1:]
with open(LOG, "a") as f:
    f.write(os.path.realpath(os.getcwd()) + " | " + " ".join(args) + "\n")
pat = args[args.index("-t") + 1] if "-t" in args else ""
leaf = pat.strip("^$").split(" > ")[-1].split(" ")[-1]
flavour = "vitest" if args[:1] == ["run"] else "jest"
try:
    fixed = "fixed" in open("src/calc.ts").read()
except OSError:
    fixed = False
outcome = "pass"
if os.path.exists("tests/outcomes"):
    for line in open("tests/outcomes"):
        w = line.split()
        if w and w[0] == leaf:
            outcome = w[2] if fixed else w[1]
if outcome == "flaky":
    state = os.path.join(os.path.dirname(LOG), "flaky-" + leaf)
    n = int(open(state).read()) + 1 if os.path.exists(state) else 1
    open(state, "w").write(str(n))
    outcome = "fail" if n % 2 else "pass"
if outcome == "error":
    print("boom: no test result")
    sys.exit(1)
sys.stdout.write(open(os.path.join(FX, flavour, outcome + ".txt")).read())
sys.exit(0 if outcome in ("pass", "none") else 1)
'''

TEST = '''import { describe, it, expect } from "vitest";
import { add } from "../src/calc";

describe("Calc", () => {
  it("adds", () => {
    expect(add(1, 2)).toBe(3);
  });
});
'''
TEST_FRESH = TEST.replace("  });\n});", '  });\n  it("fresh", () => {\n    expect(add(1, 2)).toBe(3);\n  });\n});')
SRC = "export function add(a: number, b: number): number {\n  return a + b;\n}\n"


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(self.tmp, "repo")
        self.log = os.path.join(self.tmp, "calls.log")
        stub = os.path.join(self.tmp, "stub.py")
        with open(stub, "w") as f:
            f.write(STUB)
        env = mock.patch.dict(os.environ, {"MECH_TEST_STUB": stub, "STUB_FX": FX, "STUB_LOG": self.log})
        env.start()
        self.addCleanup(env.stop)
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        import subprocess
        return subprocess.run(["git", "-C", self.repo, "-c", "user.email=t@t", "-c", "user.name=t",
                               "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout

    def commit(self, files):
        for rel, text in files.items():
            full = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", newline="\n") as f:
                f.write(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")
        return self.git("rev-parse", "HEAD").strip()

    def ts_repo(self, outcomes, dep="vitest", files=None):
        """base: Calc > adds; head: Calc > fresh added, src fixed. outcomes: tests/outcomes at head."""
        base = self.commit({".gitignore": "node_modules/\n", "src/calc.ts": SRC, "tests/calc.test.ts": TEST,
                            "package.json": '{"name":"calc","devDependencies":{"%s":"1.0.0"}}\n' % dep})
        head = self.commit(dict({"tests/calc.test.ts": TEST_FRESH, "tests/outcomes": outcomes,
                                 "src/calc.ts": SRC.replace("a + b;", "a + b; // fixed")}, **(files or {})))
        return base, head

    def red(self, base, head, *extra, adapter=TS_FILE, stack="ts", check="red"):
        argv = [check, "--repo", self.repo, "--base", base, "--head", head, "--stack", stack, "--test-paths", "tests/**",
                "--head-branch", "agent/x"] + (["--adapter", adapter] if adapter else []) + list(extra)
        return _kit.run_cli(argv)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            lines = f.read().splitlines()
        os.remove(self.log)
        for name in os.listdir(self.tmp):  # the flaky counters start again for the next run
            if name.startswith("flaky-"):
                os.remove(os.path.join(self.tmp, name))
        return lines

    def both(self, base, head, *extra):
        """(file result, built-in result) as (rc, checks, entries, runner calls): the file must equal the built-in."""
        out = []
        for adapter in (TS_FILE, None):
            r = self.red(base, head, *extra, adapter=adapter)
            self.assertIn(r.returncode, (0, 1), r.stderr)
            env = json.loads(r.stdout)
            out.append((r.returncode, env["checks"], env["entries"], [c.split(" | ", 1)[1] for c in self.calls()]))
        self.assertEqual(out[0], out[1], "the adapter file must give the built-in ts adapter's result")
        return out[0]


class TsRunThroughTheFile(Fixture):
    def test_a_test_red_on_the_base_and_green_at_head_passes_r1_and_r4(self):
        rc, checks, entries, calls = self.both(*self.ts_repo("fresh fail pass\n"))
        self.assertEqual(rc, 0)
        self.assertEqual(entries, [])
        self.assertEqual(checks["R1"], {"status": "pass",
                                        "note": "1 of 1 new or changed test(s) fail on the base's production code"})
        self.assertEqual(checks["R4"], {"status": "pass", "note": "1 new or changed test(s) run 5x at head"})
        self.assertEqual(calls, ["run tests/calc.test.ts -t ^Calc fresh$"] * 6)

    def test_a_new_test_that_does_not_build_on_the_base_counts_as_red(self):
        rc, checks, entries, _ = self.both(*self.ts_repo("fresh build pass\n"))
        self.assertEqual((rc, entries), (0, []))
        self.assertEqual(checks["R1"], {"status": "pass", "note": "1 of 1 new or changed test(s) fail on the base's "
                                                                  "production code (1 compile-red)"})

    def test_a_filter_that_runs_nothing_on_the_base_is_never_a_pass(self):
        base, head = self.ts_repo("fresh none pass\n")
        rc, checks, entries, _ = self.both(base, head)
        self.assertEqual(rc, 1)
        self.assertEqual(checks["R1"]["status"], "fail")
        self.assertEqual([(e["check"], e["severity"], e["class"], e["problem"]) for e in entries], [
            ("R1", "fail", "agent-fixable",
             "`Calc > fresh` cannot be proven red on the base's production code (none: RUN  v5.0.5 /work/cap-v)")])

    def test_jest_from_package_json_runs_the_space_joined_name_without_run(self):
        rc, checks, _, calls = self.both(*self.ts_repo("fresh fail pass\n", dep="jest"))
        self.assertEqual((rc, checks["R1"]["status"], checks["R4"]["status"]), (0, "pass", "pass"))
        self.assertEqual(calls[0], "tests/calc.test.ts -t ^Calc fresh$")

    def test_a_flaky_test_at_head_fails_r4_naming_the_runs(self):
        rc, checks, entries, _ = self.both(*self.ts_repo("fresh fail flaky\n"))
        self.assertEqual(rc, 1)
        self.assertEqual([(e["check"], e["problem"]) for e in entries],
                         [("R4", "test `Calc > fresh` failed 3 of 5 runs at head (fail)")])

    def test_a_test_that_does_not_run_at_head_reads_none_never_pass(self):
        rc, checks, entries, _ = self.both(*self.ts_repo("fresh fail none\n"))
        self.assertEqual((rc, checks["R4"]["status"]), (1, "fail"))
        self.assertEqual([(e["check"], e["problem"]) for e in entries], [("R4", "test `Calc > fresh` did not run at head")])

    def test_a_test_that_does_not_build_at_head_fails_r4(self):
        rc, checks, entries, _ = self.both(*self.ts_repo("fresh fail build\n"))
        self.assertEqual(rc, 1)
        self.assertEqual([(e["check"], e["problem"]) for e in entries],
                         [("R4", "does not build at head: `Calc > fresh` cannot run")])

    def test_regex_characters_in_a_name_are_literal_and_each_placeholders_match_any_value(self):
        test = TEST.replace("  });\n});", '  });\n  it("adds (1) [x] $a", () => {\n    expect(1).toBe(1);\n  });\n'
                                          '  it.each([[1, 2]])("sums %i and %i", (a, b) => {\n'
                                          '    expect(a).toBe(b);\n  });\n});')
        base, head = self.ts_repo("x fail pass\n", files={"tests/calc.test.ts": test})
        _, _, _, calls = self.both(base, head)
        self.assertEqual(calls[:2], ["run tests/calc.test.ts -t ^Calc adds \\(1\\) \\[x\\] .*$",
                                     "run tests/calc.test.ts -t ^Calc sums .* and .*$"])

    def test_a_missing_runner_is_na_env_naming_the_runner_and_the_adapters_install_command(self):
        base, head = self.ts_repo("fresh fail pass\n")
        with mock.patch.dict(os.environ):
            del os.environ["MECH_TEST_STUB"]
            r = self.red(base, head)
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        fix = "run the adapter's install command (`npm ci`), or set setup-command"
        self.assertEqual(env["checks"]["R1"], {"status": "n/a", "note": "toolchain absent: `node_modules/.bin/vitest` "
                                               f"not found (env): {fix} (tests on the base's production code)"})
        self.assertEqual(env["checks"]["R4"], {"status": "n/a", "note": "toolchain absent: `node_modules/.bin/vitest` "
                                               f"not found (env): {fix} (new or changed tests)"})
        self.assertNotIn("all pass", env["summary"])

    def test_the_callers_node_modules_is_linked_into_the_worktree_and_survives(self):
        base, head = self.ts_repo("fresh fail pass\n")
        bin_dir = os.path.join(self.repo, "node_modules", ".bin")
        os.makedirs(bin_dir)
        runner = os.path.join(bin_dir, "vitest")
        with open(runner, "w") as f:
            f.write(f"#!/bin/sh\nif grep -q fixed src/calc.ts; then cat '{FX}/vitest/pass.txt'; exit 0; fi\n"
                    f"cat '{FX}/vitest/fail.txt'; exit 1\n")
        os.chmod(runner, 0o755)
        with mock.patch.dict(os.environ):
            del os.environ["MECH_TEST_STUB"]
            r = self.red(base, head)
        env = json.loads(r.stdout)
        self.assertEqual((r.returncode, env["checks"]["R1"]["status"], env["checks"]["R4"]["status"]), (0, "pass", "pass"))
        self.assertTrue(os.access(runner, os.X_OK))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_a_custom_vitest_command_gets_run_after_the_vitest_word(self):
        base, head = self.ts_repo("fresh fail pass\n")
        _, _, _, calls = self.both(base, head, "--test-cmd", "npx vitest --silent")
        self.assertEqual(calls[0], "vitest run --silent tests/calc.test.ts -t ^Calc fresh$")


MINI_RUN = '''
[commands]
install = "mini fetch"
build = "mini build"
lint = ""
test = "minitest"

[run]
test = ["--file", "{path}", "--only", "{name}"]

[run.outcome]
passed = '(\\d+) passed'
failed = '(\\d+) failed'
skipped = '(\\d+) skipped'
build = '^compile error'
no_test = '^no test named'
env = 'runtime not installed'
'''
# mini's runner: `<leaf> <outcome on the base> <outcome at head>` in tests/outcomes; head's src/calc.mini says `fixed`
MINI_STUB = r'''
import os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(os.path.realpath(os.getcwd()) + " | " + " ".join(sys.argv[1:]) + "\n")
leaf = sys.argv[sys.argv.index("--only") + 1].split(" / ")[-1]
fixed = "fixed" in open("src/calc.mini").read()
outcome = "pass"
for line in open("tests/outcomes"):
    w = line.split()
    if w and w[0] == leaf:
        outcome = w[2] if fixed else w[1]
text, rc = {"pass": ("ok: 1 passed\n", 0), "fail": ("1 failed, 0 passed\n", 1), "skipped": ("0 passed, 1 skipped\n", 0),
            "notest": ("no test named " + leaf + "\n", 1), "build": ("compile error: add/3 undefined\n", 2),
            "env": ("minitest: runtime not installed\n", 127), "passrc": ("1 passed\n", 1),
            "quiet": ("minitest 1.0\n", 0), "envbanner": ("minitest 1.0\nboot: runtime not installed (erlang)\n", 127),
            "notestbanner": ("minitest 1.0\nno test named " + leaf + "\n", 1)}[outcome]
sys.stdout.write(text)
sys.exit(rc)
'''
MINI_TEST = '''suite("Calc", {
  test("adds", {
    assertEquals(3, add(1, 2))
  })
})
'''
MINI_FRESH = MINI_TEST.replace("  })\n})", '  })\n  test("fresh", {\n    assertEquals(3, add(1, 2))\n  })\n})')


class MiniRunThroughTheFile(Fixture):
    """a stack no built-in knows: tests/fixtures/adapters/mini.toml (R2) plus a [run] and [commands] of its own."""

    def setUp(self):
        super().setUp()
        with open(MINI) as f:
            text = f.read()
        self.adapter = os.path.join(self.tmp, "mini.toml")
        with open(self.adapter, "w") as f:
            f.write(text + MINI_RUN)
        with open(os.environ["MECH_TEST_STUB"], "w") as f:
            f.write(MINI_STUB)

    def mini(self, outcomes):
        base = self.commit({"src/calc.mini": "fn add(a, b) { a + b }\n", "tests/calc.mini": MINI_TEST})
        head = self.commit({"tests/calc.mini": MINI_FRESH, "tests/outcomes": outcomes,
                            "src/calc.mini": "fn add(a, b) { a + b } # fixed\n"})
        r = self.red(base, head, adapter=self.adapter, stack="mini")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        env = json.loads(r.stdout)
        return r.returncode, env["checks"], [(e["check"], e["problem"]) for e in env["entries"]]

    def test_red_on_the_base_and_green_at_head_runs_the_named_test_with_the_files_words(self):
        rc, checks, entries = self.mini("fresh fail pass\n")
        self.assertEqual((rc, entries, checks["R1"]["status"], checks["R4"]["status"]), (0, [], "pass", "pass"))
        self.assertEqual({c.split(" | ", 1)[1] for c in self.calls()}, {"--file tests/calc.mini --only Calc / fresh"})

    def test_a_skipped_test_on_the_base_reads_none_never_pass(self):
        rc, checks, entries = self.mini("fresh skipped pass\n")
        self.assertEqual((rc, checks["R1"]["status"]), (1, "fail"))
        self.assertEqual(entries, [("R1", "`Calc / fresh` cannot be proven red on the base's production code "
                                          "(none: 0 passed, 1 skipped)")])

    def test_no_such_test_at_head_reads_none_did_not_run(self):
        rc, _, entries = self.mini("fresh fail notest\n")
        self.assertEqual((rc, entries), (1, [("R4", "test `Calc / fresh` did not run at head")]))

    def test_a_build_failure_on_the_base_is_compile_red(self):
        rc, checks, entries = self.mini("fresh build pass\n")
        self.assertEqual((rc, entries), (0, []))
        self.assertEqual(checks["R1"]["note"], "1 of 1 new or changed test(s) fail on the base's production code "
                                               "(1 compile-red)")

    def test_a_passed_count_with_a_failing_exit_is_a_fail(self):
        rc, _, entries = self.mini("fresh fail passrc\n")
        self.assertEqual((rc, entries), (1, [("R4", "test `Calc / fresh` failed 5 of 5 runs at head (fail)")]))

    def test_output_with_no_count_is_a_test_that_cannot_run(self):
        rc, _, entries = self.mini("fresh fail quiet\n")
        self.assertEqual((rc, entries), (1, [("R4", "test `Calc / fresh` cannot run at head: minitest 1.0")]))

    def test_the_env_pattern_is_na_naming_the_output_and_the_install_command(self):
        rc, checks, entries = self.mini("fresh env env\n")
        self.assertEqual((rc, entries), (0, []))
        self.assertEqual(checks["R1"], {"status": "n/a", "note": "toolchain absent (env): `minitest: runtime not "
                                        "installed`: run the adapter's install command (`mini fetch`), or set "
                                        "setup-command (tests on the base's production code)"})

    def test_the_env_note_quotes_the_line_the_env_pattern_matched_not_the_banner(self):
        _, checks, _ = self.mini("fresh envbanner pass\n")
        self.assertEqual(checks["R1"]["note"], "toolchain absent (env): `boot: runtime not installed (erlang)`: run the "
                                               "adapter's install command (`mini fetch`), or set setup-command (tests "
                                               "on the base's production code)")

    def test_a_no_such_test_entry_quotes_the_line_no_test_matched(self):
        _, _, entries = self.mini("fresh notestbanner pass\n")
        self.assertEqual(entries, [("R1", "`Calc / fresh` cannot be proven red on the base's production code "
                                          "(none: no test named fresh)")])

    def test_a_lookaround_build_pattern_never_turns_a_test_that_did_not_run_into_red(self):
        with open(self.adapter) as f:
            text = f.read()
        with open(self.adapter, "w") as f:  # loads (no load probe has a-w before it), and matches no text at run time
            f.write(text.replace("build = '^compile error'", "build = '(?<=[a-w])'"))
        rc, checks, entries = self.mini("fresh skipped pass\n")
        self.assertEqual((rc, checks["R1"]["status"]), (1, "fail"))
        self.assertEqual(entries, [("R1", "`Calc / fresh` cannot be proven red on the base's production code "
                                          "(none: 0 passed, 1 skipped)")])


class RunUsage(Fixture):
    def test_red_and_all_with_a_file_that_has_no_run_table_are_usage_errors_naming_it(self):
        head = self.commit({"tests/calc.mini": MINI_TEST})
        for check in ("red", "all"):
            r = self.red(head, head, adapter=MINI, stack="mini", check=check)
            self.assertEqual((r.returncode, r.stdout), (2, ""))
            self.assertIn(f"error: --adapter applies to r2 only for {MINI}: it has no [run] table, and {check} runs R1 "
                          "and R4 through [run] and [commands] (format: docs/mech-review-ci.md#adapter-file)\n", r.stderr)

    def test_r0_proves_the_shipped_ts_file_with_its_run_side(self):
        head = self.commit({"tests/calc.test.ts": TEST})
        fixtures = os.path.join(_kit.ROOT, "scripts", "mech_review", "r0_fixtures", "ts")  # none beside the file (#20)
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", head, "--head", head, "--stack", "ts", "--adapter", TS_FILE,
                          "--fixtures", fixtures, "--test-paths", "tests/**"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["checks"]["R0"]["status"], "pass")

    def test_a_file_whose_test_command_has_unbalanced_quotes_is_a_usage_error_not_a_crash(self):
        with open(TS_FILE) as f:
            text = f.read()
        bad = os.path.join(self.tmp, "ts.toml")
        with open(bad, "w") as f:
            f.write(text.replace('test = "node_modules/.bin/vitest run"', 'test = "vitest \'run"'))
        r = self.red(*self.ts_repo("fresh fail pass\n"), adapter=bad)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("commands.test: `vitest 'run`: unbalanced quotes (No closing quotation)", r.stderr)

    def test_a_declared_none_build_command_is_named_in_the_result(self):
        base, head = self.ts_repo("fresh fail pass\n")
        env = json.loads(self.red(base, head).stdout)
        self.assertEqual(env["notes"], ['adapter file declares no build command (commands.build = "")'])
        text = self.red(base, head, "--format", "text").stdout
        self.assertIn('\nnote: adapter file declares no build command (commands.build = "")', text)

    def test_declared_none_install_and_build_commands_are_both_named(self):
        with open(TS_FILE) as f:
            text = f.read()
        bare = os.path.join(self.tmp, "ts.toml")
        with open(bare, "w") as f:
            f.write(text.replace('install = "npm ci"', 'install = ""'))
        head = self.commit({"tests/calc.test.ts": TEST})
        env = json.loads(self.red(head, head, adapter=bare, check="all").stdout)
        self.assertEqual(env["notes"], ['adapter file declares no install command (commands.install = "")',
                                        'adapter file declares no build command (commands.build = "")'])

    def test_r2_through_the_file_prints_what_the_built_in_prints_with_no_notes(self):
        head = self.commit({"tests/calc.test.ts": TEST})
        through_file = self.red(head, head, check="r2")
        self.assertEqual(through_file.stdout, self.red(head, head, adapter=None, check="r2").stdout)
        self.assertNotIn("notes", json.loads(through_file.stdout))

    def test_an_adapter_that_names_every_command_has_no_notes(self):
        head = self.commit({"tests/calc.mini": MINI_TEST})
        with open(MINI) as f:
            text = f.read()
        full = os.path.join(self.tmp, "mini.toml")
        with open(full, "w") as f:
            f.write(text + MINI_RUN)
        self.assertEqual(json.loads(self.red(head, head, adapter=full, stack="mini").stdout)["notes"], [])
        self.assertNotIn("notes", json.loads(self.red(head, head, adapter=None, check="r2").stdout))

    def test_r3_through_a_file_runs_the_declared_tool(self):
        head = self.commit({"tests/calc.test.ts": TEST})
        # #19: no longer a usage error: R3 runs through the file's [mutation.tool] (ts.toml declares Stryker); with no
        # production change it is skipped, as the built-in's is (tests/py/test_adapter_mutation_ts.py runs it)
        for check in ("mutants", "baseline"):
            r = self.red(head, head, check=check)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["checks"]["R3"], {"status": "skipped",
                                                                   "note": "no production file changed"})

    def test_all_runs_r0_r1_r2_and_r4_through_the_file(self):
        base, head = self.ts_repo("fresh fail pass\n")
        r = self.red(base, head, check="all")
        env = json.loads(r.stdout)
        self.assertEqual((r.returncode, {k: v["status"] for k, v in env["checks"].items()}),
                         (0, {"R0": "pass", "R1": "pass", "R2": "pass", "R3": "skipped", "R4": "pass"}))


if __name__ == "__main__":
    unittest.main()
