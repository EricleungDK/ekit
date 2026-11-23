"""R1 and R4 through the repo's own adapter file (#18 after #17): `red --stack <name>` with no --adapter takes
`.ekit/adapters/<name>.toml` at the base, as r2 does. With a [run] table the file drives R1 and R4, for a stack only the
repo defines and for one named like a built-in (an override); without [run], #17's behaviour stays (n/a for a
repo-only stack, the built-in's run side for an override). R3 through a file is #19: still n/a."""
import json
import os
import unittest

import _kit
from test_adapter_run import FX, MINI, MINI_FRESH, MINI_RUN, MINI_STUB, MINI_TEST, TEST, TEST_FRESH, TS_FILE, SRC, Fixture


def read(path):
    with open(path) as f:
        return f.read()


MINI_R2 = read(MINI)


class RepoAdapterRunSide(Fixture):
    def setUp(self):
        super().setUp()
        with open(os.environ["MECH_TEST_STUB"], "w") as f:
            f.write(MINI_STUB)

    def mini_pr(self, adapter_text, outcomes="fresh fail pass\n"):
        base = self.commit({"src/calc.mini": "fn add(a, b) { a + b }\n", "tests/calc.mini": MINI_TEST,
                            ".ekit/adapters/mini.toml": adapter_text})
        head = self.commit({"tests/calc.mini": MINI_FRESH, "tests/outcomes": outcomes,
                            "src/calc.mini": "fn add(a, b) { a + b } # fixed\n"})
        return base, head

    def run_check(self, check, base, head, stack="mini"):
        r = self.red(base, head, adapter=None, stack=stack, check=check)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return r.returncode, json.loads(r.stdout)

    def test_red_runs_r1_and_r4_through_a_repo_stacks_file_with_run(self):
        base, head = self.mini_pr(MINI_R2 + MINI_RUN)
        rc, env = self.run_check("red", base, head)
        self.assertEqual((rc, env["entries"]), (0, []))
        self.assertEqual(env["checks"]["R1"], {"status": "pass",
                                               "note": "1 of 1 new or changed test(s) fail on the base's production code"})
        self.assertEqual(env["checks"]["R4"], {"status": "pass", "note": "1 new or changed test(s) run 5x at head"})
        self.assertEqual({c.split(" | ", 1)[1] for c in self.calls()}, {"--file tests/calc.mini --only Calc / fresh"})
        self.assertEqual(env["notes"], [])

    def test_red_reads_the_bases_file_not_the_prs(self):
        base, head = self.mini_pr(MINI_R2 + MINI_RUN, outcomes="fresh pass pass\n")
        # the PR's file would run `--pick`, which the runner does not know: an error, never this R1 verdict
        head = self.commit({".ekit/adapters/mini.toml": MINI_R2 + MINI_RUN.replace('"--only"', '"--pick"')})
        rc, env = self.run_check("red", base, head)
        self.assertEqual((rc, [e["problem"].split(":")[0] for e in env["entries"] if e["check"] == "R1"]),
                         (1, ["no new or changed test fails without this PR's production change"]))

    def test_all_runs_r2_and_r1_r4_through_the_file_and_leaves_r0_to_r0(self):
        base, head = self.mini_pr(MINI_R2 + MINI_RUN)
        rc, env = self.run_check("all", base, head)
        self.assertEqual((rc, {c: v["status"] for c, v in env["checks"].items()}),
                         (0, {"R0": "skipped", "R1": "pass", "R2": "pass", "R3": "skipped", "R4": "pass"}))
        self.assertEqual(env["notes"], [])

    def test_a_failing_r1_through_the_repo_file_is_a_fail_entry(self):
        base, head = self.mini_pr(MINI_R2 + MINI_RUN, outcomes="fresh pass pass\n")
        rc, env = self.run_check("all", base, head)
        self.assertEqual((rc, env["checks"]["R1"]["status"], [e["check"] for e in env["entries"]]), (1, "fail", ["R1"]))

    def test_without_run_red_stays_n_a_naming_the_missing_table(self):
        base, head = self.mini_pr(MINI_R2)
        rc, env = self.run_check("red", base, head)
        note = "stack `mini` is the repo's adapter file, which has no [run] table: {} runs through [run] (#18)"
        self.assertEqual((rc, {c: env["checks"][c] for c in ("R1", "R4")}),
                         (0, {"R1": {"status": "n/a", "note": note.format("R1")},
                              "R4": {"status": "n/a", "note": note.format("R4")}}))
        self.assertEqual(self.calls(), [])

    def test_r3_on_a_repo_stack_with_run_is_still_n_a(self):
        base, head = self.mini_pr(MINI_R2 + MINI_RUN)
        rc, env = self.run_check("mutants", base, head)
        self.assertEqual((rc, env["checks"]["R3"]), (0, {
            "status": "n/a", "note": "stack `mini` is the repo's adapter file: R3 through an adapter file is not built "
                                     "yet (#19)"}))


class OverrideWithRun(Fixture):
    """a repo file named like a built-in (.ekit/adapters/ts.toml): with [run] it drives R1 and R4 too."""

    def ts_pr(self, adapter_text, outcomes):
        base = self.commit({".gitignore": "node_modules/\n", "src/calc.ts": SRC, "tests/calc.test.ts": TEST,
                            "package.json": '{"name":"calc","devDependencies":{"vitest":"1.0.0"}}\n',
                            ".ekit/adapters/ts.toml": adapter_text})
        head = self.commit({"tests/calc.test.ts": TEST_FRESH, "tests/outcomes": outcomes,
                            "src/calc.ts": SRC.replace("a + b;", "a + b; // fixed")})
        return base, head

    def test_red_on_an_override_with_run_runs_the_files_runner_words(self):
        # the file's own -t words: the built-in would run `-t ^Calc > fresh$`
        text = read(TS_FILE).replace('test = ["{path}", "-t", "^{name}$"]', 'test = ["{path}", "--testNamePattern", "{name}"]')
        base, head = self.ts_pr(text, "fresh fail pass\n")
        r = self.red(base, head, adapter=None)
        env = json.loads(r.stdout)
        self.assertEqual(r.returncode, 1, r.stderr)  # the stub reads -t only: every run is the default pass
        self.assertEqual(set(c.split(" | ", 1)[1] for c in self.calls()),
                         {"run tests/calc.test.ts --testNamePattern Calc > fresh"})
        self.assertEqual(env["checks"]["R1"]["status"], "fail")

    def test_all_on_an_override_with_run_runs_one_adapter(self):
        base, head = self.ts_pr(read(TS_FILE), "fresh fail pass\n")
        r = self.red(base, head, adapter=None, check="all")
        env = json.loads(r.stdout)
        self.assertEqual((r.returncode, {c: v["status"] for c, v in env["checks"].items()}),
                         (0, {"R0": "skipped", "R1": "pass", "R2": "pass", "R3": "skipped", "R4": "pass"}), r.stderr)
        self.assertEqual(env["notes"], ['adapter file declares no build command (commands.build = "")'])


if __name__ == "__main__":
    unittest.main()
