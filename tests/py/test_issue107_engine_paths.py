"""#107 B5: engine paths with an adapter file. A `mutants` run with an adapter file never reaches the built-in R3 path
(mutants.run and its tools); clearing a declared report path (or a runner's config file) never removes a link the
engine made for [run].links, and a file whose report or config file lies at or under such a link (or holds one) is a
named load error. Through cli.main in this process (the mutation-tool fixture of test_adapter_mutation_cli), with the
engine's own entry points and _clear_path beside it."""
import os
import unittest
from unittest import mock

import _kit
from scripts.mech_review import adapter_file, engine, gitio, mutants, mutation_tool
from scripts.mech_review.gitio import Review, merge_base
from test_adapter_mutation_cli import ELEMENTS, Case, adapter_text
from test_adapter_run import MINI_RUN

ELEMENTS_REPORT = 'report = "out/report.json"'


def built_in_reached(*_a, **_k):
    raise AssertionError("an adapter-file mutants run reached the built-in R3 path")


def no_built_in():
    """mutants.run, mutants.baseline and every built-in tool fail the test when called."""
    patches = [mock.patch.object(mutants, name, built_in_reached) for name in ("run", "baseline")]
    for tool in mutants.TOOLS.values():
        patches += [mock.patch.object(tool, name, built_in_reached) for name in ("check", "baseline")]
    return patches


class NeverTheBuiltIn(Case):
    def setUp(self):
        super().setUp()
        for p in no_built_in():
            p.start()
            self.addCleanup(p.stop)

    def test_an_adapter_file_mutants_run_through_cli_main_is_the_declared_tools(self):
        self.pr()
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"STUB_OUT": "boom\n", "STUB_RC": "2"})
        self.assertEqual((r.returncode, env["checks"]["R3"]["note"]),
                         (1, "mut ran and wrote no report (out/report.json): mutants not read: boom"), r.stderr)

    def test_a_file_named_like_a_built_in_with_a_tool_runs_its_tool_never_the_built_ins(self):
        ts = adapter_text(ELEMENTS, extensions='[".ts"]').replace('name = "mini"', 'name = "ts"', 1)
        self.pr(base={"package.json": "{}", "mini.json": "{}", "src/calc.ts": "export const a = 1\n"},
                head={"src/calc.ts": "export const a = 2\n"})
        with mock.patch.dict(os.environ, dict(self.env, STUB_OUT="boom\n", STUB_RC="2")):
            r = _kit.run_cli(["mutants", "--repo", self.repo, "--base", self.base, "--head", self.head, "--stack", "ts",
                              "--test-paths", "tests/**", "--adapter", self.adapter(ts)])
        self.assertIn("mut ran and wrote no report", r.stdout, r.stderr)

    def test_engine_run_with_an_adapter_file_runs_its_declared_tool(self):
        self.pr()
        adapter = adapter_file.load(self.adapter(adapter_text(ELEMENTS)))
        with mock.patch.dict(os.environ, dict(self.env, STUB_OUT="boom\n", STUB_RC="2")):
            env = engine.run(self.repo, self.base, self.head, "mini", ["tests/**"], which="mutants", adapter=adapter)
        self.assertEqual(env["checks"]["R3"]["note"],
                         "mut ran and wrote no report (out/report.json): mutants not read: boom")
        self.assertEqual([e["check"] for e in env["entries"]], ["R3"])


class TheBuiltInRefusesAFile(Case):
    def test_mutants_run_and_baseline_refuse_an_adapter_file_loudly(self):
        self.pr()
        _, head, mb = merge_base(self.repo, self.base, self.head)
        ts = adapter_text(ELEMENTS, extensions='[".mini"]').replace('name = "mini"', 'name = "ts"', 1)
        rv = Review(self.repo, mb, head, adapter_file.load(self.adapter(ts)), ["tests/**"], ".")
        for fn in (mutants.run, mutants.baseline):
            with self.subTest(fn=fn.__name__):
                with self.assertRaisesRegex(ValueError, "adapter file .*: R3 runs its mutation tool "
                                                        r"\(mutation_tool\), never the built-in ts tool"):
                    fn(rv, runner=built_in_reached)
        self.assertEqual(self.calls(), "")


def linked(links, report="out/report.json", runners=""):
    """mini.toml with the declared tool, a [run] whose links are links, and the tool's report path."""
    run = MINI_RUN.replace('[run]\n', f"[run]\nlinks = {links!r}\n".replace("'", '"'), 1)
    return adapter_text(ELEMENTS.replace(ELEMENTS_REPORT, f'report = "{report}"') + runners) + run


