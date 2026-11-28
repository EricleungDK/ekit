"""#107 review N1, N8: the python stack has two line numberings, ast's (and mutmut's: LF, CRLF and a lone CR each end
a line) and git's diff (LF only). Every place a python line meets the diff's lines converts it to git's first, so a
file with lone CRs or CRLF ends is judged on the lines the PR changed. R3 through mutants.run with a scripted mutmut
(in process, as test_mutmut_run), R2 through cli.main r2."""
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants, scan
from test_adapter_cli import Repo, r2
from test_mutmut_run import SUB1, SUB2, DiffOfSub, FakeMutmut, git

BASE = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
HEAD = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    c = a - b\n    return c\n"
HEADER = "# header" + "\r" * 10 + "\n"


def crlf(t):
    return t.replace("\n", "\r\n")


def mixed(t):  # LF, CRLF and a lone CR in turn, line by line
    out = t.split("\n")
    return "".join(ln + ("\n", "\r\n", "\r")[i % 3] for i, ln in enumerate(out[:-1])) + out[-1]


def git_line(text, needle):
    """the LF line (git's) that holds needle"""
    return text[:text.index(needle)].count("\n") + 1


class PythonR3Lines(DiffOfSub):
    def write(self, base, head):
        """the repo DiffOfSub made, its two commits replaced by base and head"""
        git(self.repo, "reset", "-q", "--hard", "HEAD~1")
        with open(os.path.join(self.repo, "calc.py"), "w", newline="") as f:
            f.write(base)
        git(self.repo, "commit", "-q", "--amend", "-am", "base")
        with open(os.path.join(self.repo, "calc.py"), "w", newline="") as f:
            f.write(head)
        git(self.repo, "commit", "-q", "-am", "head")

    def missed(self, base, head):
        self.write(base, head)
        fake = FakeMutmut({SUB1: "survived", SUB2: "killed"})
        fake.unmutated = head.replace("\r\n", "\n").replace("\r", "\n")  # the fake reads calc.py in text mode
        check, entries, _ = self.r3(fake)
        return check, [(e["file"], e["line"], e["problem"]) for e in entries]

    def test_the_mutant_on_the_changed_line_is_in_the_diff_and_its_missed_is_reported(self):
        for label, base, head in (
                ("plain", BASE, HEAD),
                ("lone CRs before the change", HEADER + BASE, HEADER + HEAD),
                ("CRLF", crlf(BASE), crlf(HEAD)),
                ("mixed", mixed(BASE), mixed(HEAD)),
                ("lone CRs inside the changed function", BASE.replace("\n    return a - b", "\r\r    return a - b"),
                 HEAD.replace("    c = a - b\n", "\r\r    c = a - b\n"))):
            with self.subTest(label):
                line = git_line(head, "c = a - b")
                check, got = self.missed(base, head)
                self.assertEqual(got, [("calc.py", line, f"MISSED mutant calc.py:{line}: c = a - b -> c = a + b")])
                self.assertEqual((check["status"], check["tested"], check["total"]), ("fail", 2, 2), check["note"])

    def test_a_plain_file_keeps_its_numbers(self):
        _, got = self.missed(BASE, HEAD)
        self.assertEqual([g[1] for g in got], [6])


class LineMap(unittest.TestCase):
    def test_a_python_line_is_the_lf_line_that_holds_its_start(self):
        text = "a\rb\r\nc\nd\re\n"  # python lines a b c d e; git's: a b on 1, c on 2, d e on 3
        self.assertEqual([scan.lf_line(text, n, scan.PYTHON) for n in range(1, 6)], [1, 1, 2, 3, 3])
        self.assertEqual([scan.lf_line(text, n) for n in range(1, 4)], [1, 2, 3])  # LF numbers are git's already
        self.assertEqual([scan.lf_line(text, n, scan.PYTHON) for n in (0, 9, None)], [0, 9, None])  # no such line: kept

    def test_mutmut_spans_and_lines_are_gits(self):
        src = "import os\r# x\r\r\rdef add(a, b=1):\r\n    total = a + b\r    return total\n"
        self.assertEqual(mutants.scope_span(src, "calc.x_add__mutmut_1"), (1, 2))
        self.assertEqual(mutants.line_at(src, "calc.x_add__mutmut_1", 1, "total = a + b"), 2)
        self.assertEqual(mutants.locate(src, "calc.x_add__mutmut_1", "return total"), 2)


SKIP_BASE = "import os\n\n\ndef add(a, b):\n    return a + b\n"
SKIP_HEAD = "import os\n\n\ndef add(a, b):  # pragma: no mutate\n    return a + b\n"
NOQA_HEAD = "import os  # noqa\n\n\ndef add(a, b):\n    return a + b\n"


class PythonR2Lines(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(os.path.join(tmp.name, "r"))
        self.repo.commit({"pyproject.toml": "[project]\nname = 'x'\n"}, "init")
        self.n = 0

    def entries(self, before, after):
        self.n += 1
        path = os.path.join(self.repo.path, f"calc{self.n}.py")
        with open(path, "w", newline="") as f:
            f.write(before)
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "base")
        base = self.repo.git("rev-parse", "HEAD").strip()
        with open(path, "w", newline="") as f:
            f.write(after)
        self.repo.git("commit", "-qam", "head")
        head = self.repo.git("rev-parse", "HEAD").strip()
        res = r2(self.repo, base, head, adapter=None, stack="python")
        self.assertIn(res.returncode, (0, 1), res.stderr)
        return [(e["line"], e["class"], e["problem"]) for e in json.loads(res.stdout)["entries"]]

    def each(self, before, after, needle, want):
        for label, conv in (("plain", lambda t: t), ("lone CRs before it", lambda t: HEADER + t), ("CRLF", crlf),
                            ("mixed", mixed)):
            with self.subTest(label):
                head = conv(after)
                self.assertEqual(self.entries(conv(before), head), [(git_line(head, needle), *want)])

    def test_an_added_mutation_skip_is_the_needs_human_entry(self):
        self.each(SKIP_BASE, SKIP_HEAD, "# pragma", ("needs-human", "mutation skip added: `# pragma: no mutate` hides "
                                                                    "this code from R3"))

    def test_an_added_suppression_without_a_reason_is_the_entry(self):
        self.each(SKIP_BASE, NOQA_HEAD, "# noqa", ("agent-fixable", "`# noqa` added without a reason"))

    def test_a_skip_already_there_on_an_unchanged_line_is_no_entry(self):
        head = HEADER + SKIP_HEAD.replace("import os", "import sys")
        self.assertEqual(self.entries(HEADER + SKIP_HEAD, head), [])


if __name__ == "__main__":
    unittest.main()
