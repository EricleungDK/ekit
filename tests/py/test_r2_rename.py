"""R2: a test renamed with its body mostly kept but its assertions changed (#41) is one `confirm` entry for the reviewer,
not a `fail` for a removed test; through `cli.main(["r2", ...])` on a fixture repo (python stack)."""
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from test_adapter_cli import Repo, r2

BASE = '''import unittest

import calc


class T(unittest.TestCase):
    def test_the_budget_gone_keeps_every_mutant_missed(self):
        fake = calc.fake({"a": "survived", "b": "survived"})
        with calc.clock(100, 130, 140):
            check = calc.run(fake, budget=2)
        self.assertEqual(check["status"], "fail")
        self.assertIn("2 missed", check["note"])

    def test_adds(self):
        self.assertEqual(calc.add(1, 2), 3)
'''

RENAMED = BASE.replace("def test_the_budget_gone_keeps_every_mutant_missed", "def test_the_budget_gone_leaves_every_mutant_untested") \
              .replace('self.assertEqual(check["status"], "fail")', 'self.assertEqual(check["status"], "partial")') \
              .replace('self.assertIn("2 missed", check["note"])', 'self.assertIn("2 untested", check["note"])')

UNRELATED = BASE.replace('''    def test_the_budget_gone_keeps_every_mutant_missed(self):
        fake = calc.fake({"a": "survived", "b": "survived"})
        with calc.clock(100, 130, 140):
            check = calc.run(fake, budget=2)
        self.assertEqual(check["status"], "fail")
        self.assertIn("2 missed", check["note"])
''', '''    def test_subtracts(self):
        self.assertEqual(calc.sub(3, 1), 2)
''')


DROPPED = RENAMED.replace('        self.assertIn("2 untested", check["note"])\n', "")


BLACK_BASE = """import refunds


def test_refund_is_never_negative(
    tmp_path,
):
    assert refunds.refund(tmp_path, -5) == 0
    assert refunds.refund(tmp_path, 0) == 0
    assert refunds.refund(tmp_path, 3) == 3
"""

BLACK_HEAD = """import refunds


def test_something_else(
    tmp_path,
):
    assert True
    assert 1
    assert 2
"""

NO_ASSERT_BASE = """import calc


def test_runs_without_error():
    fake = calc.fake({"a": "survived"})
    with calc.clock(100, 130):
        calc.run(fake, budget=2)
"""

NO_ASSERT_HEAD = NO_ASSERT_BASE.replace("test_runs_without_error", "test_runs_quietly")


KEEP = """

def test_keep():
    fake = calc.fake({"a": "survived"})
    with calc.clock(100, 130):
        check = calc.run(fake, budget=2)
    assert check["status"] == "fail"
"""

ONE_LINER_BASE = """import calc


def test_refund_cap(): assert calc.refund_cap(10) == 10
""" + KEEP
ONE_LINER_HEAD = """import calc


def test_other(): assert True
""" + KEEP

TS_KEEP = """
it('keeps', () => {
  const fake = makeFake(['a'])
  const check = run(fake, 2)
  expect(check.status).toBe('fail')
})
"""
TS_BASE = """it('caps the refund', () =>
  expect(refundCap(10)).toBe(10))
""" + TS_KEEP
TS_HEAD = """it('does something else', () =>
  expect(true).toBe(true))
""" + TS_KEEP

DEFAULT_BASE = """import calc


def test_runs_in_fast_mode(
    opts={
        "mode": "fast",
        "retries": 2,
        "budget": 10,
    },
):
    assert calc.run(opts) == 1
"""
DEFAULT_HEAD = DEFAULT_BASE.replace("test_runs_in_fast_mode", "test_whatever").replace(
    "assert calc.run(opts) == 1", "assert True")

RUST = """#[test]
fn keeps_missed() {
    let fake = fake(&["a", "b"]);
    let clock = clock(100, 130);
    let check = run(&fake, &clock, 2);
    assert_eq!(check.status, "fail");
}
"""

TS = """describe('budget', () => {
  it('keeps missed', () => {
    const fake = makeFake(['a', 'b'])
    const clock = makeClock(100, 130)
    const check = run(fake, clock, 2)
    expect(check.status).toBe('fail')
  })
})
"""

PREAMBLE_BASE = """import calc


def test_adds():
    x = 1
    y = 2
    assert calc.add(x, y) == 3
"""
PREAMBLE_HEAD = """import calc


def test_divides():
    x = 1
    y = 2
    assert calc.div(y, x) == 2
"""


