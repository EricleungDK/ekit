"""mech-review/spec-reversed/no-link: a removal with no spec link keeps the R2 fail."""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "mrlib", os.path.join(os.environ["EKIT_PARENT_DIR"], "fixtures", "mrlib.py"))
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
branch = lib.branch
commit = lib.commit
expect = lib.expect
expect_fail_removed = lib.expect_fail_removed
new_repo = lib.new_repo
r2 = lib.r2
r2_entries = lib.r2_entries
ONE_LINE = "def test_adds(): assert 1 + 1 == 2\ndef test_keeps(): assert 2 + 2 == 4\n"
ADDS_ONLY = "def test_adds(): assert 1 + 1 == 2\n"
repo, base = new_repo("py", {"tests/test_m.py": ONE_LINE, "src/m.py": "X = 1\n"})


def case(label, msg, *flags, files=None, test="test_keeps"):
    branch(repo, label.replace(" ", "-"), base)
    head = commit(repo, files or {"tests/test_m.py": ADDS_ONLY}, msg)
    expect_fail_removed(label, r2(repo, base, head, "python", *flags), test)


# C2: no spec line at all
case("no spec line", "drop test_keeps\n\nthe spec changed", "--linked-issue", "53")
# C2: spec line whose issue is not linked
case("unlinked issue", "spec: #53 reverses test_keeps", "--linked-issue", "61")
case("unlinked prefix issue", "spec: #5 reverses test_keeps", "--linked-issue", "53")
# C2: spec line naming another test (one still there, one that never existed, a near name)
case("names another test", "spec: #53 reverses test_adds", "--linked-issue", "53")
case("names unknown test", "spec: #53 reverses test_gone", "--linked-issue", "53")
case("names a prefix", "spec: #53 reverses test_keep", "--linked-issue", "53")
case("names a longer name", "spec: #53 reverses test_keeps_more", "--linked-issue", "53")
# C2: no --linked-issue at all
case("no flag", "spec: #53 reverses test_keeps")
# spec line in the files, not a commit message
case("line in a file, not a commit", "drop", "--linked-issue", "53",
     files={"tests/test_m.py": ADDS_ONLY, "NOTES.md": "spec: #53 reverses test_keeps\n"})

# a spec line in a commit outside base..head (already on base) does not count
repo2, b0 = new_repo("py-old", {"tests/test_m.py": ONE_LINE})
base2 = commit(repo2, {"src/m.py": "X = 1\n"}, "spec: #53 reverses test_keeps")
head2 = commit(repo2, {"tests/test_m.py": ADDS_ONLY}, "drop test_keeps")
expect_fail_removed("line before the range", r2(repo2, base2, head2, "python", "--linked-issue", "53"), "test_keeps")

# python class method named bare (not R2's `TestCalc::test_keeps`)
CLS = ("import unittest\n\n\nclass TestCalc(unittest.TestCase):\n"
       "    def test_adds(self):\n        self.assertEqual(1 + 1, 2)\n\n"
       "    def test_keeps(self):\n        self.assertEqual(2 + 2, 4)\n")
repo3, base3 = new_repo("pycls", {"tests/test_calc.py": CLS})
head3 = commit(repo3, {"tests/test_calc.py": CLS.split("\n    def test_keeps")[0] + "\n"},
               "spec: #7 reverses test_keeps")
expect_fail_removed("bare method name", r2(repo3, base3, head3, "python", "--linked-issue", "7"),
                    "TestCalc::test_keeps")

# one name removed from several files: the fail stays
repo4, base4 = new_repo("py-two-files", {"tests/test_a.py": ONE_LINE, "tests/test_b.py": ONE_LINE})
head4 = commit(repo4, {"tests/test_a.py": ADDS_ONLY, "tests/test_b.py": ADDS_ONLY}, "spec: #53 reverses test_keeps")
rc, data, out, err = r2(repo4, base4, head4, "python", "--linked-issue", "53")
es = r2_entries(data)
expect("several files exit", rc == 1, out + err)
expect("several files: no confirm", not any(e["severity"] == "confirm" for e in es), out)
expect("several files: a fail per file", sorted(e["file"] for e in es if e["severity"] == "fail")
       == ["tests/test_a.py", "tests/test_b.py"], out)

# rust: unlinked and another name
RS = "#[test]\nfn adds() { assert_eq!(1 + 1, 2); }\n#[test]\nfn keeps() { assert_eq!(2 + 2, 4); }\n"
repo5, base5 = new_repo("rs", {"tests/math.rs": RS})
head5 = commit(repo5, {"tests/math.rs": "#[test]\nfn adds() { assert_eq!(1 + 1, 2); }\n"}, "spec: #53 reverses adds")
expect_fail_removed("rust another name", r2(repo5, base5, head5, "rust", "--linked-issue", "53"), "keeps")
expect_fail_removed("rust no flag", r2(repo5, base5, head5, "rust"), "keeps")
print("no-link ok")
