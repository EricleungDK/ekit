"""R2 through a parser-backed adapter file (#27): `[parser]` names one command that prints a file's facts as JSON.

The stub (tests/fixtures/parser/mini_facts.py) reads `mini` files the way tests/fixtures/adapters/mini.toml does, so
the parser-backed file and the pattern file must give the same R2 entries. A parser that cannot run, or prints what the
fact schema refuses, gives one blocking `CI` entry and never a pattern fallback. Through cli.main in this process."""
import json
import os
import shlex
import sys
import tempfile
import time
import unittest

import _kit
from scripts.mech_review import adapter_file
from test_adapter_cli import BASE, MINI, Repo, r2
from test_r0 import FUNCTIONS

STUB = os.path.join(_kit.ROOT, "tests", "fixtures", "parser", "mini_facts.py")
MINI_FIXTURES = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.r0")


def parser_toml(opts="", extra=""):
    """the parser-backed twin of mini.toml: same name, manifest and extensions, the stub as its command."""
    cmd = " ".join(shlex.quote(x) for x in [sys.executable, "-I", STUB] + shlex.split(opts))
    return (f'format = 1\nname = "mini"\nmanifests = ["mini.json"]\nextensions = [".mini"]\n\n[parser]\n'
            f'command = {json.dumps(cmd)}\ninstall = "pip install mini-facts==1.0.0"\nversion = "1.0.0"\n'
            f'skipped_text = "test `{{name}}` marked xtest"\n{extra}')


