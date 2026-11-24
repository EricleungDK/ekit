"""The built-in adapters' listing (#21, R0's census), in process and with no toolchain: the argv each one lists its
runner's tests with, how it reads the listing, and rust's names by module path. tests/py/test_r0_runtime_builtins.py
runs the same against real cargo and pytest where they are installed; these hold on every machine."""
import unittest

import _kit  # noqa: F401 - the repo root on sys.path
from scripts.mech_review import stack

RUST, PY, TS = stack.RustAdapter(), stack.PythonAdapter(), stack.TsAdapter()


class Rust(unittest.TestCase):
    def test_list_argv(self):
        self.assertEqual(RUST.list_argv("cargo test --workspace"), ["cargo", "test", "--workspace", "--", "--list"])

    def test_listed_keeps_tests_and_leaves_out_doc_tests_and_benchmarks(self):
        out = "tests::adds: test\nm::inner: test\nsrc/lib.rs - add (line 2): test\nbench_x: benchmark\n\n2 tests\n"
        self.assertEqual(RUST.listed(0, out, "."), [(None, "tests::adds"), (None, "m::inner")])

    def test_a_listing_that_did_not_build_reads_none(self):
        self.assertIsNone(RUST.listed(101, "tests::adds: test\n", "."))

    def test_listed_name_is_the_module_path_from_the_file(self):
        cases = {"src/lib.rs": "tests::x", "src/main.rs": "tests::x", "src/bin/tool.rs": "tests::x",
                 "src/foo.rs": "foo::tests::x", "src/a/b.rs": "a::b::tests::x", "src/a/mod.rs": "a::tests::x",
                 "tests/it.rs": "tests::x", "tests/t/main.rs": "tests::x", "tests/t/sub.rs": "sub::tests::x",
                 "tests/t/sub/mod.rs": "sub::tests::x", "benches/b.rs": "tests::x", "build.rs": "tests::x",
                 "README": "tests::x", "src/a/module": "tests::x", "tests": "tests::x"}
        self.assertEqual({p: RUST.listed_name(p, "tests::x") for p in cases}, cases)


class Python(unittest.TestCase):
    def test_list_argv_clears_addopts_and_the_cache(self):
        self.assertEqual(PY.list_argv("python3 -m pytest"),
                         ["python3", "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", "-p", "no:cacheprovider"])

    def test_a_unittest_command_has_no_listing_and_says_why(self):
        self.assertIsNone(PY.list_argv("python3 -m unittest"))
        self.assertEqual(PY.no_listing("python3 -m unittest"),
                         "a unittest command lists no tests by name without running them: no census")

    def test_listed_reads_node_ids_once_and_exit_5_as_no_tests(self):
        out = "tests/test_a.py::test_x\ntests/test_a.py::test_p[1]\ntests/test_a.py::test_p[2]\ntests/test_a.py::C::test_m\n"
        self.assertEqual(PY.listed(0, out, "."), [("tests/test_a.py", "test_x"), ("tests/test_a.py", "test_p"),
                                                   ("tests/test_a.py", "C::test_m")])
        self.assertEqual(PY.listed(5, "no tests ran\n", "."), [])
        for rc in (1, 2, 4, 6):
            self.assertIsNone(PY.listed(rc, out, "."), rc)


class Ts(unittest.TestCase):
    def test_list_argv_puts_list_after_the_vitest_word_and_drops_run(self):
        self.assertEqual(TS.list_argv("node_modules/.bin/vitest run"), ["node_modules/.bin/vitest", "list"])
        self.assertEqual(TS.list_argv("npx vitest run --silent"), ["npx", "vitest", "list", "--silent"])
        self.assertEqual(TS.list_argv("npx vitest --silent run"), ["npx", "vitest", "list", "--silent"])
        self.assertEqual(TS.list_argv("env X=1 node_modules/.bin/vitest"), ["env", "X=1", "node_modules/.bin/vitest",
                                                                            "list"])

    def test_a_command_with_no_vitest_word_lists_at_its_end(self):
        self.assertEqual(TS.list_argv("bin/runner --flag run"), ["bin/runner", "--flag", "run", "list"])

    def test_jest_has_no_listing_and_says_why(self):
        self.assertIsNone(TS.list_argv("node_modules/.bin/jest"))
        self.assertEqual(TS.no_listing("node_modules/.bin/jest"),
                         "jest lists test files, not tests (`--listTests`): no census")

    def test_listed_reads_file_and_name(self):
        out = " RUN  v3\ntests/a.test.ts > Calc > adds\ntests/b.test.tsx > top\nnot a test line\n"
        self.assertEqual(TS.listed(0, out, "."), [("tests/a.test.ts", "Calc > adds"), ("tests/b.test.tsx", "top")])
        self.assertIsNone(TS.listed(1, out, "."))


if __name__ == "__main__":
    unittest.main()
