"""R1 and R4 through a parser-backed adapter file (#27) whose parser is not installed: `red` and `all` stop with a
usage-level error (exit 2) that names the parser, never a traceback, so the workflow's red-first step goes red and says
why. (R2 makes the same failure one CI entry; the run side names the changed tests from the parser's facts.)"""
import os
import tempfile

import _kit
from test_adapter_run import MINI_FRESH, MINI_RUN, MINI_STUB, MINI_TEST, Fixture
from test_parser_cli import HOME_VAR, parser_home, parser_toml


class RedWithoutTheParser(Fixture):
    def setUp(self):
        super().setUp()
        with open(os.environ["MECH_TEST_STUB"], "w") as f:
            f.write(MINI_STUB)
        os.environ.pop(HOME_VAR, None)
        self.text = parser_toml() + MINI_RUN  # load only: no program installed
        parser_home(self)  # an empty EKIT_PARSER_HOME: nothing installed there

    def pr(self, files):
        base = self.commit({"src/calc.mini": "fn add(a, b) { a + b }\n", "tests/calc.mini": MINI_TEST, **files})
        head = self.commit({"tests/calc.mini": MINI_FRESH, "tests/outcomes": "fresh fail pass\n",
                            "src/calc.mini": "fn add(a, b) { a + b } # fixed\n"})
        return base, head

    def check_stops(self, check, base, head, *extra):
        r = _kit.run_cli([check, "--repo", self.repo, "--base", base, "--head", head, "--stack", "mini",
                          "--test-paths", "tests/**", "--head-branch", "claude/x", *extra])
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        self.assertTrue(r.stderr.startswith("mech-review: the adapter's parser failed: parser `mini-facts` on "),
                        r.stderr)
        self.assertIn("not installed by the declared package (pip mini-facts 1.0.0", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_red_and_all_on_the_repos_file_stop_naming_the_parser(self):
        base, head = self.pr({".ekit/adapters/mini.toml": self.text})
        for check in ("red", "all"):
            with self.subTest(check=check):
                self.check_stops(check, base, head)

    def test_red_with_an_adapter_file_stops_naming_the_parser(self):
        base, head = self.pr({})
        path = os.path.join(self.tmp, "mini.toml")
        with open(path, "w") as f:
            f.write(self.text)
        for check in ("red", "all"):
            with self.subTest(check=check):
                self.check_stops(check, base, head, "--adapter", path)