class R2Rename(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(os.path.join(self.tmp.name, "r"))
        self.base = self.repo.commit({"pyproject.toml": "[project]\nname = 'x'\n", "calc.py": "def add(a, b):\n    return a + b\n",
                                      "tests/test_calc.py": BASE}, "base")

    def tearDown(self):
        self.tmp.cleanup()

    def entries(self, text):
        head = self.repo.commit({"tests/test_calc.py": text}, "head")
        res = r2(self.repo, self.base, head, adapter=None, stack="python")
        return res.returncode, [(e["severity"], e["problem"]) for e in json.loads(res.stdout)["entries"]]

    def test_a_rename_whose_assertions_changed_is_one_confirm_entry(self):
        self.assertEqual(self.entries(RENAMED), (0, [
            ("confirm", "test `T::test_the_budget_gone_keeps_every_mutant_missed` renamed to "
                        "`T::test_the_budget_gone_leaves_every_mutant_untested`, assertions changed")]))

    def test_a_rename_that_drops_an_assertion_stays_a_fail(self):
        rc, got = self.entries(DROPPED)
        self.assertEqual(rc, 1)
        self.assertEqual(got, [("fail", "test fn `T::test_the_budget_gone_keeps_every_mutant_missed` removed")])

    def test_two_tests_sharing_only_a_multi_line_signature_are_no_rename(self):
        self.repo.commit({"tests/test_refunds.py": BLACK_BASE}, "black base")
        self.base = self.repo.git("rev-parse", "HEAD").strip()
        head = self.repo.commit({"tests/test_refunds.py": BLACK_HEAD}, "head")
        res = r2(self.repo, self.base, head, adapter=None, stack="python")
        self.assertEqual(res.returncode, 1)
        self.assertEqual([(e["severity"], e["problem"]) for e in json.loads(res.stdout)["entries"]],
                         [("fail", "test fn `test_refund_is_never_negative` removed")])

    def test_a_removed_test_with_no_assertion_is_no_rename_whose_assertions_changed(self):
        self.repo.commit({"tests/test_quiet.py": NO_ASSERT_BASE}, "quiet base")
        self.base = self.repo.git("rev-parse", "HEAD").strip()
        head = self.repo.commit({"tests/test_quiet.py": NO_ASSERT_HEAD}, "head")
        res = r2(self.repo, self.base, head, adapter=None, stack="python")
        self.assertEqual(res.returncode, 1)
        self.assertEqual([(e["severity"], e["problem"]) for e in json.loads(res.stdout)["entries"]],
                         [("fail", "test fn `test_runs_without_error` removed")])

    def removal(self, path, before, after, stack="python"):
        """the entries of a head that replaces `before` with `after` at path"""
        self.repo.commit({path: before}, "case base")
        self.base = self.repo.git("rev-parse", "HEAD").strip()
        head = self.repo.commit({path: after}, "case head")
        res = r2(self.repo, self.base, head, adapter=None, stack=stack)
        return res.returncode, [(e["severity"], e["problem"]) for e in json.loads(res.stdout)["entries"]]

    def test_a_one_line_test_does_not_borrow_the_next_tests_body(self):
        self.assertEqual(self.removal("tests/test_refund.py", ONE_LINER_BASE, ONE_LINER_HEAD),
                         (1, [("fail", "test fn `test_refund_cap` removed")]))

    def test_a_one_line_ts_test_does_not_borrow_the_next_tests_body(self):
        self.assertEqual(self.removal("tests/refund.test.ts", TS_BASE, TS_HEAD, stack="ts"),
                         (1, [("fail", "test fn `caps the refund` removed")]))

    def test_a_signature_default_ending_in_a_brace_is_not_the_body(self):
        self.assertEqual(self.removal("tests/test_mode.py", DEFAULT_BASE, DEFAULT_HEAD),
                         (1, [("fail", "test fn `test_runs_in_fast_mode` removed")]))

    def test_a_two_line_preamble_shared_by_different_tests_is_no_rename(self):
        self.assertEqual(self.removal("tests/test_arith.py", PREAMBLE_BASE, PREAMBLE_HEAD),
                         (1, [("fail", "test fn `test_adds` removed")]))

    def test_a_rust_rename_whose_assertion_changed_is_one_confirm_entry(self):
        self.assertEqual(self.removal("tests/budget.rs", RUST, RUST.replace("keeps_missed", "leaves_untested")
                                      .replace('"fail"', '"partial"'), stack="rust"),
                         (0, [("confirm", "test `keeps_missed` renamed to `leaves_untested`, assertions changed")]))

    def test_a_ts_rename_whose_assertion_changed_is_one_confirm_entry(self):
        self.assertEqual(self.removal("tests/budget.test.ts", TS, TS.replace("keeps missed", "leaves untested")
                                      .replace("'fail'", "'partial'"), stack="ts"),
                         (0, [("confirm", "test `budget > keeps missed` renamed to `budget > leaves untested`, "
                                          "assertions changed")]))

    def test_an_unrelated_test_in_place_of_a_removed_one_stays_a_fail(self):
        rc, got = self.entries(UNRELATED)
        self.assertEqual(rc, 1)
        self.assertEqual(got, [("fail", "test fn `T::test_the_budget_gone_keeps_every_mutant_missed` removed")])


if __name__ == "__main__":
    unittest.main()
