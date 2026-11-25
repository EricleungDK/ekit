"""mech-review/spec-reversed/misuse: a bad --linked-issue, or one on a subcommand that does not run R2, is a usage error."""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["EKIT_PARENT_DIR"], "fixtures"))
from mrlib import commit, expect, expect_spec_confirm, mr, new_repo, r2  # noqa: E402

repo, base = new_repo("py", {"tests/test_m.py": "def test_adds(): assert 1 + 1 == 2\ndef test_keeps(): assert 2 + 2 == 4\n",
                             "src/m.py": "X = 1\n"})
head = commit(repo, {"tests/test_m.py": "def test_adds(): assert 1 + 1 == 2\n", "src/m.py": "X = 2\n"},
              "spec: #53 reverses test_keeps")


def usage_error(label, res, *want):
    rc, _, out, err = res
    expect(label + " exit", rc == 2, f"want 2, got {rc}\n{out}{err}")
    expect(label + " empty stdout", out.strip() == "", out)
    for w in want:
        expect(label + " stderr", w in err, f"want {w!r} in {err!r}")


# bad values: not a number, zero, negative, signs, spaces, extra '#', non-ASCII digits, empty
for v in ["0", "#0", "-1", "abc", "", "#", "##53", "53x", "5 3", " 53", "+53", "53.0", "١٢", "５３"]:
    usage_error(f"value {v!r}", r2(repo, base, head, "python", "--linked-issue", v), "--linked-issue", repr(v))
# a bad value among good ones still stops the run
usage_error("bad among good", r2(repo, base, head, "python", "--linked-issue", "53", "--linked-issue", "x"),
            "--linked-issue")
# the flag with no value
usage_error("no value", r2(repo, base, head, "python", "--linked-issue"), "--linked-issue")

# subcommands that do not run R2
common = ["--repo", repo, "--base", base, "--head", head, "--stack", "python", "--linked-issue", "53"]
for sub in ["red", "mutants", "plan", "baseline", "merge"]:
    usage_error(sub, mr(sub, *common), "--linked-issue", "r2", "all")

# odd but valid: the same issue twice, a large N
expect_spec_confirm("same issue twice", r2(repo, base, head, "python", "--linked-issue", "53", "--linked-issue", "#53"),
                    "test_keeps", 53, head)
rc, data, out, err = r2(repo, base, head, "python", "--linked-issue", "999999")
expect("large N unlinked exit", rc == 1, out + err)
print("misuse ok")
