"""[mutation.tool] in an adapter file (#19): adapter_file.parse validates the declared mutation tool at load, so a bad
value is an AdapterFileError naming the field, never a crash or a silent default in R3. Pure: the dicts are what tomllib
would read."""
import copy
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review.adapter_file import AdapterFileError, parse

BASE = {
    "format": 1,
    "name": "mini",
    "extensions": [".mini"],
    "lexer": {"block_style": "braces", "brackets": ["()", "{}"], "line_comments": ["#"],
              "strings": [{"quote": '"', "escape": "\\"}]},
    "tests": {"style": "calls", "groups": ["suite"], "cases": ["test", "xtest"], "skip": ["xtest"]},
    "asserts": {"call": [{"names": ["assertEquals"], "kind": "eq", "operands": [0, 1]}]},
}
TOOL = {"name": "mut", "command": "mut", "args": ["--files", "{mutate}", "--timeout", "{timeout_s}"],
        "mutate": "{file}:{first}-{last}", "report": "out/report.json", "format": "mutation-testing-elements",
        "os": ["linux", "macos"]}
LINES = {"name": "mut", "command": "mut", "report": "out/report.txt", "format": "lines", "os": ["linux"],
         "pattern": r"^(?P<file>\S+):(?P<line>\d+) (?P<status>\w+)$",
         "status": {"missed": ["SURVIVED"], "caught": ["KILLED"], "timeout": ["SLOW"], "unviable": ["BROKEN"]}}
RUN = {"commands": {"install": "", "build": "", "lint": "", "test": "run-tests"},
       "run": {"test": ["{path}", "{name}"], "outcome": {"passed": r"(\d+) passed", "failed": r"(\d+) failed"},
               "runner": [{"name": "fast", "match": "fast"}, {"name": "slow"}]}}


def with_tool(tool=TOOL, mutation=None, **top):
    d = copy.deepcopy(BASE)
    d["mutation"] = dict(mutation or {}, tool=tool)
    d.update(copy.deepcopy(top))
    return d


def changed(**kv):
    t = copy.deepcopy(TOOL)
    for k, v in kv.items():
        if v is DEL:
            t.pop(k, None)
        else:
            t[k] = v
    return t


def lines(**kv):
    t = copy.deepcopy(LINES)
    for k, v in kv.items():
        if v is DEL:
            t.pop(k, None)
        else:
            t[k] = v
    return t


DEL = object()


