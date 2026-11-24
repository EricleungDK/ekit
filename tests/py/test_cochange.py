"""Co-change rules (#83): `.ekit/co-change.toml` at the base says "when these paths change, one of those must change too";
R2's path rules give one entry per broken rule. Through `cli.main(["r2", ...])` on fixture repos (python stack)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import _kit
from test_adapter_cli import Repo

RULES = '''format = 1

[[rule]]
id = "changelog"
trigger = ["src/**"]
require = ["CHANGELOG.md", "docs/*.md"]
reason = "a behaviour change updates the changelog or the docs"
incident = "#83"
'''


def r2(repo, base, head, check="r2"):
    return _kit.run_cli([check, "--repo", repo.path, "--base", base, "--head", head, "--stack", "python",
                         "--test-paths", "tests/**"])


class CoChange(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def base(self, rules=RULES):
        files = {"src/a.py": "X = 1\n", "src/b.py": "Y = 1\n", "CHANGELOG.md": "# log\n", "README.md": "hi\n"}
        if rules is not None:
            files[".ekit/co-change.toml"] = rules
        return self.repo.commit(files, "base")

    def run_r2(self, head_files, rules=RULES, check="r2"):
        base = self.base(rules)
        head = self.repo.commit(head_files, "head")
        r = r2(self.repo, base, head, check)
        return r, (json.loads(r.stdout) if r.stdout else None)

    def test_a_trigger_changed_and_no_required_path_is_one_confirm_entry_naming_both_and_the_reason(self):
        r, env = self.run_r2({"src/a.py": "X = 2\n", "src/b.py": "Y = 2\n"})
        self.assertEqual(r.returncode, 0, r.stderr)
        got = [e for e in env["entries"] if e["check"] == "R2"]
        self.assertEqual(len(got), 1, got)
        e = got[0]
        self.assertEqual((e["class"], e["severity"], e["file"], e["line"]),
                         ("agent-fixable", "confirm", ".ekit/co-change.toml", 0))
        self.assertEqual(e["problem"], "co-change rule `changelog`: `src/a.py` and 1 more changed, and none of "
                                       "`CHANGELOG.md`, `docs/*.md` did: a behaviour change updates the changelog or "
                                       "the docs")
        self.assertIn("`CHANGELOG.md`, `docs/*.md`", e["hint"])
        self.assertTrue(env["summary"].startswith("pass "), env["summary"])
        self.assertEqual(env["checks"]["R2"], {"status": "pass", "note": "0 fail, 1 confirm"})

    def test_a_required_path_changed_too_gives_no_entry(self):
        for req in ({"CHANGELOG.md": "# log\n- a\n"}, {"docs/new.md": "x\n"}):
            with self.subTest(req=req):
                self.tearDown()
                self.setUp()
                r, env = self.run_r2({"src/a.py": "X = 3\n", **req})
                self.assertEqual((r.returncode, env["entries"]), (0, []), r.stderr)
                self.assertTrue(env["summary"].startswith("pass "), env["summary"])

    def test_no_triggering_path_changed_gives_no_entry(self):
        r, env = self.run_r2({"README.md": "hello\n"})
        self.assertEqual((r.returncode, env["entries"]), (0, []), r.stderr)

    def test_a_trigger_path_renamed_away_still_triggers(self):
        base = self.base()
        self.repo.git("mv", "src/a.py", "lib_a.py")
        self.repo.git("commit", "-q", "-m", "move")
        r = r2(self.repo, base, "HEAD")
        got = json.loads(r.stdout)["entries"]
        self.assertEqual([e["problem"].split(":")[0] for e in got], ["co-change rule `changelog`"])
        self.assertIn("`src/a.py` changed,", got[0]["problem"])

    def test_a_rule_at_fail_fails_the_summary(self):
        r, env = self.run_r2({"src/a.py": "X = 2\n"}, rules=RULES + 'severity = "fail"\n')
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual([(e["severity"], e["class"]) for e in env["entries"]], [("fail", "agent-fixable")])
        self.assertIn("`src/a.py` changed, and none", env["entries"][0]["problem"])
        self.assertTrue(env["summary"].startswith("fail "), env["summary"])
        self.assertEqual(env["checks"]["R2"]["status"], "fail")

    def test_one_entry_per_broken_rule_with_an_id_that_stays_across_heads(self):
        two = RULES + ('\n[[rule]]\nid = "readme"\ntrigger = ["src/b.py"]\nrequire = ["README.md"]\n'
                       'reason = "b is documented"\nincident = "abc1234"\n')
        base = self.base(two)
        h1 = self.repo.commit({"src/a.py": "X = 2\n"}, "one")
        first = json.loads(r2(self.repo, base, h1).stdout)["entries"]
        h2 = self.repo.commit({"src/b.py": "Y = 2\n"}, "two")
        second = json.loads(r2(self.repo, base, h2).stdout)["entries"]
        self.assertEqual([e["problem"].split(":")[0] for e in first], ["co-change rule `changelog`"])
        self.assertEqual(sorted(e["problem"].split(":")[0] for e in second),
                         ["co-change rule `changelog`", "co-change rule `readme`"])
        self.assertIn(first[0]["id"], [e["id"] for e in second])
        self.assertEqual(len({e["id"] for e in second}), 2)
        self.assertIn("abc1234", [e for e in second if "readme" in e["problem"]][0]["hint"])

    def test_a_rule_the_pr_adds_does_not_judge_its_own_pr(self):
        r, env = self.run_r2({"src/a.py": "X = 2\n", ".ekit/co-change.toml": RULES}, rules=None)
        self.assertEqual((r.returncode, env["entries"]), (0, []), r.stderr)

    def test_a_rule_the_pr_removes_still_judges_it(self):
        base = self.base()
        self.repo.git("rm", "-q", ".ekit/co-change.toml")
        head = self.repo.commit({"src/a.py": "X = 2\n"}, "drop the rule")
        got = json.loads(r2(self.repo, base, head).stdout)["entries"]
        self.assertEqual([e["file"] for e in got], [".ekit/co-change.toml"])

    def test_the_rules_are_read_at_the_base_tip_not_the_merge_base(self):
        self.base(rules=None)
        self.repo.git("checkout", "-q", "-b", "pr")
        head = self.repo.commit({"src/a.py": "X = 2\n"}, "pr")
        self.repo.git("checkout", "-q", "main")
        base = self.repo.commit({".ekit/co-change.toml": RULES}, "rules on main")
        got = json.loads(r2(self.repo, base, head).stdout)["entries"]
        self.assertEqual([e["file"] for e in got], [".ekit/co-change.toml"])

    def test_all_runs_the_rules_too(self):
        r, env = self.run_r2({"src/a.py": "X = 2\n"}, check="all")
        self.assertIn("co-change rule `changelog`", [e["problem"].split(":")[0] for e in env["entries"]], r.stderr)

    def test_a_repo_without_a_rule_file_reads_no_toml(self):
        with mock.patch.dict(sys.modules, {"tomllib": None}):
            r, env = self.run_r2({"src/a.py": "X = 2\n"}, rules=None)
        self.assertEqual((r.returncode, env["entries"], r.stderr), (0, [], ""))
        self.assertTrue(env["summary"].startswith("pass "), env["summary"])

    def test_a_rule_file_on_a_python_without_tomllib_is_a_clean_error(self):
        with mock.patch.dict(sys.modules, {"tomllib": None}):
            r, _ = self.run_r2({"src/a.py": "X = 2\n"})
        self.assertEqual(r.returncode, 2)
        self.assertRegex(r.stderr, r"^mech-review: co-change rule file \.ekit/co-change\.toml at [0-9a-f]{12}: reading "
                                   r"the co-change rule file needs python 3\.11 or newer \(tomllib\)\n$")


RULE = 'id = "x"\ntrigger = ["src/**"]\nrequire = ["CHANGELOG.md"]\nreason = "why"\nincident = "#1"\n'


class MalformedRuleFile(unittest.TestCase):
    """a rule file that does not read is a usage error (exit 2) naming the field, as for an adapter file: no result,
    no traceback, never read as no rules."""

    def error(self, raw):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Repo(tmp)
            repo.commit({"src/a.py": "X = 1\n"}, "seed")
            os.makedirs(os.path.join(tmp, ".ekit"))
            with open(os.path.join(tmp, ".ekit", "co-change.toml"), "wb") as f:
                f.write(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
            base = repo.commit({}, "rules")
            head = repo.commit({"src/a.py": "X = 2\n"}, "head")
            r = r2(repo, base, head)
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        prefix = "mech-review: co-change rule file .ekit/co-change.toml at "
        self.assertTrue(r.stderr.startswith(prefix), r.stderr)
        self.assertEqual(r.stderr.count("\n"), 1, r.stderr)
        return r.stderr[len(prefix) + 14:].rstrip("\n")

    def test_each_problem_names_its_field(self):
        cases = [
            ("format = 1\n[[rule]]\n" + RULE + 'triggers = ["a"]\n', "rule[0].triggers: unknown key"),
            ("format = 1\nrules = []\n", "rules: unknown key"),
            ("format = 1\n[[rule]]\n" + RULE.replace('reason = "why"\n', ""), "rule[0].reason: missing"),
            ("format = 1\n[[rule]]\n" + RULE.replace('incident = "#1"\n', ""), "rule[0].incident: missing"),
            ("[[rule]]\n" + RULE, "format: missing"),
            ("format = 2\n", "format: `2`: want 1"),
            ('format = "1"\n', "format: `1`: want 1"),
            ("format = true\n", "format: `True`: want 1"),
            ("format = 1\n[[rule]]\n" + RULE.replace('["src/**"]', '["src/**", 3]'),
             "rule[0].trigger[1]: want a glob, a non-empty string"),
            ("format = 1\n[[rule]]\n" + RULE.replace('["CHANGELOG.md"]', '[""]'),
             "rule[0].require[0]: want a glob, a non-empty string"),
            ("format = 1\n[[rule]]\n" + RULE.replace('["src/**"]', '"src/**"'),
             "rule[0].trigger: want a list of globs (non-empty strings), at least one"),
            ("format = 1\n[[rule]]\n" + RULE.replace('["CHANGELOG.md"]', "[]"),
             "rule[0].require: want a list of globs (non-empty strings), at least one"),
            ("format = 1\n[[rule]]\n" + RULE + "\n[[rule]]\n" + RULE, "rule[1].id: `x` is already rule[0].id"),
            ("format = 1\n[[rule]]\n" + RULE.replace('"x"', '"a b"'),
             "rule[0].id: `a b`: want letters, digits, _, - or ."),
            ("format = 1\n[[rule]]\n" + RULE.replace('"x"', "7"), "rule[0].id: want a non-empty string"),
            ("format = 1\n[[rule]]\n" + RULE.replace('"why"', '" "'), "rule[0].reason: want a non-empty string"),
            ("format = 1\n[[rule]]\n" + RULE.replace('"#1"', '""'), "rule[0].incident: want a non-empty string"),
            ("format = 1\n[[rule]]\n" + RULE + 'severity = "block"\n',
             "rule[0].severity: `block`: want confirm or fail"),
            ("format = 1\nrule = 1\n", "rule: want an array of tables ([[rule]])"),
            ("format = 1\nrule = [1]\n", "rule: want an array of tables ([[rule]])"),
        ]
        for text, want in cases:
            with self.subTest(want=want):
                self.assertEqual(self.error(text), want)

    def test_not_toml_not_utf8_and_too_deep_are_named(self):
        self.assertTrue(self.error("format = \n").startswith("not valid TOML: "))
        self.assertEqual(self.error(b"format = 1\n# \xff\n"),
                         "not valid TOML: not UTF-8 (invalid start byte at byte 13)")
        self.assertEqual(self.error("x = " + "[" * 5000 + "]" * 5000 + "\n"),
                         "not valid TOML: arrays or tables nested too deep")

    def test_a_bom_and_an_empty_rule_list_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Repo(tmp)
            base = repo.commit({".ekit/co-change.toml": "﻿format = 1\n"}, "base")
            head = repo.commit({"src/a.py": "X = 2\n"}, "head")
            r = r2(repo, base, head)
        self.assertEqual((r.returncode, json.loads(r.stdout)["entries"]), (0, []), r.stderr)

    def test_a_directory_at_the_rule_path_is_not_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Repo(tmp)
            base = repo.commit({".ekit/co-change.toml/x": "y\n"}, "base")
            head = repo.commit({"src/a.py": "X = 2\n"}, "head")
            r = r2(repo, base, head)
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.rstrip().endswith(": not a file"), r.stderr)


if __name__ == "__main__":
    unittest.main()
