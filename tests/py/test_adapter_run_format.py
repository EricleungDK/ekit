"""The run side of an adapter file (#18): [commands] and [run] are validated at load, so a bad one is an AdapterFileError
naming the field, never a crash in R1 or R4. Pure: adapter_file.parse on the dicts tomllib reads, and loads on bytes."""
import copy
import os
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

    def test_the_shipped_ts_file_has_the_run_side(self):
        with open(os.path.join(_kit.ROOT, "scripts", "mech_review", "adapters", "ts.toml"), "rb") as f:
            a = loads(f.read(), "ts.toml")
        self.assertEqual(a.commands, {"install": "npm ci", "build": "", "lint": "", "test": "node_modules/.bin/vitest run"})


if __name__ == "__main__":
    unittest.main()
