"""mech-review/spec-reversed: a test removed because the linked spec reverses it is one R2 confirm, not the fail."""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["EKIT_SCENARIO_DIR"], "fixtures"))
from mrlib import (branch, commit, expect, expect_fail_removed, expect_spec_confirm,  # noqa: E402
                   mr, new_repo, r2, r2_entries)

ONE_LINE = "def test_adds(): assert 1 + 1 == 2\ndef test_keeps(): assert 2 + 2 == 4\n"
ADDS_ONLY = "def test_adds(): assert 1 + 1 == 2\n"

# 1. python, one-line test, spec line in the head commit's body, issue linked as N and as #N
repo, base = new_repo("py", {"tests/test_m.py": ONE_LINE, "src/m.py": "X = 1\n"})
head = commit(repo, {"tests/test_m.py": ADDS_ONLY},
              "drop test_keeps\n\nThe issue says 2 + 2 is no longer 4.\nspec: #53 reverses test_keeps\n")
expect_spec_confirm("py N", r2(repo, base, head, "python", "--linked-issue", "53"), "test_keeps", 53, head)
expect_spec_confirm("py #N", r2(repo, base, head, "python", "--linked-issue", "#53"), "test_keeps", 53, head)
expect_spec_confirm("py N among others", r2(repo, base, head, "python", "--linked-issue", "61",
                                            "--linked-issue", "53"), "test_keeps", 53, head)
# the same range, issue not linked: the plain fail (the confirm is down to the link)
expect_fail_removed("py unlinked", r2(repo, base, head, "python"), "test_keeps")

# 2. spec line in an earlier commit of the range, later commits unrelated
branch(repo, "early", base)
c1 = commit(repo, {"tests/test_m.py": ADDS_ONLY}, "spec: #53 reverses test_keeps")
c2 = commit(repo, {"src/m.py": "X = 2\n"}, "unrelated follow-up")
expect_spec_confirm("earlier commit", r2(repo, base, c2, "python", "--linked-issue", "53"), "test_keeps", 53, c2)

# 3. two linked spec lines for the one test: one confirm, the lowest N
branch(repo, "two-lines", base)
h3 = commit(repo, {"tests/test_m.py": ADDS_ONLY},
            "drop\n\nspec: #61 reverses test_keeps\nspec: #53 reverses test_keeps\n")
expect_spec_confirm("two linked lines", r2(repo, base, h3, "python", "--linked-issue", "61",
                                           "--linked-issue", "53"), "test_keeps", 53, h3)

# 4. python class method: R2's name `TestCalc::test_keeps`
CLS = ("import unittest\n\n\nclass TestCalc(unittest.TestCase):\n"
       "    def test_adds(self):\n        self.assertEqual(1 + 1, 2)\n\n"
       "    def test_keeps(self):\n        self.assertEqual(2 + 2, 4)\n")
CLS_ADDS = CLS.split("\n    def test_keeps")[0] + "\n"
repo4, base4 = new_repo("pycls", {"tests/test_calc.py": CLS})
h4 = commit(repo4, {"tests/test_calc.py": CLS_ADDS}, "spec: #7 reverses TestCalc::test_keeps")
expect_spec_confirm("py class", r2(repo4, base4, h4, "python", "--linked-issue", "7"),
                    "TestCalc::test_keeps", 7, h4)

# 5. rust, one-line test fn
RS = "#[test]\nfn adds() { assert_eq!(1 + 1, 2); }\n#[test]\nfn keeps() { assert_eq!(2 + 2, 4); }\n"
repo5, base5 = new_repo("rs", {"tests/math.rs": RS})
h5 = commit(repo5, {"tests/math.rs": "#[test]\nfn adds() { assert_eq!(1 + 1, 2); }\n"},
            "spec: #53 reverses keeps")
expect_spec_confirm("rust one-line", r2(repo5, base5, h5, "rust", "--linked-issue", "53"), "keeps", 53, h5)
expect_fail_removed("rust unlinked", r2(repo5, base5, h5, "rust"), "keeps")

# 6. two tests removed: each one's own line makes each a confirm; an unnamed one stays a fail
THREE = ONE_LINE + "def test_more(): assert 3 == 3\n"
repo6, base6 = new_repo("py2", {"tests/test_m.py": THREE})
h6 = commit(repo6, {"tests/test_m.py": ADDS_ONLY},
            "drop two\n\nspec: #53 reverses test_keeps\nspec: #53 reverses test_more\n")
rc, data, out, err = r2(repo6, base6, h6, "python", "--linked-issue", "53")
es = r2_entries(data)
expect("two named exit", rc == 0, out + err)
expect("two named: two confirms, no fail", sorted(e["severity"] for e in es) == ["confirm", "confirm"], out)
branch(repo6, "one-named", base6)
h6b = commit(repo6, {"tests/test_m.py": ADDS_ONLY}, "drop two\n\nspec: #53 reverses test_keeps\n")
rc, data, out, err = r2(repo6, base6, h6b, "python", "--linked-issue", "53")
es = r2_entries(data)
expect("one named exit", rc == 1, out + err)
expect("one named: confirm for test_keeps", [e["severity"] for e in es if "`test_keeps`" in e["problem"]] == ["confirm"], out)
expect("one named: fail for test_more", [e["severity"] for e in es if "`test_more`" in e["problem"]] == ["fail"], out)

# 7. the spec line is no waiver: another cheat in the same range still fails
branch(repo, "plus-skip", base)
h7 = commit(repo, {"tests/test_m.py": "import pytest\n\n\n@pytest.mark.skip\ndef test_adds(): assert 1 + 1 == 2\n"},
            "spec: #53 reverses test_keeps")
rc, data, out, err = r2(repo, base, h7, "python", "--linked-issue", "53")
es = r2_entries(data)
expect("plus skip exit", rc == 1, out + err)
expect("plus skip: removal is confirm", any(e["severity"] == "confirm" and "`test_keeps`" in e["problem"] for e in es), out)
expect("plus skip: skip is fail", any(e["severity"] == "fail" and "test_adds" in e["problem"] for e in es), out)

# 8. `all` takes the flag too (R1/R4 toolchain absent here; R2 is what we read)
rc, data, out, err = mr("all", "--repo", repo, "--base", base, "--head", head, "--stack", "python",
                        "--test-paths", "tests/**", "--linked-issue", "#53", "--test-cmd", "ekit-no-such-toolchain")
expect("all not a usage error", rc != 2, err)
es = r2_entries(data)
expect("all: one R2 confirm", [e["severity"] for e in es] == ["confirm"] and "#53" in es[0]["problem"], out)

# 9. text format shows the confirm too
rc, _, out, err = r2(repo, base, head, "python", "--linked-issue", "53", "--format", "text")
expect("text exit", rc == 0, out + err)
expect("text names test and issue", "test_keeps" in out and "#53" in out and "confirm" in out, out)
print("spec-reversed ok")
