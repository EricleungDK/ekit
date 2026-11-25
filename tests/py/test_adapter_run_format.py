"""The run side of an adapter file (#18): [commands] and [run] are validated at load, so a bad one is an AdapterFileError
naming the field, never a crash in R1 or R4. Pure: adapter_file.parse on the dicts tomllib reads, and loads on bytes."""
import copy
import os
import shutil
import tempfile
import unittest

import _kit
from scripts.mech_review.adapter_file import AdapterFileError, loads, parse

R2_ONLY = {
    "format": 1,
    "name": "mini",
    "extensions": [".mini"],
    "lexer": {"block_style": "braces", "brackets": ["()", "{}"], "line_comments": ["#"]},
    "tests": {"style": "calls", "groups": ["suite"], "cases": ["test"]},
    "asserts": {"call": [{"names": ["assertEquals"], "kind": "eq", "operands": [0, 1]}]},
}
COMMANDS = {"install": "mini fetch", "build": "", "lint": "mini lint", "test": "minitest"}
RUN = {"test": ["--only", "{name}"], "outcome": {"passed": r"(\d+) passed", "failed": r"(\d+) failed"}}
GOOD = dict(copy.deepcopy(R2_ONLY), commands=COMMANDS, run=RUN)
DEL = object()


def with_(path, value):
    """GOOD with the dotted path set to value (DEL: the key removed); list indexes are numbers."""
    d = copy.deepcopy(GOOD)
    *parents, last = path.split(".")
    cur = d
    for p in parents:
        cur = cur[int(p)] if isinstance(cur, list) else cur.setdefault(p, {})
    if value is DEL:
        del cur[last]
    elif isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value
    return d