RUNNERS = '''
[[run.runner]]
name = "fast"
command = "minitest --fast"
when = { file = "mini.json" }
'''
CONFIG = '''
[mutation.tool.runners.fast]
config_file = "{cf}"
config = '{{"a": 1}}'
'''


class ReportUnderALink(Case):
    def load_error(self, text):
        self.pr()
        path = self.adapter(text)
        r, env = self.cli("mutants", path)
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        head = f"mech-review: adapter file {path}: "
        self.assertTrue(r.stderr.startswith(head), r.stderr)
        return "mech-review: " + r.stderr[len(head):].strip()

    def test_a_report_path_under_an_engine_link_is_a_named_error(self):
        for links, report, link in ((["node_modules"], "node_modules/.cache/report.json", "node_modules"),
                                    (["node_modules"], "node_modules", "node_modules"),
                                    (["./node_modules"], "node_modules/r.json", "./node_modules"),
                                    (["node_modules/"], "node_modules/r.json", "node_modules/"),
                                    (["a//b"], "a/b/r.json", "a//b"),
                                    (["deps", "Node_Modules"], "node_modules/r.json", "Node_Modules"),
                                    (["out/deps"], "out", "out/deps"),
                                    (["caf\u00e9"], "cafe\u0301/r.json", "caf\u00e9"),  # NFC link, NFD report
                                    (["cafe\u0301"], "caf\u00e9", "cafe\u0301")):
            with self.subTest(links=links, report=report):
                self.assertEqual(self.load_error(linked(links, report)), (
                    f"mech-review: mutation.tool.report: `{report}` and run.links `{link}` overlap: clearing the "
                    "report path would remove the link the engine makes there; write the report elsewhere"))

    def test_a_runners_config_file_under_an_engine_link_is_a_named_error(self):
        text = linked(["cfg"], runners=CONFIG.format(cf="cfg/mut.json")).replace(
            '[mutation.tool]', '[mutation]\nconfig_files = ["cfg/mut.json"]\nconfig_name = "mut config"\n\n'
            '[mutation.tool]', 1) + RUNNERS
        self.assertEqual(self.load_error(text), (
            "mech-review: mutation.tool.runners.fast.config_file: `cfg/mut.json` and run.links `cfg` overlap: clearing "
            "the config file would remove the link the engine makes there; write it elsewhere"))

    def test_paths_beside_a_link_load(self):
        for links, report in ((["node_modules"], "node_modules_report.json"), (["out/deps"], "out/report.json"),
                              (["."], "out/report.json"), ([], "out/report.json")):
            with self.subTest(links=links, report=report):
                adapter_file.load(self.adapter(linked(links, report)))


class TheRunKeepsEngineLinks(Case):
    def test_a_run_whose_report_path_meets_a_link_the_engine_made_fails_and_keeps_the_link(self):
        """the load check reads paths; the run checks the file itself: a file the load check let through (here: its
        links changed after load) still never has the engine's link removed."""
        self.pr(base={"mini.json": "{}", "src/calc.mini": "fn add(a, b) {\n  a+b\n}\n", "tests/calc.mini": "x\n",
                      ".gitignore": "out/\n"})
        os.makedirs(os.path.join(self.repo, "out"))
        with open(os.path.join(self.repo, "out", "keep.txt"), "w") as f:
            f.write("the caller's\n")
        adapter = adapter_file.load(self.adapter(linked(["deps"])))
        adapter.run["links"] = ["out"]
        _, head, mb = merge_base(self.repo, self.base, self.head)
        rv = Review(self.repo, mb, head, adapter, ["tests/**"], ".")
        with mock.patch.dict(os.environ, dict(self.env, **self.report("elements.json", "out/report.json"))):
            check, ents = mutation_tool.run(rv)
        problem = ("mut report out/report.json: the checkout's path cannot be cleared (it goes through `out`, a link "
                   "the engine made for run.links): mutants not run")
        self.assertEqual((check["status"], check["note"]), ("fail", problem))
        self.assertEqual([e["problem"] for e in ents], [problem])
        self.assertEqual(os.listdir(os.path.join(self.repo, "out")), ["keep.txt"])


