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
        self.assertEqual(e["hint"], "change one of `CHANGELOG.md`, `docs/*.md` in this range as the rule asks (it came "
                                    "from #83); a rule that misfires is changed in a PR of its own")
        self.assertEqual(e["forbidden"], "editing the co-change rule file to silence the rule that fires")
        self.assertEqual(e["id"], "R2-3ec3a5e8")  # the rule id's, as finalize derives it: what a waiver names
        self.assertEqual(env["summary"], f"pass {env['head']} (0 fail, 1 confirm; ran: R2; skipped: R1 R3 R4)")
        self.assertEqual(env["checks"]["R2"], {"status": "pass", "note": "0 fail, 1 confirm"})

    def test_a_required_path_changed_too_gives_no_entry(self):
        for req in ({"CHANGELOG.md": "# log\n- a\n"}, {"docs/new.md": "x\n"}):
            with self.subTest(req=req):
                self.tearDown()
                self.setUp()
                r, env = self.run_r2({"src/a.py": "X = 3\n", **req})
                self.assertEqual((r.returncode, env["entries"]), (0, []), r.stderr)
                self.assertEqual(env["summary"], f"pass {env['head']} (0 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)")

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
        self.assertEqual(env["summary"], f"fail {env['head']} (1 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)")
        self.assertEqual(env["checks"]["R2"]["status"], "fail")

    def test_one_entry_per_broken_rule_with_an_id_that_stays_across_heads(self):
        # the second rule is listed first: a rule that does not fire leaves the next one checked
        two = ('format = 1\n\n[[rule]]\nid = "read-me_b.1"\ntrigger = ["src/b.py"]\nrequire = ["README.md"]\n'
               'reason = "b is documented"\nincident = "abc1234"\n' + RULES.replace("format = 1\n", ""))
        base = self.base(two)
        h1 = self.repo.commit({"src/a.py": "X = 2\n"}, "one")
        first = json.loads(r2(self.repo, base, h1).stdout)["entries"]
        h2 = self.repo.commit({"src/b.py": "Y = 2\n"}, "two")
        second = json.loads(r2(self.repo, base, h2).stdout)["entries"]
        self.assertEqual([e["problem"].split(":")[0] for e in first], ["co-change rule `changelog`"])
        self.assertEqual(sorted(e["problem"].split(":")[0] for e in second),
                         ["co-change rule `changelog`", "co-change rule `read-me_b.1`"])
        self.assertIn(first[0]["id"], [e["id"] for e in second])
        self.assertEqual(len({e["id"] for e in second}), 2)
        self.assertIn("abc1234", [e for e in second if "read-me" in e["problem"]][0]["hint"])

    def test_a_rule_the_pr_adds_does_not_judge_its_own_pr(self):
        valid = RULES.replace('"#83"', '"#7"') + 'flagged = ["src/a.py"]\ncontrol = ["src/a.py", "CHANGELOG.md"]\n'
        self.repo.commit({"README.md": "hi\n"}, "Merge pull request #7 from a/b")
        r, env = self.run_r2({"src/a.py": "X = 2\n", ".ekit/co-change.toml": valid}, rules=None)
        self.assertEqual((r.returncode, env["entries"]), (0, []), r.stderr)

    def test_a_rule_the_pr_removes_still_judges_it(self):
        base = self.base()
        self.repo.git("rm", "-q", ".ekit/co-change.toml")
        head = self.repo.commit({"src/a.py": "X = 2\n"}, "drop the rule")
        got = json.loads(r2(self.repo, base, head).stdout)["entries"]
        self.assertEqual(sorted(e["problem"].split(":")[0] for e in got),  # and the removal is guarded (#85)
                         ["co-change rule `changelog`", "co-change rule `changelog` fires in this range, and this range "
                                                        "removes it"])

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
        self.assertEqual(env["summary"], f"pass {env['head']} (0 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)")

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
            ("format = 1\n[[rule]]\n" + RULE + 'flagged = "src/a.py"\n',
             "rule[0].flagged: want a list of paths (non-empty strings), at least one"),
            ("format = 1\n[[rule]]\n" + RULE + 'control = ["a", ""]\n', "rule[0].control[1]: want a path, a non-empty string"),
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
        self.assertRegex(r.stderr, r"^mech-review: co-change rule file \.ekit/co-change\.toml at [0-9a-f]{12}: not a "
                                   r"file\n$")