class RunSideFormat(unittest.TestCase):
    def bad(self, data, msg):
        with self.assertRaises(AdapterFileError) as e:
            parse(data)
        self.assertEqual(str(e.exception), msg)

    def test_a_file_with_commands_and_run_reads_its_commands(self):
        a = parse(GOOD)
        self.assertEqual(a.commands, COMMANDS)
        self.assertEqual(a.default_test_cmd, "minitest")
        self.assertEqual(a.test_argv(a.test_cmd_in("/no/such/dir"), "tests/a.mini", "S > t"),
                         ["minitest", "--only", "S > t"])

    def test_a_file_without_run_is_r2_only(self):
        self.assertIsNone(parse(R2_ONLY).run)
        self.assertEqual(parse(dict(copy.deepcopy(R2_ONLY), commands=dict(COMMANDS, test=""))).commands["test"], "")

    def test_a_missing_install_command_is_named(self):
        self.bad(with_("commands.install", DEL),
                 "commands.install: missing: want the command that installs the project's dependencies, or \"\" when "
                 "the stack has none")

    def test_a_missing_build_command_is_named(self):
        self.bad(with_("commands.build", DEL),
                 "commands.build: missing: want the command that builds the project, or \"\" when the stack has none")

    def test_missing_lint_and_test_commands_are_named(self):
        self.bad(with_("commands.lint", DEL),
                 "commands.lint: missing: want the command that lints the project, or \"\" when the stack has none")
        self.bad(with_("commands.test", DEL),
                 "commands.test: missing: want the command that runs the whole test suite, or \"\" when the stack has "
                 "none")

    def test_run_needs_commands_and_a_test_command(self):
        self.bad(with_("commands", DEL),
                 "commands: missing: [run] needs [commands] (install, build, lint, test): R1 and R4 start from its test")
        self.bad(with_("commands.test", " "),
                 "commands.test: want the whole-suite command: [run] starts every R1 and R4 run from it")

    def test_commands_are_strings_and_known_keys(self):
        self.bad(with_("commands.build", ["make"]), "commands.build: want a string")
        self.bad(with_("commands.deploy", "x"), "commands.deploy: unknown key")

    def test_the_one_test_words_must_name_the_test_with_known_plain_placeholders(self):
        self.bad(with_("run.test", ["{path}"]), "run.test: no `{name}`: the words must name the one test to run")
        self.bad(with_("run.test", ["{file}", "{name}"]),
                 "run.test[0]: unknown placeholder `{file}`: want `{path}` or `{name}`")
        self.bad(with_("run.test", ["{name!r}"]), "run.test[0]: `{name!r}`: want plain `{path}` or `{name}` (no `!` "
                                                  "conversion or `:` spec)")
        self.bad(with_("run.test", []), "run.test: want at least one entry")
        self.bad(with_("run.test", DEL), "run.test: missing")

    def test_outcome_patterns_are_compiled_at_load(self):
        self.bad(with_("run.outcome", DEL), "run.outcome: missing")
        self.bad(with_("run.outcome.failed", DEL), "run.outcome.failed: missing")
        self.bad(with_("run.outcome.build", "(oops"),
                 "run.outcome.build: bad regex `(oops`: missing ), unterminated subpattern at position 0")
        self.bad(with_("run.outcome.passed", "passed"),
                 "run.outcome.passed: `passed` has 0 capturing groups: want one capturing group: the count, e.g. "
                 "`(\\d+) passed`")
        self.bad(with_("run.outcome.summary", "(a)(b)"),
                 "run.outcome.summary: `(a)(b)` has 2 capturing groups: want at most one capturing group: the part "
                 "counts are read from")
        self.bad(with_("run.outcome.crashed", "x"), "run.outcome.crashed: unknown key")

    def test_name_quoting_needs_placeholders_and_their_replacement_together(self):
        self.bad(with_("run.name", {"placeholders": "%s"}),
                 "run.name.any: missing: placeholders needs the text they become, e.g. \".*\"")
        self.bad(with_("run.name", {"any": ".*"}), "run.name.placeholders: missing: any is what placeholders become")
        self.bad(with_("run.name", {"placeholders": "(%s)", "any": ".*"}),
                 "run.name.placeholders: `(%s)` has 1 capturing groups: want no capturing group: use (?:...)")

    def test_runners_are_each_reachable_and_named_once(self):
        self.bad(with_("run.runner", [{"name": "a"}, {"name": "b", "match": "b"}]),
                 "run.runner[1]: never picked for a command: run.runner[0] has no match, so it takes every command")
        self.bad(with_("run.runner", [{"name": "a", "match": "a"}, {"name": "a"}]),
                 "run.runner[1].name: `a` is already run.runner[0]")
        self.bad(with_("run.runner", {"name": "a"}), "run.runner: want an array of tables ([[run.runner]])")

    def test_a_runners_when_needs_a_command_and_tables_for_names(self):
        self.bad(with_("run.runner", [{"name": "a", "match": "a", "when": {"file": "a.json"}}]),
                 "run.runner[0].command: missing: when picks this runner's command for the checkout")
        self.bad(with_("run.runner", [{"name": "a", "command": "a", "when": {"file": "a.json", "has": ["x"]}}]),
                 "run.runner[0].when.has: needs tables: the JSON tables the names are looked up in")
        self.bad(with_("run.runner", [{"name": "a", "command": "a", "when": {"file": "../a.json"}}]),
                 "run.runner[0].when.file: `../a.json`: want a path under the project dir (no .., not absolute)")

    def test_links_stay_under_the_project_dir(self):
        self.bad(with_("run.links", ["/opt/node_modules"]),
                 "run.links[0]: `/opt/node_modules`: want a path under the project dir (no .., not absolute)")

    def test_loads_names_the_file_and_the_field(self):
        raw = b'format = 1\nname = "mini"\nextensions = [".mini"]\n[lexer]\nblock_style = "braces"\n' \
              b'brackets = ["()", "{}"]\n[tests]\nstyle = "calls"\ncases = ["test"]\n' \
              b'[[asserts.call]]\nnames = ["eq"]\nkind = "other"\n[commands]\ninstall = ""\nlint = ""\ntest = "t"\n'
        with self.assertRaises(AdapterFileError) as e:
            loads(raw, "x.toml")
        self.assertEqual(str(e.exception), "adapter file x.toml: commands.build: missing: want the command that builds "
                                           "the project, or \"\" when the stack has none")

    def test_a_command_with_unbalanced_quotes_is_named_at_load(self):
        self.bad(with_("commands.test", "vitest 'run"),
                 "commands.test: `vitest 'run`: unbalanced quotes (No closing quotation)")
        self.bad(with_("commands.install", 'npm "ci'),
                 "commands.install: `npm \"ci`: unbalanced quotes (No closing quotation)")
        self.bad(with_("run.runner", [{"name": "j", "match": "j", "command": 'jest "x', "when": {"file": "p.json"}}]),
                 "run.runner[0].command: `jest \"x`: unbalanced quotes (No closing quotation)")

    def test_a_blank_runner_command_is_named_at_load(self):
        self.bad(with_("run.runner", [{"name": "j", "match": "j", "command": "   ", "when": {"file": "p.json"}}]),
                 "run.runner[0].command: want a command, not blank")

    def test_a_runner_command_without_when_is_never_used(self):
        self.bad(with_("run.runner", [{"name": "j", "match": "j", "command": "jest"}]),
                 "run.runner[0].command: never used: a runner's command is picked by its when")

    def test_a_when_file_that_names_a_dir_can_never_hold(self):
        for path in ("./", ".", "a/", "a//b", "a/./b"):
            self.bad(with_("run.runner", [{"name": "j", "match": "j", "command": "jest", "when": {"file": path}}]),
                     f"run.runner[0].when.file: `{path}`: want a file name under the project dir, such as package.json")

    def test_a_pattern_that_matches_empty_text_is_named_at_load(self):
        for key, pat in (("build", "x?"), ("env", "a*"), ("no_test", "^"), ("summary", "(.*)"), ("build", r"\b"),
                         ("passed", r"(\d*)(?: passed)?")):
            self.bad(with_(f"run.outcome.{key}", pat),
                     f"run.outcome.{key}: `{pat}` matches empty text: want a pattern that needs some output to match")
        self.bad(with_("run.name", {"placeholders": "x*", "any": ".*"}),
                 "run.name.placeholders: `x*` matches empty text: want a pattern that needs some output to match")

    def test_a_pattern_whose_empty_match_needs_a_newline_is_named_at_load(self):
        self.bad(with_("run.outcome.build", "(?<=\n)"),
                 "run.outcome.build: `(?<=\n)` matches empty text: want a pattern that needs some output to match")

    def test_a_runners_subcommand_separator_and_when_names_are_checked(self):
        runner = {"name": "v", "match": "v"}
        self.bad(with_("run.runner", [dict(runner, subcommand={"after": "v"})]), "run.runner[0].subcommand.word: missing")
        self.bad(with_("run.runner", [dict(runner, subcommand={"word": "run", "after": ""})]),
                 "run.runner[0].subcommand.after: want a non-empty string")
        self.bad(with_("run.runner", [dict(runner, separator=3)]), "run.runner[0].separator: want a non-empty string")
        for k in ("has", "lacks"):
            self.bad(with_("run.runner", [dict(runner, command="v", when={"file": "p.json", "tables": ["d"], k: "x"})]),
                     f"run.runner[0].when.{k}: want a list of non-empty strings")

    def test_a_path_with_a_backslash_is_not_under_the_project_dir(self):
        self.bad(with_("run.links", ["a\\b"]),
                 "run.links[0]: `a\\b`: want a path under the project dir (no .., not absolute)")

    def test_a_parser_backed_file_takes_the_run_side_too(self):
        # #27's [parser] reads the facts in place of the pattern tables; the run side reads runner output, not source
        data = {"format": 1, "name": "mini", "extensions": [".mini"], "commands": COMMANDS, "run": RUN,
                "parser": {"command": "mini-facts", "installer": "pip", "package": "mini-facts", "version": "1.0.0"}}
        a = parse(copy.deepcopy(data))
        self.assertEqual(a.test_argv(a.test_cmd_in("/no/such/dir"), "tests/a.mini", "S > t"), ["minitest", "--only", "S > t"])
        self.assertEqual((a.outcome(0, "2 passed"), a.outcome(1, "1 failed")), ("pass", "fail"))
        self.assertEqual(a.notes(), ['adapter file declares no build command (commands.build = "")'])
        del data["commands"]
        self.bad(data, "commands: missing: [run] needs [commands] (install, build, lint, test): R1 and R4 start from its test")

    def test_the_shipped_ts_file_has_the_run_side(self):
        with open(os.path.join(_kit.ROOT, "scripts", "mech_review", "adapters", "ts.toml"), "rb") as f:
            a = loads(f.read(), "ts.toml")
        self.assertEqual(a.commands, {"install": "npm ci", "build": "", "lint": "", "test": "node_modules/.bin/vitest run"})