class NoLinkThroughALink(Case):
    """#107 review F5: worktree_setup makes no link whose parent dir is reached through a link in the checkout (the
    PR's `vendor -> build`): such a link would land where the load check did not look (under `build`, the report path,
    which clearing removes whole). A named error, never a link made there."""

    def setUp(self):
        super().setUp()
        self.pr()
        os.symlink("build", os.path.join(self.repo, "vendor"))
        os.makedirs(os.path.join(self.repo, "build"))
        with open(os.path.join(self.repo, "build", ".keep"), "w") as f:
            f.write("")
        with open(os.path.join(self.repo, ".gitignore"), "w") as f:
            f.write("node_modules/\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "vendor")
        self.head = self.git("rev-parse", "HEAD")
        os.makedirs(os.path.join(self.repo, "build", "node_modules"))  # the caller's install, untracked
        self.text = linked(["vendor/node_modules"], report="build")

    def test_mutants_stops_naming_the_link(self):  # R1 and R4 make their worktrees' links the same way
        r, _ = self.cli("mutants", self.adapter(self.text))
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        self.assertEqual(r.stderr.strip(), "mech-review: run.links `vendor/node_modules`: `vendor` in the checkout "
                                           "is a link: the engine makes no link through it")
        self.assertTrue(os.path.isdir(os.path.join(self.repo, "build", "node_modules")))

    def test_the_load_check_passes_this_layout(self):
        adapter_file.load(self.adapter(self.text))


class LinkParents(unittest.TestCase):
    """#107 review N2, N4: only the dirs of a link's own path below the project dir count; a project dir reached through
    a link (`app -> packages/app`) is the caller's choice, and both the report and the links are relative to it."""

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo, self.wt = os.path.join(tmp.name, "repo"), os.path.join(tmp.name, "wt")
        for top in (self.repo, self.wt):
            os.makedirs(os.path.join(top, "packages", "app", "a", "real"))
            os.symlink(os.path.join("packages", "app"), os.path.join(top, "app"))
        os.makedirs(os.path.join(self.repo, "packages", "app", "node_modules"))
        os.makedirs(os.path.join(self.repo, "packages", "app", "a", "real", "node_modules"))

    def setup_links(self, links):
        path = os.path.join(os.path.dirname(self.wt), "mini.toml")
        with open(path, "w") as f:
            f.write(linked(links))
        return adapter_file.load(path).worktree_setup(self.repo, self.wt, "app")

    def test_a_project_dir_reached_through_a_link_gets_its_links(self):
        self.assertEqual(self.setup_links(["node_modules"]), [os.path.join(self.wt, "app", "node_modules")])
        self.assertTrue(os.path.islink(os.path.join(self.wt, "packages", "app", "node_modules")))

    def test_a_link_under_a_nested_linked_dir_is_refused_naming_it(self):
        os.symlink("real", os.path.join(self.wt, "packages", "app", "a", "vendor"))
        os.symlink("real", os.path.join(self.repo, "packages", "app", "a", "vendor"))
        with self.assertRaises(gitio.Die) as cm:
            self.setup_links(["a/vendor/node_modules"])
        self.assertEqual(str(cm.exception), "run.links `a/vendor/node_modules`: `a/vendor` in the checkout is a link: "
                                            "the engine makes no link through it")
        self.assertFalse(os.path.lexists(os.path.join(self.wt, "packages", "app", "a", "real", "node_modules")))


class ClearPathKeepsEngineLinks(unittest.TestCase):
    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wt = os.path.join(tmp.name, "wt")
        self.deps = os.path.join(tmp.name, "deps")
        os.makedirs(os.path.join(self.deps, ".cache"))
        os.makedirs(self.wt)
        self.link = os.path.join(self.wt, "node_modules")
        os.symlink(self.deps, self.link)

    def test_a_path_through_a_link_the_engine_made_is_refused_and_the_link_stays(self):
        for rel in ("node_modules/.cache/report.json", "node_modules"):
            with self.subTest(rel=rel):
                why = mutation_tool._clear_path(self.wt, self.wt, rel, keep=[self.link])
                self.assertEqual(why, "it goes through `node_modules`, a link the engine made for run.links")
                self.assertTrue(os.path.islink(self.link))
                self.assertTrue(os.path.isdir(os.path.join(self.deps, ".cache")))

    def test_a_link_the_pr_put_on_the_path_is_still_removed(self):
        os.symlink(self.deps, os.path.join(self.wt, "out"))
        self.assertIsNone(mutation_tool._clear_path(self.wt, self.wt, "out/report.json", keep=[self.link]))
        self.assertFalse(os.path.lexists(os.path.join(self.wt, "out")))
        self.assertTrue(os.path.islink(self.link))


if __name__ == "__main__":
    unittest.main()