class Declared(unittest.TestCase):
    def err(self, data):
        with self.assertRaises(AdapterFileError) as cm:
            parse(data)
        return str(cm.exception)

    def test_a_valid_tool_is_the_adapters_mutation_tool(self):
        tool = parse(with_tool()).mutation_tool
        self.assertEqual((tool["name"], tool["command"], tool["report"], tool["format"], tool["os"], tool["timeout"]),
                         ("mut", "mut", "out/report.json", "mutation-testing-elements", ["linux", "macos"], 120))

    def test_no_tool_is_none(self):
        self.assertIsNone(parse(copy.deepcopy(BASE)).mutation_tool)
        self.assertIsNone(parse(dict(copy.deepcopy(BASE), mutation={"skip_comments": ["x"]})).mutation_tool)

    def test_each_required_key_is_named_when_missing(self):
        for k in ("name", "command", "report", "format", "os"):
            with self.subTest(k):
                self.assertEqual(self.err(with_tool(changed(**{k: DEL}))), f"mutation.tool.{k}: missing")

    def test_an_unknown_key_is_named(self):
        self.assertEqual(self.err(with_tool(changed(install="npm i"))), "mutation.tool.install: unknown key")

    def test_a_tool_that_is_not_a_table(self):
        self.assertEqual(self.err(with_tool("stryker")), "mutation.tool: want a table")

    def test_an_unknown_format_lists_the_three(self):
        self.assertEqual(self.err(with_tool(changed(format="junit"))),
                         "mutation.tool.format: `junit`: want mutation-testing-elements, pit-xml or lines")

    def test_os_values_are_target_oses_listed_once(self):
        self.assertEqual(self.err(with_tool(changed(os=[]))), "mutation.tool.os: want at least one entry")
        self.assertEqual(self.err(with_tool(changed(os=["Linux"]))),
                         "mutation.tool.os[0]: `Linux`: want linux, macos or windows")
        self.assertEqual(self.err(with_tool(changed(os=["linux", "linux"]))),
                         "mutation.tool.os[1]: `linux` is listed twice")
        self.assertEqual(self.err(with_tool(changed(os="linux"))), "mutation.tool.os: want a list of non-empty strings")

    def test_command_blank_or_unbalanced_quotes(self):
        self.assertEqual(self.err(with_tool(changed(command="  "))), "mutation.tool.command: want a command, not blank")
        self.assertIn("mutation.tool.command: `x 'y`: unbalanced quotes", self.err(with_tool(changed(command="x 'y"))))

    def test_the_program_is_on_path_or_absolute_never_in_the_checkout(self):  # review F1
        for bad, word in (("tools/mut", "tools/mut"), ("./mvnw --batch", "./mvnw"),
                          ("node_modules/.bin/stryker run", "node_modules/.bin/stryker"), ("'a\\b.exe'", "a\\b.exe")):
            with self.subTest(bad):
                self.assertEqual(self.err(with_tool(changed(command=bad))),
                                 f"mutation.tool.command: `{word}` is a path in the project dir, which the PR "
                                 "under review can change: want a program on PATH or an absolute path outside it "
                                 "(install the tool with setup-command, or pass mutants-cmd)")
        for good in ("mut", "mvn -q", "/opt/mut/bin/mut --x", "'C:\\tools\\mut.exe'", "a\\b.exe"):  # the last: ab.exe
            with self.subTest(good):
                self.assertEqual(parse(with_tool(changed(command=good))).mutation_tool["command"], good)

    def test_args_placeholders_are_the_tools_only(self):
        self.assertEqual(self.err(with_tool(changed(args=["{path}"]))),
                         "mutation.tool.args[0]: unknown placeholder `{path}`: want `{mutate}` or `{timeout_ms}` or "
                         "`{timeout_s}` or `{report}`")
        self.assertIn("mutation.tool.args[0]: `{timeout_s!r}`: want plain",
                      self.err(with_tool(changed(args=["{timeout_s!r}"]))))
        self.assertEqual(self.err(with_tool(changed(args=[""]))), "mutation.tool.args: want a list of non-empty strings")

    def test_mutate_goes_with_a_mutate_placeholder(self):
        self.assertEqual(self.err(with_tool(changed(mutate=DEL))),
                         "mutation.tool.mutate: missing: an arg uses `{mutate}`, the changed line ranges")
        self.assertEqual(self.err(with_tool(changed(args=["run"]))),
                         "mutation.tool.mutate: never used: no arg has `{mutate}`")
        self.assertEqual(self.err(with_tool(changed(mutate="{file}:{start}"))),
                         "mutation.tool.mutate: unknown placeholder `{start}`: want `{file}` or `{first}` or `{last}`")
        self.assertEqual(self.err(with_tool(changed(mutate="{first}-{last}"))),
                         "mutation.tool.mutate: no `{file}`: a range names its file")
        self.assertEqual(self.err(with_tool(changed(mutate_join=""))), "mutation.tool.mutate_join: want a non-empty string")

    def test_report_is_a_file_under_the_project_dir(self):
        for bad in ("/tmp/r.json", "../r.json", "out/../../r.json", "out\\r.json", "out/./r.json", "out/", "."):
            with self.subTest(bad):
                self.assertTrue(self.err(with_tool(changed(report=bad))).startswith(f"mutation.tool.report: `{bad}`"),
                                bad)

    def test_timeout_is_a_whole_number_of_seconds(self):
        self.assertEqual(parse(with_tool(changed(timeout=30))).mutation_tool["timeout"], 30)
        self.assertEqual(parse(with_tool(changed(timeout=1))).mutation_tool["timeout"], 1)  # the least, 1 s
        for bad in (0, True, 1.5, "30"):
            with self.subTest(bad):
                self.assertEqual(self.err(with_tool(changed(timeout=bad))),
                                 "mutation.tool.timeout: want a whole number of seconds >= 1")

    def test_version_probe_and_its_pattern(self):
        tool = parse(with_tool(changed(version=["--version"], version_pattern=r"^\d+\.\d+"))).mutation_tool
        self.assertEqual(tool["version"], ["--version"])
        self.assertEqual(self.err(with_tool(changed(version_pattern="x"))),
                         "mutation.tool.version_pattern: needs version: the words that print the tool's version")
        self.assertIn("matches empty text", self.err(with_tool(changed(version=["-V"], version_pattern="(?=x)"))))
        self.assertIn("bad regex", self.err(with_tool(changed(version=["-V"], version_pattern="("))))

    def test_an_empty_version_probe_is_refused(self):
        self.assertEqual(self.err(with_tool(changed(version=[]))), "mutation.tool.version: want at least one entry")

    def test_runners_that_are_not_a_table(self):
        for bad in (3, "fast", ["fast"], True):
            with self.subTest(bad):
                self.assertEqual(self.err(with_tool(changed(runners=bad), **RUN)), "mutation.tool.runners: want a table")

    def test_baseline_failed_is_a_pattern_that_needs_output(self):
        self.assertIn("mutation.tool.baseline_failed: `x*` matches empty text",
                      self.err(with_tool(changed(baseline_failed="x*"))))

    def test_name_is_a_plain_word(self):
        self.assertEqual(self.err(with_tool(changed(name="a b"))),
                         "mutation.tool.name: `a b`: want letters, digits, _, - or .")
        self.assertEqual(self.err(with_tool(changed(name="mütt"))),
                         "mutation.tool.name: `mütt`: want letters, digits, _, - or .")
        self.assertEqual(parse(with_tool(changed(name="pit_2.x-y"))).mutation_tool["name"], "pit_2.x-y")