class ParserR2(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = Repo(os.path.join(tmp.name, "repo"))
        self.base = self.repo.commit({"tests/calc.mini": BASE, "src/calc.mini": "fn add(a, b) { a + b }\n"}, "base")

    def adapter(self, opts="", extra="", name="parser.toml"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(parser_toml(opts, extra))
        return path

    def head(self, files):
        self.repo.git("checkout", "-q", "--detach", self.base)
        return self.repo.commit(files, "head")

    def entries(self, head, adapter):
        r = r2(self.repo, self.base, head, adapter=adapter)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return json.loads(r.stdout)["entries"]

    def test_valid_facts_give_the_same_r2_entries_as_the_pattern_adapter(self):
        heads = {
            "removed": {"tests/calc.mini": BASE.replace('  test("subtracts", {\n    assertTrue(sub(3, 1) == 2)\n  })\n', "")},
            "skipped": {"tests/calc.mini": BASE.replace('test("adds"', 'xtest("adds"')},
            "expected": {"tests/calc.mini": BASE.replace("assertEquals(3,", "assertEquals(4,")},
            "dropped": {"tests/calc.mini": BASE.replace("    assertTrue(sub(3, 1) == 2)\n", "")},
            "replaced": {"tests/calc.mini": BASE.replace("assertTrue(sub(3, 1) == 2)", "assertTrue(sub(3, 1) > 0)")},
            "suppression": {"src/calc.mini": "# lint-off unused\nfn add(a, b) { a + b }\n"},
            "unparsed": {"tests/calc.mini": BASE.replace("add(1, 2))", "add(1, 2)")},
            "renamed": {"tests/calc.mini": BASE.replace('test("adds"', 'test("sums"')},
        }
        parser = self.adapter()
        got = {}
        for case, files in heads.items():
            head = self.head(files)
            want = self.entries(head, MINI)
            have = self.entries(head, parser)
            self.assertEqual(have, want, case)
            got[case] = [(e["check"], e["severity"], e["line"], e["problem"]) for e in have]
        self.assertEqual(got, {
            "removed": [("R2", "fail", 5, "test fn `Calc / subtracts` removed")],
            "skipped": [("R2", "fail", 2, "test `Calc / adds` marked xtest")],
            "expected": [("R2", "confirm", 3, "expected value changed in `Calc / adds`: was 3, now 4")],
            "dropped": [("R2", "fail", 5, "assertions in test `Calc / subtracts` dropped from 1 to 0")],
            "replaced": [("R2", "confirm", 6, "assertion replaced in `Calc / subtracts`: `assertTrue(sub(3, 1) == 2)` -> "
                                              "`assertTrue(sub(3, 1) > 0)`")],
            "suppression": [("R2", "fail", 1, "`lint-off unused` added without a reason")],
            "unparsed": [("R2", "fail", 4, "file does not parse: unexpected `}` (line 4)")],
            "renamed": [],
        })


    # ---- P2: a parser that cannot run, or prints what the schema refuses: one CI entry, no fallback ----
    def removed_head(self):
        """a head that removes a test, so a pattern fallback would give an R2 entry, and edits a protected path."""
        return self.head({"tests/calc.mini": BASE.replace('  test("subtracts", {\n    assertTrue(sub(3, 1) == 2)\n  })\n', ""),
                          ".github/ci.yml": "x: 1\n"})

    def failed(self, adapter, head=None):
        """(exit code, [(check, class, severity, file)], the CI entry's problem) of R2 at a head the parser fails on."""
        r = r2(self.repo, self.base, head or self.removed_head(), "--protected-paths", ".github/**", adapter=adapter)
        self.assertEqual(r.returncode, 1, r.stderr)
        env = json.loads(r.stdout)
        ents = env["entries"]
        self.assertEqual(env["checks"]["R2"]["status"], "fail")
        ci = [e for e in ents if e["check"] == "CI"]
        self.assertEqual(len(ci), 1, ents)
        return sorted((e["check"], e["class"], e["severity"], e["file"]) for e in ents), ci[0]["problem"]

    def emit(self, text):
        path = os.path.join(self.tmp, "canned.json")
        with open(path, "wb") as f:
            f.write(text if isinstance(text, bytes) else text.encode("utf-8"))
        return self.adapter("--emit " + shlex.quote(path))

    def test_invalid_json_is_one_ci_entry_and_no_fallback(self):
        ents, problem = self.failed(self.emit("{not json"))
        self.assertEqual(ents, [("CI", "adapter-fix", "fail", "tests/calc.mini"),
                                ("R2", "needs-human", "fail", ".github/ci.yml")])
        self.assertTrue(problem.startswith(f"the adapter's parser failed: parser `{sys.executable}` on tests/calc.mini: "
                                           "printed invalid JSON: "), problem)

    def test_a_non_zero_exit_is_one_ci_entry_naming_the_status(self):
        ents, problem = self.failed(self.adapter("--exit 3"))
        self.assertEqual(ents[0], ("CI", "adapter-fix", "fail", "tests/calc.mini"))
        self.assertTrue(problem.endswith("on tests/calc.mini: exited with status 3"), problem)

    def test_a_command_that_cannot_run_is_one_ci_entry(self):
        path = self.adapter()
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace(json.dumps(sys.executable)[1:-1], os.path.join(self.tmp, "no-such-parser"), 1))
        ents, problem = self.failed(path)
        self.assertIn("cannot run `" + os.path.join(self.tmp, "no-such-parser") + "`", problem)

    def test_output_past_the_size_limit_is_refused_unread(self):
        _, problem = self.failed(self.emit(b" " * (16 * 1024 * 1024 + 1)))
        self.assertTrue(problem.endswith("on tests/calc.mini: printed more than 16777216 bytes"), problem)

    def test_a_parser_that_hangs_hits_the_timeout_and_is_one_ci_entry(self):
        ents, problem = self.failed(self.adapter("--hang", extra="timeout = 1\n"))
        self.assertTrue(problem.endswith("on tests/calc.mini: timed out after 1s"), problem)

    def test_facts_the_schema_refuses_are_one_ci_entry_naming_the_field(self):
        good = {"format": 1, "parse_error": None, "tests": [], "asserts": [], "suppressions": [], "mutation_skips": []}
        test = {"name": "a", "line": 1, "end_line": 2, "markers": [], "body": None, "calls": []}
        ast = {"line": 1, "test": None, "owner": None, "kind": "other", "left": None, "right": None, "text": "t"}
        cases = [
            ([], "facts: want an object"),
            (dict(good, extra=1), "facts.extra: unknown key"),
            ({k: v for k, v in good.items() if k != "asserts"}, "facts.asserts: missing"),
            (dict(good, format=2), "format: want 1"),
            (dict(good, format=True), "format: want 1"),
            (dict(good, tests={}), "tests: want a list"),
            (dict(good, tests=[dict(test, line=True)]), "tests[0].line: want a whole number from 1 to "),
            (dict(good, tests=[dict(test, line=1.0)]), "tests[0].line: want a whole number from 1 to "),
            (dict(good, tests=[dict(test, line=0)]), "tests[0].line: want a whole number from 1 to "),
            (dict(good, tests=[dict(test, line=99999)]), "tests[0].line: want a whole number from 1 to "),
            (dict(good, tests=[dict(test, line=3, end_line=2)]), "tests[0].end_line: want a whole number from 3 to "),
            (dict(good, tests=[dict(test, body=[2, 1])]), "tests[0].body[1]: want a whole number from 2 to 2"),
            (dict(good, tests=[dict(test, body=[1, 3])]), "tests[0].body[1]: want a whole number from 1 to 2"),
            (dict(good, tests=[dict(test, body=[1])]), "tests[0].body: want null or [first, last]"),
            (dict(good, tests=[dict(test, markers=["skip"])]), "tests[0].markers[0]: want ignore, only or should_panic"),
            (dict(good, tests=[dict(test, markers=["only", "only"])]), "tests[0].markers[1]: `only` given twice"),
            (dict(good, tests=[dict(test, name="")]), "tests[0].name: want a non-empty string"),
            (dict(good, tests=[dict(test, name="x" * 70000)]), "tests[0].name: longer than 65536 characters"),
            (dict(good, tests=[dict(test, calls=[1])]), "tests[0].calls[0]: want a non-empty string"),
            (dict(good, tests=[dict(test, oops=1)]), "tests[0].oops: unknown key"),
            (dict(good, asserts=[dict(ast, test="ghost")]), "asserts[0].test: `ghost` is not a name in tests"),
            (dict(good, asserts=[dict(ast, kind="eqq")]), "asserts[0].kind: want eq, ne or other"),
            (dict(good, asserts=[dict(ast, kind="eq")]), "asserts[0].left: want a non-empty string"),
            (dict(good, asserts=[dict(ast, left="a")]), "asserts[0]: kind other has no operands"),
            (dict(good, asserts=[dict(ast, text="")]), "asserts[0].text: want a non-empty string"),
            (dict(good, suppressions=[{"line": 1, "end_line": 1, "kind": "k", "lints": "k", "reason": 0}]),
             "suppressions[0].reason: want true or false"),
            (dict(good, mutation_skips=[{"line": 2, "end_line": 1, "marker": "m"}]),
             "mutation_skips[0].end_line: want a whole number from 2 to "),
            (dict(good, parse_error={"line": 1}), "parse_error.message: missing"),
            # review round 1: a lone surrogate (it cannot be written as UTF-8: the entry ids and the comment would
            # crash), a control character, whitespace-only names and operands, an assert outside its test's lines
            (dict(good, tests=[dict(test, name="\ud800")]), "tests[0].name: want text without a lone surrogate"),
            (dict(good, asserts=[dict(ast, text="a\udfffb")]), "asserts[0].text: want text without a lone surrogate"),
            (dict(good, parse_error={"line": 1, "message": "\ud800"}),
             "parse_error.message: want text without a lone surrogate"),
            (dict(good, tests=[dict(test, name="a\x1b[2Jb")]), "tests[0].name: want text without control characters"),
            (dict(good, tests=[dict(test, name="a\nb")]), "tests[0].name: want text without control characters"),
            (dict(good, tests=[dict(test, name="  ")]), "tests[0].name: want a non-empty string"),
            (dict(good, asserts=[dict(ast, text=" \t ")]), "asserts[0].text: want a non-empty string"),
            (dict(good, tests=[test], asserts=[dict(ast, test="a", kind="eq", left=" ", right="1")]),
             "asserts[0].left: want a non-empty string"),
            (dict(good, tests=[test], asserts=[dict(ast, test="a", kind="ne", left="1", right="\t")]),
             "asserts[0].right: want a non-empty string"),
            (dict(good, tests=[dict(test, line=1, end_line=1)], asserts=[dict(ast, line=2, test="a")]),
             "asserts[0].line: 2 is outside test `a` (lines 1 to 1)"),
        ]
        for doc, want in cases:
            with self.subTest(want=want):
                _, problem = self.failed(self.emit(json.dumps(doc)))
                self.assertIn("printed facts the schema refuses: " + want, problem)
        for raw, want in ((b'{"format": 1, "format": 1}', "key `format` given twice"), (b"NaN", "`NaN` is not JSON"),
                          (b"\xff", "not UTF-8"), (b"[" * 100000, "nested too deep"), (b"", "Expecting value")):
            with self.subTest(want=want):
                _, problem = self.failed(self.emit(raw))
                self.assertIn("printed invalid JSON: " + want, problem)

    def test_an_assert_text_may_span_lines_and_a_name_repeat_within_the_spans(self):
        doc = {"format": 1, "parse_error": None, "suppressions": [], "mutation_skips": [],
               "tests": [{"name": "a", "line": 1, "end_line": 1, "markers": [], "body": None, "calls": []},
                         {"name": "a", "line": 2, "end_line": 3, "markers": [], "body": None, "calls": []}],
               "asserts": [{"line": 3, "test": "a", "owner": "a", "kind": "other", "left": None, "right": None,
                            "text": "ok(\n\tx)"}]}
        a = adapter_file.load(self.emit(json.dumps(doc))).at("tests/a.mini")
        self.assertEqual([(x.line, x.fn, x.text) for x in a.assertions("1\n2\n3\n")], [(3, "a", "ok( x)")])

    def test_many_keys_under_the_size_limit_are_checked_in_linear_time(self):
        keys = 300000  # about 4 MiB: a quadratic duplicate-key check takes hours here (the twice-given key is last)
        raw = ("{" + ",".join(f'"k{i}": 0' for i in range(keys)) + f', "k{keys - 1}": 1}}').encode()
        start = time.monotonic()
        _, problem = self.failed(self.emit(raw))
        self.assertIn(f"printed invalid JSON: key `k{keys - 1}` given twice", problem)
        self.assertLess(time.monotonic() - start, 60)


    def test_operands_are_compared_with_whitespace_removed_and_texts_normalized(self):
        doc = {"format": 1, "parse_error": None, "suppressions": [], "mutation_skips": [],
               "tests": [{"name": "a", "line": 1, "end_line": 1, "markers": [], "body": None, "calls": []}],
               "asserts": [{"line": 1, "test": "a", "owner": "a", "kind": "eq", "left": " 3 ", "right": "add(1,  2)",
                            "text": "eq( 3,\n add(1,  2))"}]}
        a = adapter_file.load(self.emit(json.dumps(doc))).at("tests/a.mini")
        self.assertEqual([(x.fn, x.scope, x.kind, x.left, x.right, x.text, x.owner) for x in a.assertions("x\n")],
                         [("a", True, "eq", "3", "add(1,2)", "eq( 3, add(1, 2))", "a")])

    # ---- P4: the parser gets one file's text and path, in an empty dir, with no secret and no project config ----
    def test_the_parser_gets_the_text_and_path_only_in_an_empty_dir_with_a_minimal_env(self):
        record = os.path.join(self.tmp, "record.jsonl")
        head = self.head({"tests/calc.mini": BASE.replace("assertEquals(3,", "assertEquals(4,"),
                          "mini.json": "{}\n", ".ekit/adapters/mini.toml": parser_toml("--exit 9")})
        os.environ["EKIT_TEST_SECRET"] = "s3cret"
        self.addCleanup(os.environ.pop, "EKIT_TEST_SECRET", None)
        r = r2(self.repo, self.base, head, adapter=self.adapter("--record " + shlex.quote(record)))
        self.assertEqual([e["problem"] for e in json.loads(r.stdout)["entries"]],
                         ["expected value changed in `Calc / adds`: was 3, now 4"], r.stderr)
        with open(record) as f:
            runs = [json.loads(ln) for ln in f]
        self.assertEqual(sorted(x["stdin"] for x in runs),
                         sorted([BASE, BASE.replace("assertEquals(3,", "assertEquals(4,")]))
        for x in runs:
            self.assertEqual(x["argv"], ["--record", record, "tests/calc.mini"])
            self.assertEqual(x["cwd_files"], [])
            self.assertFalse(os.path.realpath(x["cwd"]).startswith(os.path.realpath(self.repo.path)), x["cwd"])
            self.assertEqual(sorted(x["env"]), ["HOME", "LANG", "LC_ALL", "PATH", "TMPDIR"])
            self.assertEqual(os.path.realpath(x["env"]["HOME"]), os.path.realpath(x["cwd"]))
        self.assertFalse(any(os.path.exists(x["cwd"]) for x in runs), "the parser's dir outlives its run")


    # ---- P3: R0 judges a parser-backed adapter as it judges a pattern one ----
    def r0(self, adapter, base=None, head=None):
        r = _kit.run_cli(["r0", "--repo", self.repo.path, "--base", base or self.base, "--head", head or base or self.base,
                          "--stack", "mini", "--adapter", adapter, "--fixtures", MINI_FIXTURES])
        return r.returncode, json.loads(r.stdout)["checks"]["R0"], r

    ADAPTER = ".ekit/adapters/mini.toml"

    def in_repo(self, base_file, head_file=None):
        """(the adapter's path in the checkout, base, head): base_file's text committed on base, head_file's on head."""
        texts = []
        for p in (base_file, head_file or base_file):
            with open(p) as f:
                texts.append(f.read())
        self.repo.git("checkout", "-q", "--detach", self.base)
        base = self.repo.commit({self.ADAPTER: texts[0]}, "adapter")
        head = self.repo.commit({self.ADAPTER: texts[1]}, "adapter at head") if texts[1] != texts[0] else base
        return os.path.join(self.repo.path, self.ADAPTER), base, head

    def test_r0_passes_a_parser_backed_adapter_on_the_mini_fixtures(self):
        table = os.path.join(self.tmp, "mini-fns.toml")  # mini.toml with helper fns, as R0's own mini test proves it
        with open(MINI) as f, open(table, "w") as out:
            out.write(f.read() + FUNCTIONS)
        path, base, _ = self.in_repo(self.adapter("--table " + shlex.quote(table)))  # its base copy is the same
        rc, check, r = self.r0(path, base)
        self.assertEqual((rc, check["status"]), (0, "pass"), r.stdout)
        self.assertEqual({c["case"]: c["status"] for c in check["cases"]},
                         {c: "pass" for c in ("delete", "comment-out", "rename", "skip", "expected-value", "weaken-assert",
                                              "suppression", "rename-same-asserts", "reorder-asserts", "helper-asserts",
                                              "empty-diff", "source-ident-chars", "source-empty-asserts",
                                              "source-unbalanced-brackets", "ident-chars", "empty-asserts",
                                              "unbalanced-brackets")})
        twin_rc, twin, _ = self.r0(table)
        self.assertEqual((twin_rc, [(c["case"], c["status"], c["got"]) for c in twin["cases"] if c["kind"] != "malformed-table"]),
                         (rc, [(c["case"], c["status"], c["got"]) for c in check["cases"] if c["kind"] != "malformed-table"]))
        self.assertEqual([c["got"].split(": ", 1)[1] for c in check["cases"] if c["kind"] == "malformed-table"],
                         ["lexer: not with [parser]: the parser command gives the facts, a file declares no patterns beside it",
                          "asserts: not with [parser]: the parser command gives the facts, a file declares no patterns beside it",
                          "lexer: not with [parser]: the parser command gives the facts, a file declares no patterns beside it"])

    def test_r0_fails_a_parser_that_prints_invalid_json(self):
        path, base, _ = self.in_repo(self.emit("nope"))
        rc, check, r = self.r0(path, base)
        self.assertEqual((rc, check["status"]), (1, "fail"), r.stdout)
        ent = json.loads(r.stdout)["entries"]
        self.assertEqual([(e["check"], e["class"]) for e in ent], [("R0", "adapter-fix")])
        self.assertIn("printed invalid JSON", ent[0]["problem"])

    def held(self, rc, check, r):
        """the needs-human entry of an R0 that did not run the parser: every case that reads source is unproven."""
        self.assertEqual((rc, check["status"]), (1, "unproven"), r.stdout)
        self.assertEqual({c["case"]: c["status"] for c in check["cases"] if c["status"] != "unproven"},
                         {"ident-chars": "pass", "empty-asserts": "pass", "unbalanced-brackets": "pass"})
        ents = json.loads(r.stdout)["entries"]
        self.assertEqual([(e["check"], e["class"], e["severity"]) for e in ents], [("R0", "needs-human", "fail")])
        self.assertTrue(ents[0]["problem"].startswith("parser command changed: a person reviews it before it runs"),
                        ents[0]["problem"])
        return ents[0]["problem"]

    def test_r0_never_runs_a_parser_command_that_differs_from_the_base_adapters(self):
        record = os.path.join(self.tmp, "record.jsonl")
        path, base, head = self.in_repo(self.adapter(), self.adapter("--record " + shlex.quote(record), name="pr.toml"))
        problem = self.held(*self.r0(path, base, head))
        self.assertIn(f"[parser] of {self.ADAPTER} differs from the base branch's", problem)
        self.assertFalse(os.path.exists(record), "R0 ran the PR's parser command")

    def test_r0_never_runs_a_parser_with_no_base_copy(self):
        record = os.path.join(self.tmp, "record.jsonl")
        problem = self.held(*self.r0(self.adapter("--record " + shlex.quote(record))))  # outside the repo
        self.assertIn("is not in the repo: no base copy to compare its [parser] with", problem)
        self.repo.git("checkout", "-q", "--detach", self.base)
        head = self.repo.commit({self.ADAPTER: parser_toml("--record " + shlex.quote(record))}, "new adapter")
        problem = self.held(*self.r0(os.path.join(self.repo.path, self.ADAPTER), self.base, head))
        self.assertIn(f"{self.ADAPTER} has no [parser] on the base branch", problem)
        self.assertFalse(os.path.exists(record), "R0 ran the PR's parser command")

    def test_r0_binds_each_fixture_to_its_own_path(self):
        record = os.path.join(self.tmp, "record.jsonl")
        path, base, _ = self.in_repo(self.adapter("--record " + shlex.quote(record)))
        self.r0(path, base)
        with open(record) as f:
            paths = {json.loads(ln)["argv"][-1] for ln in f}
        self.assertNotIn("input.mini", paths)
        self.assertIn(".ekit/scenarios/r0/seed.mini", paths)
        self.assertIn(".ekit/scenarios/r0/skip.mini", paths)


    def test_a_renamed_file_is_parsed_at_its_base_path_for_base_text_and_its_head_path_for_head_text(self):
        record = os.path.join(self.tmp, "record.jsonl")
        self.repo.git("checkout", "-q", "--detach", self.base)
        self.repo.git("mv", "tests/calc.mini", "tests/sums.mini")
        head = self.repo.commit({"tests/sums.mini": BASE.replace("assertEquals(3,", "assertEquals(4,")}, "rename")
        r = r2(self.repo, self.base, head, adapter=self.adapter("--record " + shlex.quote(record)))
        self.assertEqual([e["problem"] for e in json.loads(r.stdout)["entries"]],
                         ["expected value changed in `Calc / adds`: was 3, now 4"], r.stderr)
        with open(record) as f:
            runs = sorted((json.loads(ln)["argv"][-1], json.loads(ln)["stdin"] == BASE) for ln in f)
        self.assertEqual(runs, [("tests/calc.mini", True), ("tests/sums.mini", False)])

    def test_a_command_word_inside_the_checkout_is_refused_before_it_runs(self):
        record = os.path.join(self.tmp, "record.jsonl")
        inside = os.path.join(self.repo.path, "tools", "facts.py")
        os.makedirs(os.path.dirname(inside))
        with open(STUB) as f, open(inside, "w") as out:
            out.write(f.read().replace("os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(",
                                       repr(_kit.ROOT) + "  # (").replace("os.path.abspath(__file__)))))", ""))
        for cmd in (f"{sys.executable} -I {inside} --record {record}",
                    f"{sys.executable} -I {STUB} --record {record} --table={os.path.join(self.repo.path, 'x.toml')}"):
            with self.subTest(cmd=cmd):
                path = os.path.join(self.tmp, "inside.toml")
                with open(path, "w") as f:
                    f.write(parser_toml().replace(next(ln for ln in parser_toml().splitlines()
                                                       if ln.startswith("command = ")), f"command = {json.dumps(cmd)}"))
                _, problem = self.failed(path)
                self.assertIn("is inside the checkout: the parser runs no code or config from the PR", problem)
                self.assertFalse(os.path.exists(record), "the command ran")

class ParserTable(unittest.TestCase):
    """adapter_file.loads on a [parser] table: every bad value a clean error naming the field."""

    def load(self, text):
        return adapter_file.loads(text.encode("utf-8"), "p.toml")

    def error(self, text):
        with self.assertRaises(adapter_file.AdapterFileError) as cm:
            self.load(text)
        return str(cm.exception)

    def test_a_parser_table_loads_with_its_command_split_into_argv(self):
        a = self.load(parser_toml(extra="timeout = 5\n"))
        self.assertEqual((a.name, a.parser["command"], a.parser["timeout"], a.parser["version"]),
                         ("mini", [sys.executable, "-I", STUB], 5, "1.0.0"))
        self.assertEqual(self.load(parser_toml().replace('skipped_text = "test `{name}` marked xtest"\n', ""))
                         .ignored_text("t"), "test `t` marked skipped")

    def test_each_bad_parser_value_is_an_error_naming_the_field(self):
        base = parser_toml()
        inst = lambda cmd: base.replace('install = "pip install mini-facts==1.0.0"', f"install = {json.dumps(cmd)}")
        cmd = next(ln for ln in base.splitlines() if ln.startswith("command = "))
        cases = [
            (base.replace(cmd, 'command = "   "'), "parser.command: want a command, not only whitespace"),
            (base.replace(cmd, 'command = ""'), "parser.command: want a non-empty string"),
            (base.replace(cmd, 'command = ["facts"]'), "parser.command: want a non-empty string"),
            (base.replace(cmd, 'command = "facts \'unbalanced"'), "parser.command: `facts 'unbalanced`: No closing quotation"),
            (base.replace(cmd, 'command = "tools/facts --json"'), "parser.command: `tools/facts`: want a program on PATH"),
            (base.replace(cmd, 'command = "./facts"'), "parser.command: `./facts`: want a program on PATH"),
            (base.replace(cmd, 'command = "env PATH=/w/bin facts"'),
             "parser.command: `env` with `PATH=/w/bin`: want the program itself (no assignment or option for env)"),
            (base.replace(cmd, 'command = "/usr/bin/env -S facts"'),
             "parser.command: `env` with `-S`: want the program itself (no assignment or option for env)"),
            (base.replace(cmd, 'command = "facts\\u0000x"'), "parser.command: a NUL character cannot be in a command"),
            (base.replace('version = "1.0.0"', 'version = "latest"'), "parser.version: `latest`: want one pinned version"),
            (base.replace('version = "1.0.0"', 'version = ">=1.0"'), "parser.version: `>=1.0`: want one pinned version"),
            (base.replace('version = "1.0.0"', 'version = "1.0.1"'), "parser.install: does not pin version `1.0.1`"),
            # review round 1: the pin is an exact word of a pinned form, and no range operator anywhere
            (inst('pip install x==11.0.0'), "parser.install: does not pin version `1.0.0`"),
            (inst('pip install x>=1.0.0'), "parser.install: `x>=1.0.0` holds `>`: a range, not a pin"),
            (inst('pip install x~=1.0.0'), "parser.install: `x~=1.0.0` holds `~`: a range, not a pin"),
            (inst('npm i -g x@^1.0.0'), "parser.install: `x@^1.0.0` holds `^`: a range, not a pin"),
            (inst('pip install x==1.0.0 y<2'), "parser.install: `y<2` holds `<`: a range, not a pin"),
            (inst('pip install "x==1.0.*"'), "parser.install: `x==1.0.*` holds `*`: a range, not a pin"),
            (inst('echo 1.0.0'), "parser.install: does not pin version `1.0.0`"),
            (inst('pip install x==1.0.0.post1'), "parser.install: does not pin version `1.0.0`"),
            (inst('gem install x -v1.0.0'), "parser.install: does not pin version `1.0.0`"),
            (base.replace('version = "1.0.0"\n', ""), "parser.version: missing"),
            (base.replace('install = "pip install mini-facts==1.0.0"\n', ""), "parser.install: missing"),
            (base + "timeout = 0\n", "parser.timeout: want a whole number of seconds from 1 to 600"),
            (base + "timeout = 601\n", "parser.timeout: want a whole number of seconds from 1 to 600"),
            (base + "timeout = true\n", "parser.timeout: want a whole number of seconds from 1 to 600"),
            (base + "shell = true\n", "parser.shell: unknown key"),
            (base.replace("marked xtest", "marked {nme}"), "parser.skipped_text: unknown placeholder `{nme}`"),
            (base + '\n[lexer]\nblock_style = "braces"\nbrackets = ["()", "{}"]\n', "lexer: not with [parser]"),
            (base + '\n[asserts]\n', "asserts: not with [parser]"),
            (base + '\n[tests]\nstyle = "calls"\ncases = ["t"]\n', "tests: not with [parser]"),
            (base + '\n[[suppressions]]\ndirectives = ["x"]\ncovers = { x = "line" }\n', "suppressions: not with [parser]"),
            (base + '\n[mutation]\nskip_comments = ["keep"]\n', "mutation.skip_comments: not with [parser]"),
            (base.split("[parser]")[0], "lexer: missing"),  # no parser: the pattern tables are required
        ]
        for text, want in cases:
            with self.subTest(want=want):
                self.assertIn(want, self.error(text))
        self.assertEqual(self.load(base.replace(cmd, 'command = "/usr/bin/env facts --x=1"')).parser["command"],
                         ["/usr/bin/env", "facts", "--x=1"])
        for ok in ("pip install x==1.0.0", "npm install -g x@1.0.0", "cargo install x@1.0.0", "gem install x -v 1.0.0",
                   "cargo install x --version 1.0.0", "go install example.com/x@1.0.0", "gem install x --version=1.0.0"):
            with self.subTest(ok=ok):
                self.assertEqual(self.load(inst(ok)).parser["version"], "1.0.0")
        self.assertEqual(self.load(base + '\n[mutation]\nconfig_files = ["m.toml"]\nconfig_name = "m"\n')
                         .mutation_config("x/m.toml", None), "m")


if __name__ == "__main__":
    unittest.main()
