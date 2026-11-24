"""`{module}` in [mutation.tool].mutate (#22): a changed file under one of module_roots, as its dotted name (PIT's class
name: src/main/java/com/x/Calc.java -> com.x.Calc). Load validation on dicts, module_name, and `mutants` through
cli.main with the stub tool of test_adapter_mutation_cli (the argv it gets, and n/a for a file under no root). Also
controls.json's `test-paths` for R0's runtime fixtures (a project whose tests sit outside tests/)."""
import copy
import json
import os
import tempfile
import unittest

import _kit
from scripts.mech_review import mutation_tool, r0, r0_runtime
from scripts.mech_review.adapter_file import AdapterFileError, parse
from test_adapter_mutation_cli import Case, adapter_text
from test_adapter_mutation_file import BASE, TOOL

PIT = dict(TOOL, args=["-DtargetClasses={mutate}"], mutate="{module},{module}$*", module_roots=["src/main/java"])


def with_tool(**kv):
    d = copy.deepcopy(BASE)
    t = dict(copy.deepcopy(PIT), **kv)
    d["mutation"] = {"tool": {k: v for k, v in t.items() if v is not None}}
    return d


class ModuleValidation(unittest.TestCase):
    def err(self, data):
        with self.assertRaises(AdapterFileError) as cm:
            parse(data)
        return str(cm.exception)

    def test_a_valid_module_tool_loads(self):
        self.assertEqual(parse(with_tool()).mutation_tool["module_roots"], ["src/main/java"])

    def test_module_needs_its_roots_and_the_roots_need_module(self):
        self.assertEqual(self.err(with_tool(module_roots=None)),
                         "mutation.tool.module_roots: missing: `{module}` and `{package}` are a file's dotted name under "
                         "one of these dirs")
        self.assertEqual(self.err(with_tool(mutate="{package}*", module_roots=None)),
                         "mutation.tool.module_roots: missing: `{module}` and `{package}` are a file's dotted name under "
                         "one of these dirs")
        self.assertEqual(parse(with_tool(mutate="{package}*")).mutation_tool["mutate"], "{package}*")
        self.assertEqual(self.err(with_tool(mutate="{first}")),
                         "mutation.tool.mutate: no `{file}`, `{module}` or `{package}`: a range names its file")
        self.assertEqual(self.err(with_tool(mutate="{file}")),
                         "mutation.tool.module_roots: never used: mutate has no `{module}` or `{package}`")
        self.assertEqual(self.err(with_tool(args=["run"], mutate=None)),
                         "mutation.tool.module_roots: never used: no mutate has `{module}` or `{package}`")
        self.assertEqual(self.err(with_tool(module_roots=[])), "mutation.tool.module_roots: want at least one entry")

    def test_each_root_is_a_dir_under_the_project_dir(self):
        for bad in ("/src", "../src", "src/", "src/./java", "src\\java"):
            with self.subTest(bad):
                self.assertIn("mutation.tool.module_roots[0]: ", self.err(with_tool(module_roots=[bad])))

    def test_module_name(self):
        t = {"module_roots": ["src/main/java", "gen"]}
        self.assertEqual(mutation_tool.module_name(t, "src/main/java/com/x/Calc.java"), "com.x.Calc")
        self.assertEqual(mutation_tool.module_name(t, "gen/A.kt"), "A")
        self.assertEqual(mutation_tool.module_name(t, "src/main/javax/B.java"), "")
        self.assertEqual(mutation_tool.module_name(t, "other/B.java"), "")
        self.assertIsNone(mutation_tool.module_name({}, "src/main/java/B.java"))


PIT_TOML = '''
[mutation.tool]
name = "pit"
command = "mvn"
args = ["pit", "-DtargetClasses={mutate}"]
mutate = "{module},{module}$*"
module_roots = ["src/main/java", "gen"]
report = "target/pit-reports/mutations.xml"
format = "pit-xml"
os = ["linux", "macos", "windows"]
'''
JAVA = "src/main/java/com/example/Calc.java"
SRC = "\n".join(f"// {n}" for n in range(1, 15)) + "\n"