def rule(rid="x", flagged=("src/a.py",), control=("src/a.py", "CHANGELOG.md"), incident="#7", extra=""):
    """one [[rule]] table: trigger src/**, require CHANGELOG.md; a case of None is left out."""
    out = (f'\n[[rule]]\nid = "{rid}"\ntrigger = ["src/**"]\nrequire = ["CHANGELOG.md"]\nreason = "why"\n'
           f'incident = "{incident}"\n')
    for key, paths in (("flagged", flagged), ("control", control)):
        if paths is not None:
            out += f"{key} = [" + ", ".join(f'"{x}"' for x in paths) + "]\n"
    return out + extra


def rules(*tables):
    return "format = 1\n" + "".join(tables)


class Proof(unittest.TestCase):
    """R0's static half runs each rule's two cases (#85): the rules at the head, each case a PR in a throwaway repo.
    A rule missing a case, or whose case reads wrong, fails R0 and is named; it blocks nothing."""

    def r0(self, head_rules, base_rules=None, check="r0", extra=()):
        """r0 (or check) on a fresh repo: base_rules on base, head_rules (None: no commit) on head."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(tmp.name)
        files = {"src/a.py": "X = 1\n", "CHANGELOG.md": "# log\n"}
        if base_rules is not None:
            files[".ekit/co-change.toml"] = base_rules
        base = self.repo.commit(files, "base")
        head = self.repo.commit({".ekit/co-change.toml": head_rules}, "head") if head_rules is not None else base
        r = _kit.run_cli([check, "--repo", self.repo.path, "--base", base, "--head", head, "--stack", "python",
                          "--test-paths", "tests/**", *extra])
        return r, (json.loads(r.stdout) if r.stdout else None)

    def test_both_cases_reading_right_prove_the_rule(self):
        r, env = self.r0(rules(rule("x"), rule("y", flagged=["src/deep/b.py", "README.md"])))
        self.assertEqual(r.returncode, 0, r.stderr)
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual([(x["case"], x["status"]) for x in c["co-change"]],
                         [("x:flagged", "pass"), ("x:control", "pass"), ("y:flagged", "pass"), ("y:control", "pass")])
        self.assertEqual(c["note"].split("; co-change rules: ")[1], "2 of 2 proved")
        self.assertEqual(env["entries"], [])

    def test_a_rule_missing_a_case_or_whose_case_reads_wrong_fails_r0_and_is_named(self):
        r, env = self.r0(rules(rule("ok"), rule("no-control", control=None), rule("none", flagged=None, control=None),
                               rule("blind", flagged=["README.md"]), rule("noisy", control=["src/a.py"]),
                               rule("bad-path", flagged=["src/../a.py"])))
        self.assertEqual(r.returncode, 1, r.stderr)
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "fail")
        self.assertNotIn("blocks", c)  # a rule's proof is not the adapter's: R1, R2 and R4 still read
        self.assertEqual(c["note"].split("; co-change rules: ")[1],
                         "1 of 6 proved; failed: no-control none blind noisy bad-path")
        got = {e["problem"].split("`")[1]: e for e in env["entries"]}
        self.assertEqual(sorted(got), ["bad-path", "blind", "no-control", "noisy", "none"])
        for e in got.values():
            self.assertEqual((e["check"], e["class"], e["severity"], e["file"], e["line"]),
                             ("R0", "agent-fixable", "fail", ".ekit/co-change.toml", 0))
        self.assertEqual(got["no-control"]["problem"], "co-change rule `no-control` fails its proof: no `control` case")
        self.assertEqual(got["none"]["problem"],
                         "co-change rule `none` fails its proof: no `flagged` case; no `control` case")
        self.assertEqual(got["blind"]["problem"],
                         "co-change rule `blind` fails its proof: `flagged` case (`README.md`) gave no entry (want "
                         "the rule's entry)")
        self.assertEqual(got["noisy"]["problem"],
                         "co-change rule `noisy` fails its proof: `control` case (`src/a.py`) gave the rule's entry "
                         "(want none)")
        self.assertEqual(got["bad-path"]["problem"],
                         "co-change rule `bad-path` fails its proof: `flagged` case (`src/../a.py`) builds a PR that "
                         "changes no path (want each path as given: a repo path, no `.` or `..` segment)")
        self.assertEqual(got["none"]["hint"],
                         "give the rule a `flagged` case (the paths of a PR it must flag) and a `control` case (the "
                         "paths of a PR it must leave alone), and fix the rule or the case that reads wrong")
        self.assertEqual(got["none"]["forbidden"], "rewriting a case to match what the rule does, not what it is for")
        self.assertEqual([x["status"] for x in env["checks"]["R0"]["co-change"] if x["case"].startswith("ok:")],
                         ["pass", "pass"])

    def test_a_path_that_is_a_folder_of_another_does_not_build_as_given(self):
        r, env = self.r0(rules(rule("x", flagged=["src/a.py", "src/a.py/b.py"])))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("`flagged` case (`src/a.py`, `src/a.py/b.py`) builds a PR that changes ", env["entries"][0]["problem"])

    def test_the_rules_at_the_head_are_proved_not_the_base(self):
        r, env = self.r0(rules(rule("x")), base_rules=rules(rule("x", control=None)))
        self.assertEqual((r.returncode, env["entries"], env["checks"]["R0"]["status"]), (0, [], "pass"), r.stderr)
        r, env = self.r0(rules(rule("x", control=None)), base_rules=rules(rule("x")))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual([e["problem"] for e in env["entries"] if e["check"] == "R0"],
                         ["co-change rule `x` fails its proof: no `control` case"])

    def test_a_head_rule_file_that_does_not_read_leaves_the_rules_unproven(self):
        r, env = self.r0(rules(rule()).replace('id = "x"', "id = 3"))
        self.assertEqual((r.returncode, env["entries"]), (0, []), r.stderr)
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "unproven")
        self.assertRegex(c["note"], r"; co-change rules unproven: co-change rule file \.ekit/co-change\.toml at "
                                    r"[0-9a-f]{12}: rule\[0\]\.id: want a non-empty string$")
        self.assertIn("unproven: R0", env["summary"])

    def test_proved_rules_never_lift_an_unproven_adapter(self):
        with tempfile.TemporaryDirectory() as empty:
            r, env = self.r0(rules(rule()), extra=("--fixtures", empty))
        c = env["checks"]["R0"]
        self.assertEqual((r.returncode, c["status"]), (0, "unproven"), r.stderr)
        self.assertEqual(c["note"].split("; co-change rules: ")[1], "1 of 1 proved")

    def test_no_rule_file_or_no_rules_leaves_r0_as_before(self):
        for head in (None, "format = 1\n"):
            with self.subTest(head=head):
                r, env = self.r0(head)
                c = env["checks"]["R0"]
                self.assertEqual((r.returncode, c["status"], env["entries"]), (0, "pass", []), r.stderr)
                self.assertNotIn("co-change", c)
                self.assertNotIn("co-change", c["note"])

    def test_all_proves_the_rules_and_a_failed_proof_blocks_no_check(self):
        r, env = self.r0(rules(rule("x", control=None)), check="all")
        self.assertEqual([e["problem"] for e in env["entries"] if e["check"] == "R0"],
                         ["co-change rule `x` fails its proof: no `control` case"])
        self.assertEqual(env["checks"]["R0"]["status"], "fail")
        self.assertEqual(env["checks"]["R2"]["status"], "fail")  # its own guard: a new rule without both cases
        self.assertNotIn("blocked", json.dumps(env["entries"]))

    def test_a_failed_proof_leaves_r2_its_own_status(self):
        r, env = self.r0(None, base_rules=rules(rule("x", control=None)), check="all")
        self.assertEqual(env["checks"]["R0"]["status"], "fail")
        self.assertEqual(env["checks"]["R2"], {"status": "pass", "note": "0 fail, 0 confirm"})


class Guards(unittest.TestCase):
    """R2's guards on a change to the rule file (#85): the head's file reads; a new rule's incident resolves to a
    commit or PR, and it has both cases; a rule that fires in the range is not weakened or removed in it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(self.tmp.name)
        self.repo.commit({"src/a.py": "X = 1\n", "CHANGELOG.md": "# log\n", "README.md": "hi\n"}, "seed (#70, #123, #0)")
        self.seed = self.repo.commit({"src/b.py": "Y = 1\n"}, "Merge pull request #7 from someone/branch")

    def tearDown(self):
        self.tmp.cleanup()

    def r2(self, head_files, base_rules=None):
        """R2 over base (base_rules on it, if any) .. head (head_files): its entries other than a rule firing."""
        base = self.repo.commit({".ekit/co-change.toml": base_rules}, "rules") if base_rules else self.seed
        head = self.repo.commit(head_files, "head")
        r = r2(self.repo, base, head)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        env = json.loads(r.stdout)
        return r, [e for e in env["entries"] if "fires" in e["problem"] or not e["problem"].startswith("co-change rule")]

    def test_a_new_rule_whose_incident_resolves_to_no_commit_or_pr_is_a_fail(self):
        tree = self.repo.git("rev-parse", "HEAD^{tree}").strip()
        side = self.repo.git("commit-tree", "-m", "Merge pull request #9 from a/b", tree).strip()
        self.repo.git("update-ref", "refs/heads/elsewhere", side)  # a branch the head does not reach
        bad = ["#8", "#0", "#9", "#12", side[:10], "the doc PR", "#7 and more"]
        _, got = self.r2({".ekit/co-change.toml": rules(*(rule(f"r{i}", incident=x) for i, x in enumerate(bad)))})
        self.assertEqual(sorted(e["problem"] for e in got),
                         [f"new co-change rule `r{i}`: incident `{x}` resolves to no commit or PR (want a commit the "
                          f"head reaches, or `#N` that the message of a commit the head reaches names)"
                          for i, x in enumerate(bad)])
        self.assertEqual({(e["check"], e["class"], e["severity"], e["file"]) for e in got},
                         {("R2", "agent-fixable", "fail", ".ekit/co-change.toml")})
        self.assertEqual(got[0]["hint"], "name the commit (its sha) or the PR (`#N`) of the mistake the rule came "
                                         "from, one the history of this branch holds")

    def test_a_new_rule_whose_incident_resolves_gives_no_entry(self):
        good = ["#7", "#70", self.seed, self.seed[:7].upper()]
        r, got = self.r2({".ekit/co-change.toml": rules(*(rule(f"r{i}", incident=x) for i, x in enumerate(good)))})
        self.assertEqual((r.returncode, got), (0, []))

    def test_a_new_rule_without_both_cases_is_a_fail(self):
        _, got = self.r2({".ekit/co-change.toml": rules(rule("a", control=None), rule("b", flagged=None),
                                                        rule("c", flagged=None, control=None), rule("d"))})
        self.assertEqual(sorted(e["problem"] for e in got),
                         ["new co-change rule `a` has no `control` case", "new co-change rule `b` has no `flagged` case",
                          "new co-change rule `c` has no `flagged` case and no `control` case"])
        self.assertEqual({(e["class"], e["severity"]) for e in got}, {("agent-fixable", "fail")})
        self.assertEqual(got[0]["hint"], "add the case: the paths of a PR the rule must flag (`flagged`) or must leave "
                                         "alone (`control`); R0 runs both")

    def test_a_rule_already_on_the_merge_base_is_not_new(self):
        _, got = self.r2({".ekit/co-change.toml": rules(rule("x", control=None, incident="nothing"), rule("d"))},
                         base_rules=rules(rule("x", control=None, incident="nothing")))
        self.assertEqual(got, [])

    WAS = rule("x", extra='severity = "fail"\n').replace('trigger = ["src/**"]', 'trigger = ["src/**", "lib/**"]')
    OTHER = rule("other", flagged=["other/a"], control=["other/a", "CHANGELOG.md"]).replace('"src/**"', '"other/**"')

    def weakened(self, head_rules, changed):
        files = {"src/a.py": "X = 2\n"} if changed else {"README.md": "hello\n"}
        base = self.repo.commit({".ekit/co-change.toml": rules(self.WAS, self.OTHER)}, "rules")
        if head_rules is None:
            self.repo.git("rm", "-q", ".ekit/co-change.toml")
        else:
            files[".ekit/co-change.toml"] = head_rules
        head = self.repo.commit(files, "head")
        r = r2(self.repo, base, head)
        return r, [e for e in json.loads(r.stdout)["entries"] if e["class"] == "needs-human"]

    CHANGES = {
        "severity": (rules(WAS.replace('"fail"', '"confirm"'), OTHER), "weakens it (severity fail -> confirm)"),
        "trigger": (rules(WAS.replace('"src/**", "lib/**"', '"src/**"'), OTHER),
                    "weakens it (trigger loses `lib/**`)"),
        "require": (rules(WAS.replace('["CHANGELOG.md"]', '["CHANGELOG.md", "docs/**", ".ekit/**"]'), OTHER),
                    "weakens it (require gains `docs/**`, `.ekit/**`)"),
        "all three": (rules(rule("x", extra='severity = "confirm"\n').replace('["CHANGELOG.md"]', '["README.md"]'),
                            OTHER),
                      "weakens it (severity fail -> confirm; trigger loses `lib/**`; require gains `README.md`)"),
        "removed": (rules(OTHER), "removes it"),
        "renamed": (rules(WAS.replace('id = "x"', 'id = "x2"'), OTHER), "removes it"),
        "file deleted": (None, "removes it"),
    }

    def test_a_rule_that_fires_and_is_weakened_or_removed_in_the_range_is_a_needs_human_fail(self):
        for name, (head_rules, why) in self.CHANGES.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                r, got = self.weakened(head_rules, changed=True)
                self.assertEqual(r.returncode, 1)
                self.assertEqual([(e["problem"], e["severity"], e["file"]) for e in got],
                                 [(f"co-change rule `x` fires in this range, and this range {why}", "fail",
                                   ".ekit/co-change.toml")])
                self.assertEqual(got[0]["hint"], "a person decides: keep the rule as the merge base has it in this PR, "
                                                 "and weaken or remove it in a PR of its own")
                self.assertEqual(got[0]["forbidden"], "editing the co-change rule file to silence the rule that fires")

    def test_the_same_weakening_or_removal_where_the_rule_does_not_fire_gives_no_entry(self):
        for name, (head_rules, _) in self.CHANGES.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                r, got = self.weakened(head_rules, changed=False)
                self.assertEqual((r.returncode, got), (0, []))

    def test_adding_a_rule_promoting_one_and_widening_one_that_fires_give_no_entry(self):
        head = rules(rule("x", extra='severity = "fail"\n').replace('["src/**"]', '["src/**", "lib/**"]'),
                     rule("y", incident="#70"), rule("new", incident="#7"))
        r, got = self.r2({"src/a.py": "X = 2\n", ".ekit/co-change.toml": head}, base_rules=rules(rule("x"), rule("y")))
        self.assertEqual(got, [])

    def test_a_head_rule_file_that_does_not_read_is_a_fail_entry_not_a_usage_error(self):
        r, got = self.r2({".ekit/co-change.toml": rules(rule()).replace('id = "x"', "id = 3")})
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(len(got), 1, got)
        self.assertRegex(got[0]["problem"], r"^the co-change rule file this range writes does not read: co-change rule "
                                            r"file \.ekit/co-change\.toml at [0-9a-f]{12}: rule\[0\]\.id: want a "
                                            r"non-empty string$")
        self.assertEqual((got[0]["class"], got[0]["severity"], got[0]["file"]),
                         ("agent-fixable", "fail", ".ekit/co-change.toml"))
        self.assertEqual(got[0]["hint"], "fix the field it names; the rule file is read at the base for every PR after "
                                         "this one")

    def test_a_rule_file_the_range_leaves_alone_is_not_read_at_the_head(self):
        mb = self.repo.commit({".ekit/co-change.toml": "not toml ["}, "a broken rule file")
        self.repo.git("checkout", "-q", "-b", "pr")
        head = self.repo.commit({"src/a.py": "X = 2\n"}, "pr")
        self.repo.git("checkout", "-q", "main")
        self.repo.git("rm", "-q", ".ekit/co-change.toml")
        base = self.repo.commit({}, "main drops it")
        r = r2(self.repo, base, head)
        self.assertEqual((r.returncode, json.loads(r.stdout)["entries"]), (0, []), r.stderr)
        self.assertNotEqual(mb, base)

    def test_the_rules_the_base_tip_adds_after_the_merge_base_are_not_removed_by_the_pr(self):
        self.repo.git("checkout", "-q", "-b", "pr")
        head = self.repo.commit({"src/a.py": "X = 2\n", ".ekit/co-change.toml": rules(rule("y", incident="#7"))}, "pr")
        self.repo.git("checkout", "-q", "main")
        base = self.repo.commit({".ekit/co-change.toml": rules(rule("x"), rule("y", incident="#7"))}, "rules on main")
        env = json.loads(r2(self.repo, base, head).stdout)
        self.assertEqual(sorted(e["problem"].split(",")[0] for e in env["entries"]),
                         ["co-change rule `x`: `src/a.py` changed", "co-change rule `y`: `src/a.py` changed"])

if __name__ == "__main__":
    unittest.main()