class LinesFormat(unittest.TestCase):
    def err(self, data):
        with self.assertRaises(AdapterFileError) as cm:
            parse(data)
        return str(cm.exception)

    def test_a_valid_lines_tool(self):
        tool = parse(with_tool(LINES)).mutation_tool
        self.assertEqual(tool["status"]["missed"], ["SURVIVED"])
        self.assertEqual(sorted(tool["pattern_rx"].groupindex), ["file", "line", "status"])

    def test_pattern_needs_the_three_named_groups(self):
        self.assertEqual(self.err(with_tool(lines(pattern=r"^(?P<file>\S+):(?P<line>\d+)$"))),
                         "mutation.tool.pattern: `^(?P<file>\\S+):(?P<line>\\d+)$` has no named group `status`: want "
                         "(?P<file>...), (?P<line>...) and (?P<status>...)")
        self.assertEqual(self.err(with_tool(lines(pattern=DEL))), "mutation.tool.pattern: missing: format lines reads "
                                                                  "each mutant with it")

    def test_a_pattern_that_matches_empty_text_is_refused(self):
        self.assertIn("matches empty text",
                      self.err(with_tool(lines(pattern=r"(?P<file>\S*):?(?P<line>\d*) ?(?P<status>\w*)"))))

    def test_status_lists(self):
        self.assertEqual(self.err(with_tool(lines(status=DEL))), "mutation.tool.status: missing: format lines maps "
                                                                "each status word to missed, caught, timeout or unviable")
        self.assertEqual(self.err(with_tool(lines(status={"caught": ["K"]}))), "mutation.tool.status.missed: missing")
        self.assertEqual(self.err(with_tool(lines(status={"missed": ["S"], "caught": ["K"], "dead": ["D"]}))),
                         "mutation.tool.status.dead: unknown key")
        self.assertEqual(self.err(with_tool(lines(status={"missed": ["S"], "caught": ["S"]}))),
                         "mutation.tool.status.caught[0]: `S` is already in mutation.tool.status.missed")
        self.assertEqual(self.err(with_tool(lines(status={"missed": [], "caught": ["K"]}))),
                         "mutation.tool.status.missed: want at least one entry")

    def test_pattern_and_status_belong_to_lines_only(self):
        self.assertEqual(self.err(with_tool(changed(pattern=LINES["pattern"]))),
                         "mutation.tool.pattern: format mutation-testing-elements has no pattern (lines only)")
        self.assertEqual(self.err(with_tool(changed(format="pit-xml", status=LINES["status"]))),
                         "mutation.tool.status: format pit-xml has no status lists (lines only)")