FULL_OUTCOME = {"summary": r"^== (?:.*)$", "passed": r"(\d+) ok", "failed": r"(\d+) bad", "skipped": r"(\d+) skip",
                "build": r"^cannot compile", "no_test": r"^no such test", "env": r"^runtime missing"}


class RunSideBehaviour(unittest.TestCase):
    """the run side of a parsed file, on its own: what one run's output reads as, and the argv and command it builds."""

    def adapter(self, **run):
        return parse(dict(copy.deepcopy(R2_ONLY), commands=COMMANDS, run=dict(copy.deepcopy(RUN), **run)))

    def test_outcome_order_on_a_summary_line_without_a_group(self):
        a = self.adapter(outcome=FULL_OUTCOME)
        for rc, out, want in [
            (None, "minitest: not found", "env"),
            ("timeout", "", "timeout"),
            (0, "runtime missing: erlang", "env"),
            (0, "runtime missing: erlang\n== 1 ok", "pass"),  # #22: a summary was read: the test printed it
            (1, "runtime missing: erlang\n== 0 ok 1 bad", "fail"),
            (1, "== 1 ok 1 bad", "fail"),
            (0, "== 1 ok", "pass"),
            (1, "== 1 ok", "fail"),
            (0, "3 bad\n== 2 ok", "pass"),  # counts come from the last summary line only
            (0, "== 1 bad\n== 1 ok", "pass"),
            (1, "== 1 ok\n== 1 bad", "fail"),
            (1, "cannot compile x\n== 0 ok", "build"),
            (1, "no such test x\n== 0 ok", "none"),
            (1, "== 0 ok 1 skip", "none"),
            (0, "== 0 ok", "none"),
            (1, "== 0 ok", "error"),
            (0, "1 ok but no summary line", "error"),
            (0, "", "error"),
        ]:
            self.assertEqual(a.outcome(rc, out), want, (rc, out))

    def test_without_a_summary_every_count_in_the_output_adds_up(self):
        a = self.adapter()
        self.assertEqual(a.outcome(1, "suite a: 0 passed\nsuite b: 1 failed\n"), "fail")
        self.assertEqual(a.outcome(0, "suite a: 0 passed\nsuite b: 2 passed\n"), "pass")
        self.assertEqual(a.outcome(0, "suite a: 0 passed\n"), "none")
        s = self.adapter(outcome={"passed": r"(\d+) passed", "failed": r"(\d+) failed", "skipped": r"(\d+) skipped",
                                  "env": r"^runtime missing"})
        self.assertEqual(s.outcome(0, "1 skipped\n"), "none")  # a skipped count alone is a count read
        self.assertEqual(s.outcome(0, "runtime missing\n1 skipped\n"), "none")
        self.assertEqual(s.outcome(0, "runtime missing\n"), "env")
        self.assertEqual(a.outcome(1, "suite a: 0 passed\n"), "error")  # no skipped pattern: no skipped count
        self.assertEqual(a.outcome(0, "nothing counted\n"), "error")

    def test_a_summary_group_is_the_text_counts_are_read_from(self):
        a = self.adapter(outcome={"summary": r"^Total:(.*)\(\d+ passed\)$", "passed": r"(\d+) passed",
                                  "failed": r"(\d+) failed"})
        self.assertEqual(a.outcome(0, "Total: 0 passed (3 passed)"), "none")

    def runners(self):
        return self.adapter(runner=[
            {"name": "b", "match": "bee", "command": "bee test",
             "when": {"file": "pkg.json", "tables": ["deps", "dev"], "has": ["bee"], "lacks": ["ant"]}},
            {"name": "m", "match": "mk", "command": "mk check", "when": {"file": "Makefile"}, "separator": "::"},
            {"name": "a", "subcommand": {"word": "go"}, "separator": " "}])

    def crate(self, files):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        for name, text in files.items():
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        return d

    def test_an_optional_count_group_that_matched_nothing_counts_nothing(self):
        a = self.adapter(outcome={"passed": r"(\d+)? passed", "failed": r"(\d+) failed"})
        self.assertEqual(a.outcome(0, "all passed"), "none")
        self.assertEqual(a.outcome(0, "3 passed"), "pass")

    def test_a_count_group_that_is_not_a_number_counts_nothing(self):
        a = self.adapter(outcome={"summary": r"^Result:(.*)$", "passed": r"(\w+) passed", "failed": r"(\w+) failed"})
        self.assertEqual(a.outcome(0, "Result: all passed"), "none")
        self.assertEqual(a.outcome(0, "Result: 2 passed"), "pass")

    def test_a_when_file_that_is_not_json_never_holds(self):
        a = self.adapter(runner=[{"name": "b", "match": "bee", "command": "bee test",
                                  "when": {"file": "pkg.json", "tables": ["deps"], "has": ["bee"]}}])
        self.assertEqual(a.test_cmd_in(self.crate({"pkg.json": "{not json"})), "minitest")
        self.assertEqual(a.test_cmd_in(self.crate({"pkg.json": "\xff"})), "minitest")

    def test_a_link_is_not_made_where_the_worktree_has_no_project_dir(self):
        a = self.adapter(links=["deps"])
        repo, wt = self.crate({}), self.crate({})
        os.makedirs(os.path.join(repo, "pkg", "deps"))
        a.worktree_setup(repo, wt, "pkg")
        self.assertEqual(os.listdir(wt), [])

    def test_a_link_is_made_for_a_directory_only_as_the_built_in_ts_does(self):
        a = self.adapter(links=["node_modules"])
        repo, wt = self.crate({"node_modules": "a file, not an install"}), self.crate({})
        a.worktree_setup(repo, wt, ".")
        self.assertFalse(os.path.lexists(os.path.join(wt, "node_modules")))

    def test_the_command_for_a_checkout_is_the_first_runner_whose_when_holds(self):
        a = self.runners()
        self.assertEqual(a.test_cmd_in(self.crate({"pkg.json": '{"dev": {"bee": "1"}}'})), "bee test")
        self.assertEqual(a.test_cmd_in(self.crate({"pkg.json": '{"deps": {"bee": "1"}, "dev": {"ant": "1"}}'})),
                         "minitest")
        self.assertEqual(a.test_cmd_in(self.crate({"pkg.json": '{"deps": {"cat": "1"}}'})), "minitest")
        self.assertEqual(a.test_cmd_in(self.crate({"pkg.json": "not json", "Makefile": ""})), "mk check")
        self.assertEqual(a.test_cmd_in(self.crate({"pkg.json": '["bee"]'})), "minitest")
        self.assertEqual(a.test_cmd_in(self.crate({})), "minitest")

    def test_the_runner_for_an_argv_is_the_first_whose_match_is_in_a_word(self):
        a = self.runners()
        self.assertEqual(a.test_argv("./bee-run x", "t.mini", "S > t"), ["./bee-run", "x", "--only", "S > t"])
        self.assertEqual(a.test_argv("mk", "t.mini", "S > t"), ["mk", "--only", "S::t"])
        # the catch-all runner: its subcommand has no `after`, so it goes at the end when missing
        self.assertEqual(a.test_argv("minitest -v", "t.mini", "S > t"), ["minitest", "-v", "go", "--only", "S t"])
        self.assertEqual(a.test_argv("minitest go -v", "t.mini", "S > t"), ["minitest", "go", "-v", "--only", "S t"])

    def test_a_subcommand_goes_after_the_word_that_holds_after(self):
        a = self.adapter(runner=[{"name": "v", "subcommand": {"word": "run", "after": "vt"}}],
                         test=["{path}", "-t", "{name}"])
        self.assertEqual(a.test_argv("npx vt --silent", "t.mini", "t"), ["npx", "vt", "run", "--silent", "t.mini", "-t", "t"])
        self.assertEqual(a.test_argv("npm test", "t.mini", "t"), ["npm", "test", "run", "t.mini", "-t", "t"])

    def test_a_name_part_is_escaped_with_no_placeholders_configured(self):
        a = self.adapter(name={"escape": "\\^$.|?*+()[]{}/"}, test=["^{name}$"])
        self.assertEqual(a.test_argv("minitest", "t.mini", "a.b (1)"), ["minitest", "^a\\.b \\(1\\)$"])

    def test_a_placeholder_pattern_that_matches_only_empty_text_replaces_nothing(self):
        a = self.adapter(name={"placeholders": "(?<=[a-w])", "any": ".*"}, test=["^{name}$"])  # loads: no probe has a-w
        self.assertEqual(a.test_argv("minitest", "t.mini", "adds"), ["minitest", "^adds$"])

    def test_outcome_patterns_count_only_on_a_match_that_holds_text(self):
        a = self.adapter(outcome={"summary": "(?<=[a-w])", "passed": r"(\d+) passed", "failed": r"(\d+) failed",
                                  "skipped": r"(?<=[a-w])()", "build": "(?<=[a-w])", "no_test": "(?=[A-Za-wyz])",
                                  "env": "(?<=[a-w])"})
        self.assertEqual(a.outcome(0, "No test files found"), "error")
        self.assertEqual(a.outcome(0, "1 passed"), "error")  # the summary never matches text: no summary line
        b = self.adapter(outcome={"passed": r"(\d+) passed", "failed": r"(\d+) failed", "build": "(?<=[a-w])",
                                  "no_test": "(?=[A-Za-wyz])", "env": "(?<=[a-w])", "skipped": r"(?<=[a-w])(\d*)"})
        self.assertEqual(b.outcome(0, "0 passed, nothing ran"), "none")
        self.assertEqual(b.outcome(1, "0 passed, nothing ran"), "error")
        self.assertEqual(b.outcome(0, "2 passed"), "pass")

    def test_why_keeps_the_last_character_of_a_last_line_without_a_newline(self):
        a = self.adapter(outcome=FULL_OUTCOME)
        self.assertEqual(a.why("none", "banner\nno such test x"), "no such test x")
        self.assertEqual(a.why("env", "runtime missing: erlang"), "runtime missing: erlang")
        self.assertEqual(a.why("none", "banner\nno such test x\nmore"), "no such test x")
        self.assertIsNone(a.why("fail", "no such test x"))

    def test_name_parts_are_escaped_and_placeholders_replaced(self):
        a = self.adapter(name={"escape": "().", "placeholders": r"%s", "any": "*"})
        self.assertEqual(a.test_argv("minitest", "t.mini", "f(x) > %s.y"), ["minitest", "--only", "f\\(x\\) > *\\.y"])

    def test_links_are_made_only_where_the_caller_has_the_path_and_the_worktree_does_not(self):
        a = self.adapter(links=["deps", "cache", "made"])
        repo, wt = self.crate({}), self.crate({})
        os.makedirs(os.path.join(repo, "deps"))
        os.makedirs(os.path.join(repo, "made"))
        os.makedirs(os.path.join(wt, "made"))
        a.worktree_setup(repo, wt, ".")
        self.assertEqual(os.path.realpath(os.path.join(wt, "deps")), os.path.realpath(os.path.join(repo, "deps")))
        self.assertFalse(os.path.lexists(os.path.join(wt, "cache")))
        self.assertFalse(os.path.islink(os.path.join(wt, "made")))


if __name__ == "__main__":
    unittest.main()