class ModuleRun(Case):
    def adapter_java(self):
        return self.adapter(adapter_text(PIT_TOML, '[".mini", ".java"]'))

    def test_the_changed_classes_are_passed_once_each(self):
        self.pr(base={"mini.json": "{}", JAVA: SRC, "src/main/java/Top.java": SRC, "tests/calc.mini": "\n"},
                head={JAVA: SRC.replace("// 5\n", "int a;\n").replace("// 9\n", "int b;\n"),
                      "src/main/java/Top.java": SRC.replace("// 2\n", "int c;\n")})
        r, env = self.cli("mutants", self.adapter_java(),
                          env=self.report("mutations.xml", "target/pit-reports/mutations.xml"))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("| pit -DtargetClasses=Top,Top$*,com.example.Calc,com.example.Calc$*\n", self.calls())
        self.assertEqual([e["line"] for e in env["entries"]], [5, 9])

    def test_a_changed_file_under_no_root_is_left_out_and_named_the_rest_still_runs(self):
        """review round 1, B1: a stray tools/Stray.java made R3 n/a (env); the build compiles no such file, so it is
        not mutated, it is named, and the changed classes keep their MISSED."""
        other = "tools/Stray.java"
        self.pr(base={"mini.json": "{}", JAVA: SRC, other: SRC, "tests/calc.mini": "\n"},
                head={JAVA: SRC.replace("// 5\n", "int a;\n").replace("// 9\n", "int b;\n"),
                      other: SRC.replace("// 5\n", "x\n")})
        r, env = self.cli("mutants", self.adapter_java(),
                          env=self.report("mutations.xml", "target/pit-reports/mutations.xml"))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual([(e["file"], e["line"]) for e in env["entries"]], [(JAVA, 5), (JAVA, 9)])
        self.assertIn("| pit -DtargetClasses=com.example.Calc,com.example.Calc$*\n", self.calls())
        self.assertEqual(env["checks"]["R3"]["status"], "fail")
        self.assertIn(f"; not mutated: {other} (under none of mutation.tool.module_roots: src/main/java, gen)",
                      env["checks"]["R3"]["note"])
        self.assertNotIn("(env)", env["checks"]["R3"]["note"])

    def test_only_changed_files_under_no_root_is_a_pass_naming_them_that_runs_nothing(self):
        other = "src/it/java/Calc.java"
        self.pr(base={"mini.json": "{}", other: SRC, "tests/calc.mini": "\n"}, head={other: SRC.replace("// 5\n", "x\n")})
        r, env = self.cli("mutants", self.adapter_java())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(env["checks"]["R3"], {
            "status": "pass", "note": f"0 mutants in the diff; not mutated: {other} (under none of "
                                      "mutation.tool.module_roots: src/main/java, gen)", "tested": 0, "total": 0})
        self.assertNotIn("| pit", self.calls())

    def test_package_is_the_dotted_dir_of_each_changed_file(self):
        """review round 1, S6: `{package}*` reaches a second top-level class in a changed file (Helper in Calc.java)."""
        self.pr(base={"mini.json": "{}", JAVA: SRC, "src/main/java/Top.java": SRC, "tests/calc.mini": "\n"},
                head={JAVA: SRC.replace("// 5\n", "int a;\n"), "src/main/java/Top.java": SRC.replace("// 2\n", "c\n")})
        path = self.adapter(adapter_text(PIT_TOML.replace('mutate = "{module},{module}$*"', 'mutate = "{package}*"'),
                                         '[".mini", ".java"]'))
        self.cli("mutants", path, env=self.report("mutations.xml", "target/pit-reports/mutations.xml"))
        self.assertIn("| pit -DtargetClasses=*,com.example.*\n", self.calls())


class RuntimeTestPaths(unittest.TestCase):
    def runtime(self, controls):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "runtime"))
        with open(os.path.join(tmp.name, "runtime", "controls.json"), "w") as f:
            f.write(json.dumps(controls))
        return tmp.name

    def test_controls_json_names_the_fixture_projects_test_paths(self):
        d = self.runtime({"test-paths": ["src/test/**", "it/**"]})
        rt = r0_runtime.load_runtime(d)
        self.assertEqual((rt.globs, rt.where), (("src/test/**", "it/**"), os.path.join(d, "runtime")))

    def test_without_test_paths_the_tests_sit_under_tests(self):
        self.assertEqual(r0_runtime.load_runtime(self.runtime({})).globs, ("tests/**",))
        self.assertEqual(r0_runtime.load_runtime(self.runtime([])).globs, ("tests/**",))

    def test_test_paths_that_are_no_list_of_globs_are_a_fixture_error(self):
        for bad in ([], "src/**", [""], [1], None):
            with self.subTest(bad):
                d = self.runtime({"test-paths": bad})
                with self.assertRaises(r0.FixtureError) as cm:
                    r0_runtime.load_runtime(d)
                self.assertEqual(str(cm.exception), f"R0 runtime fixture {os.path.join(d, 'runtime', 'controls.json')}: "
                                                    '`test-paths`: want a list of globs, such as ["src/test/**"]')


if __name__ == "__main__":
    unittest.main()