class Runners(unittest.TestCase):
    """mutation.tool.runners: per [[run.runner]], what the tool needs (a file in the project dir) and, when the project
    has none of [mutation].config_files, the args it adds and the config file it writes."""

    def err(self, data):
        with self.assertRaises(AdapterFileError) as cm:
            parse(data)
        return str(cm.exception)

    MUT = {"config_files": ["mut.json"], "config_name": "Mut config"}

    def test_valid_runners(self):
        tool = changed(runners={"fast": {"needs": "bin/fast", "args": ["--runner", "fast"]},
                                "slow": {"config_file": "mut.json", "config": '{"runner": "slow"}'}})
        got = parse(with_tool(tool, self.MUT, **RUN)).mutation_tool["runners"]
        self.assertEqual(got["fast"]["args"], ["--runner", "fast"])

    def test_runners_need_run(self):
        self.assertEqual(self.err(with_tool(changed(runners={"fast": {}}), self.MUT)),
                         "mutation.tool.runners: needs [run]: a runner is one of [[run.runner]]")

    def test_a_runner_name_is_one_of_run_runner(self):
        self.assertEqual(self.err(with_tool(changed(runners={"jest": {}}), self.MUT, **RUN)),
                         "mutation.tool.runners.jest: not a [[run.runner]] name: want fast or slow")

    def test_a_run_table_with_no_runner_names_none_to_pick(self):
        run = {"commands": RUN["commands"], "run": {k: v for k, v in RUN["run"].items() if k != "runner"}}
        self.assertEqual(self.err(with_tool(changed(runners={"fast": {}}), self.MUT, **run)),
                         "mutation.tool.runners.fast: not a [[run.runner]] name: want a [[run.runner]] first")

    def test_runner_keys(self):
        bad = {"needs": "../x"}
        self.assertTrue(self.err(with_tool(changed(runners={"fast": bad}), self.MUT, **RUN))
                        .startswith("mutation.tool.runners.fast.needs: `../x`"))
        self.assertEqual(self.err(with_tool(changed(runners={"fast": {"env": "x"}}), self.MUT, **RUN)),
                         "mutation.tool.runners.fast.env: unknown key")
        self.assertEqual(self.err(with_tool(changed(runners={"fast": {"config": "{}"}}), self.MUT, **RUN)),
                         "mutation.tool.runners.fast.config_file: missing: config is written to it")
        self.assertEqual(self.err(with_tool(changed(runners={"fast": {"config_file": "mut.json"}}), self.MUT, **RUN)),
                         "mutation.tool.runners.fast.config: missing: the text written to config_file")

    def test_the_config_file_is_one_of_the_config_files(self):
        r = {"fast": {"config_file": "other.json", "config": "{}"}}
        self.assertEqual(self.err(with_tool(changed(runners=r), self.MUT, **RUN)),
                         "mutation.tool.runners.fast.config_file: `other.json` is not in mutation.config_files: it is "
                         "written only when the project has none of them")

    def test_a_config_file_with_no_config_files_at_all_is_named(self):
        r = {"fast": {"config_file": "mut.json", "config": "{}"}}
        self.assertEqual(self.err(with_tool(changed(runners=r), None, **RUN)),
                         "mutation.tool.runners.fast.config_file: `mut.json` is not in mutation.config_files: it is "
                         "written only when the project has none of them")

    def test_the_config_text_is_a_json_object(self):
        for bad in ("[1]", "{", "{\"a\": NaN}"):
            with self.subTest(bad):
                r = {"fast": {"config_file": "mut.json", "config": bad}}
                self.assertTrue(self.err(with_tool(changed(runners=r), self.MUT, **RUN))
                                .startswith("mutation.tool.runners.fast.config: want a JSON object"), bad)


if __name__ == "__main__":
    unittest.main()
