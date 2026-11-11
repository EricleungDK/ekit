"""R1 runs a PR's tests on the base's production code, and only test-path files are put there. A test in any other
file (a rust `#[cfg(test)]` mod beside the code) is not on the base's code, so R1 does not run it there."""
import hashlib
import os
import subprocess
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import engine

BASE_LIB = "pub fn div(a: i32, b: i32) -> Option<i32> { Some(a / b) }\n"
HEAD_LIB = """pub fn div(a: i32, b: i32) -> Option<i32> { if b == 0 { None } else { Some(a / b) } }

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_is_none() {
        assert_eq!(div(1, 0), None);
    }
}
"""
IN_TEST_PATHS = """#[test]
fn rejects_zero() {
    assert_eq!(fx::div(1, 0), None);
}
"""
PASSED = "test result: ok. 1 passed; 0 failed\n"
FAILED = "test result: FAILED. 0 passed; 1 failed\n"
NOT_THERE = "running 0 tests\n\ntest result: ok. 0 passed; 0 failed\n"
NO_BUILD = "error[E0425]: cannot find function `div_checked` in crate `fx`\nerror: could not compile `fx`\n"


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


class TestTestsOutsideTestPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        self.write("src/lib.rs", BASE_LIB)
        self.commit("base")
        self.on_base = []

    def write(self, path, text):
        os.makedirs(os.path.dirname(os.path.join(self.repo, path)), exist_ok=True)
        with open(os.path.join(self.repo, path), "w") as f:
            f.write(text)

    def commit(self, subject):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", subject)

    def cargo(self, argv, cwd):
        """What cargo prints for one named test: on the base's code the fix is missing and the test beside it is not there."""
        with open(os.path.join(cwd, "src", "lib.rs")) as f:
            fixed = "None" in f.read()
        if fixed:
            return 0, PASSED
        self.on_base.append(argv[-1])
        return {"rejects_zero": (101, FAILED), "pins_what_was_there": (0, PASSED),
                "needs_the_new_fn": (101, NO_BUILD)}.get(argv[-1], (0, NOT_THERE))

    def red(self):
        return engine.run(self.repo, "HEAD~1", "HEAD", "rust", ["tests/**"], which="red", head_branch="claude/fix",
                          runner=self.cargo)

    def test_a_test_beside_the_code_is_not_run_on_the_base_and_fails_nothing(self):
        self.write("src/lib.rs", HEAD_LIB)
        self.write("tests/it.rs", IN_TEST_PATHS)
        self.commit("fix")
        env = self.red()
        self.assertEqual(self.on_base, ["rejects_zero"])
        self.assertEqual(env["checks"]["R1"], {
            "status": "pass",
            "note": "1 of 1 new or changed test(s) fail on the base's production code; "
                    "1 in files outside test-paths: not run there"})
        self.assertEqual(env["checks"]["R4"], {"status": "pass", "note": "2 new or changed test(s) run 5x at head"})
        self.assertEqual(env["entries"], [])

    def test_with_every_test_in_a_test_path_the_note_is_the_count_alone(self):
        self.write("src/lib.rs", HEAD_LIB.split("\n#[cfg(test)]")[0])
        self.write("tests/it.rs", IN_TEST_PATHS)
        self.commit("fix")
        self.assertEqual(self.red()["checks"]["R1"], {
            "status": "pass", "note": "1 of 1 new or changed test(s) fail on the base's production code"})

    def test_a_test_that_does_not_build_on_the_base_is_counted_as_red(self):
        self.write("src/lib.rs", HEAD_LIB)
        self.write("tests/it.rs", IN_TEST_PATHS.replace("rejects_zero", "needs_the_new_fn"))
        self.commit("fix")
        env = self.red()
        self.assertEqual(env["checks"]["R1"], {
            "status": "pass",
            "note": "1 of 1 new or changed test(s) fail on the base's production code (1 compile-red); "
                    "1 in files outside test-paths: not run there"})
        self.assertEqual(env["entries"], [])

    def test_only_tests_beside_the_code_is_one_fail_that_names_the_way_out(self):
        self.write("src/lib.rs", HEAD_LIB)
        self.commit("fix")
        env = self.red()
        self.assertEqual(self.on_base, [])
        self.assertEqual(env["checks"]["R1"], {"status": "fail",
                                               "note": "0 of 1 new or changed test(s) are in a test-paths file"})
        self.assertEqual(env["entries"], [{
            "id": "R1-" + hashlib.sha1(b"R1src/lib.rsoutside-test-paths").hexdigest()[:8],
            "check": "R1", "class": "agent-fixable", "severity": "fail", "file": "src/lib.rs", "line": 8,
            "problem": "R1 cannot run this PR's 1 new or changed test(s) on the base's code: they are in files outside "
                       "test-paths (first: `src/lib.rs`), which the base has in its own version",
            "hint": "add a test in a test-paths file that fails without this PR's production change, through the "
                    "public interface; the tests beside the code can stay",
            "forbidden": "a production change no test catches"}])

    def test_a_guard_in_a_test_path_is_the_no_red_fail_and_is_named_by_its_own_file(self):
        self.write("src/lib.rs", HEAD_LIB)
        self.write("tests/it.rs", IN_TEST_PATHS.replace("rejects_zero", "pins_what_was_there"))
        self.commit("fix")
        env = self.red()
        self.assertEqual(self.on_base, ["pins_what_was_there"])
        self.assertEqual([(e["file"], e["line"], e["problem"]) for e in env["entries"]], [(
            "tests/it.rs", 2, "no new or changed test fails without this PR's production change: `pins_what_was_there` "
                              "pass on the base's code too")])
        self.assertEqual(env["checks"]["R1"]["note"], "0 of 1 new or changed test(s) fail on the base's production code; "
                                                      "1 in files outside test-paths: not run there")


if __name__ == "__main__":
    unittest.main()
