"""`parser-install` (#27's install step): the install argvs of the parser the base branch's adapter file declares.

The workflow's step runs them before the engine steps that read source. They come from the base's adapter file, the
copy r2 reads (ADR 0001), never the head's: a PR that edits `[parser]` changes nothing printed. A built-in stack, a
stack with no adapter file and a pattern adapter file print no step. Through cli.main in this process."""
import json
import os
import tempfile
import unittest

import _kit
from test_adapter_cli import BASE, MINI, Repo
from test_parser_cli import HOME_VAR, parser_toml

AD = ".ekit/adapters/mini.toml"


def read(path):
    with open(path) as f:
        return f.read()


def toml(**swap):
    """the parser-backed mini.toml, with `key = "old"` lines swapped for new values (load only: no stub installed)."""
    old = os.environ.pop(HOME_VAR, None)
    try:
        text = parser_toml()
    finally:
        if old is not None:
            os.environ[HOME_VAR] = old
    for key, value in swap.items():
        text = "\n".join(f'{key} = "{value}"' if line.startswith(f"{key} = ") else line for line in text.split("\n"))
    return text


def pip_steps(home, package="mini-facts", version="1.0.0"):
    prefix = f"{home}/pip/{package}/{version}"
    return [["python3", "-m", "venv", prefix], [f"{prefix}/bin/python", "-m", "pip", "install", f"{package}=={version}"]]


class ParserInstall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.join(tmp.name, "parsers")
        self.repo = Repo(os.path.join(tmp.name, "repo"))
        self.src = {"tests/calc.mini": BASE, "src/calc.mini": "fn add(a, b) { a + b }\n"}

    def run_cli(self, base, *extra, stack="mini", home=True):
        argv = ["parser-install", "--repo", self.repo.path, "--base", base, "--stack", stack]
        return _kit.run_cli(argv + (["--home", self.home] if home else []) + list(extra))

    def printed(self, base, *extra, **kw):
        r = self.run_cli(base, *extra, **kw)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return json.loads(r.stdout)

    def test_a_parser_backed_file_at_the_base_prints_its_pinned_install_steps(self):
        base = self.repo.commit({**self.src, AD: toml()}, "base")
        self.assertEqual(self.printed(base), {"stack": "mini", "adapter": AD, "steps": pip_steps(self.home),
                                              "program": f"{self.home}/pip/mini-facts/1.0.0/bin/mini-facts"})

    def test_each_installer_prints_its_own_steps(self):
        base = self.repo.commit({**self.src, AD: toml(installer="npm", package="@acme/mini-facts", version="2.1.0")},
                                "base")
        prefix = f"{self.home}/npm/@acme/mini-facts/2.1.0"
        self.assertEqual(self.printed(base)["steps"], [["npm", "install", "--no-save", "--prefix", prefix,
                                                         "@acme/mini-facts@2.1.0"]])

    def test_a_pr_that_changes_parser_does_not_change_the_printed_steps(self):
        base = self.repo.commit({**self.src, AD: toml()}, "base")
        want = self.printed(base)
        for swap in ({"version": "9.9.9"}, {"package": "evil-facts"}, {"installer": "gem"}):
            with self.subTest(swap=swap):
                self.repo.git("checkout", "-q", "--detach", base)
                head = self.repo.commit({AD: toml(**swap)}, "head")  # the head's copy is checked out: never read
                self.assertNotEqual(self.repo.git("show", f"{head}:{AD}"), self.repo.git("show", f"{base}:{AD}"))
                self.assertEqual(self.printed(base), want)

    def test_a_parser_the_pr_adds_installs_nothing(self):
        base = self.repo.commit(self.src, "base")
        self.repo.commit({AD: toml()}, "head")
        self.assertEqual(self.printed(base), {"stack": "mini", "adapter": None, "steps": [], "program": None})

    def test_a_pattern_adapter_file_prints_no_step(self):
        base = self.repo.commit({**self.src, AD: read(MINI)}, "base")
        self.assertEqual(self.printed(base), {"stack": "mini", "adapter": AD, "steps": [], "program": None})

    def test_a_built_in_stack_prints_no_step(self):
        base = self.repo.commit({"app.py": "x = 1\n"}, "base")
        self.assertEqual(self.printed(base, stack="python"),
                         {"stack": "python", "adapter": None, "steps": [], "program": None})

    def test_the_plan_entry_for_the_project_dir_names_the_file(self):
        plan = '[[stack]]\nname = "mini"\nfolder = "m"\nadapter = ".ekit/adapters/m.toml"\nstatus = "current"\n'
        base = self.repo.commit({"m/calc.mini": BASE, ".ekit/stack-plan.toml": plan, ".ekit/adapters/m.toml": toml(),
                                 "m/mini.json": "{}\n"}, "base")
        got = self.printed(base, "--project-dir", "m/")
        self.assertEqual((got["adapter"], got["steps"]), (".ekit/adapters/m.toml", pip_steps(self.home)))

    def test_the_home_defaults_to_the_env_var(self):
        base = self.repo.commit({**self.src, AD: toml()}, "base")
        old = os.environ.get(HOME_VAR)
        os.environ[HOME_VAR] = self.home + "-env"
        self.addCleanup(lambda: os.environ.__setitem__(HOME_VAR, old) if old is not None else os.environ.pop(HOME_VAR))
        self.assertEqual(self.printed(base, home=False)["steps"], pip_steps(self.home + "-env"))

    def test_malformed_input_is_a_clear_usage_error(self):
        base = self.repo.commit({**self.src, AD: toml(version="latest")}, "base")
        for argv, want in (((base,), f"mech-review: adapter file {AD}: parser.version: `latest`: want one pinned version for pip"),
                           (("no-such-ref",), "mech-review: unknown ref: no-such-ref"),
                           ((base, "--home", "rel/dir"), "mech-review: parser home `rel/dir`: want an absolute path")):
            with self.subTest(argv=argv):
                r = self.run_cli(*argv, home="--home" not in argv)
                self.assertEqual((r.returncode, r.stdout), (2, ""))
                self.assertTrue(r.stderr.startswith(want), r.stderr)
                self.assertNotIn("Traceback", r.stderr)

    def test_help_names_the_subcommand_and_says_it_reads_the_base(self):
        r = _kit.run_cli(["parser-install", "--help"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("usage: mech-review.py parser-install "), r.stdout)
        self.assertIn("install the parser the base branch's adapter file declares", " ".join(r.stdout.split()))

    def test_base_and_stack_are_required(self):
        for argv, flag in ((["--stack", "mini"], "--base"), (["--base", "HEAD"], "--stack")):
            with self.subTest(flag=flag):
                r = _kit.run_cli(["parser-install", "--repo", self.repo.path, *argv])
                self.assertEqual((r.returncode, r.stdout), (2, ""))
                self.assertIn(f"the following arguments are required: {flag}", r.stderr)

    def test_a_project_dir_outside_the_repo_is_refused(self):
        base = self.repo.commit(self.src, "base")
        r = self.run_cli(base, "--project-dir", "../x")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("want a directory under the repo root", r.stderr)
        self.assertTrue(r.stderr.startswith("usage: mech-review.py parser-install "), r.stderr)


if __name__ == "__main__":
    unittest.main()
