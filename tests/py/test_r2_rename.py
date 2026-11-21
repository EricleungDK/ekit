"""R2: a test renamed with its body mostly kept but its assertions changed (#41) is one `confirm` entry for the reviewer,
not a `fail` for a removed test; through `cli.main(["r2", ...])` on a fixture repo (python stack)."""
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from test_adapter_cli import MINI, Repo, r2

# prettier splits a call with a long name: the name, `async () => {` and `},` get lines of their own
TS_SPLIT_BASE = """it(
  'refund is never negative, whatever the input amount is',
  async () => {
    const x = f(1)
    expect(g(x)).toBe(2)
    expect(h(x)).toBe(0)
  },
)
"""
TS_SPLIT_HEAD = """it(
  'something else entirely, with a long enough name to split',
  async () => {
    const x = f(1)
    expect(1).toBe(1)
    expect(2).toBe(2)
  },
)
"""
TS_SPLIT_LEGIT_BASE = """it(
  'refund is never negative, whatever the input amount is',
  async () => {
    const shop = await makeShop()
    const order = shop.order(['a', 'b'])
    const refund = shop.refund(order, -5)
    expect(refund.amount).toBe(0)
  },
)
"""
TS_SPLIT_LEGIT_HEAD = TS_SPLIT_LEGIT_BASE.replace("refund is never negative", "refund is capped at the order") \
    .replace("toBe(0)", "toBe(order.total)")

MINI_SPLIT_BASE = """suite("Calc", {
  test(
    "refund never negative",
    {
      setUp(1)
      assertEquals(0, refund(-5))
      assertEquals(3, refund(3))
    },
  )
})
"""
MINI_SPLIT_HEAD = """suite("Calc", {
  test(
    "something else entirely",
    {
      setUp(1)
      assertTrue(1)
      assertTrue(2)
    },
  )
})
"""

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

    def removal(self, path, before, after, stack="python", adapter=None):
        """the entries of a head that replaces `before` with `after` at path"""
        self.repo.commit({path: before}, "case base")
        self.base = self.repo.git("rev-parse", "HEAD").strip()
        head = self.repo.commit({path: after}, "case head")
        res = r2(self.repo, self.base, head, adapter=adapter, stack=stack)
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

    def test_a_prettier_split_ts_call_shares_no_lines_of_its_own_with_another(self):
        self.assertEqual(self.removal("tests/refund.test.ts", TS_SPLIT_BASE, TS_SPLIT_HEAD, stack="ts"),
                         (1, [("fail", "test fn `refund is never negative, whatever the input amount is` removed")]))

    def test_a_split_test_call_of_an_adapter_file_stack_shares_no_lines_of_its_own_with_another(self):
        self.assertEqual(self.removal("tests/calc.mini", MINI_SPLIT_BASE, MINI_SPLIT_HEAD, stack="mini", adapter=MINI),
                         (1, [("fail", "test fn `Calc / refund never negative` removed")]))

    def test_a_prettier_split_ts_rename_with_its_setup_kept_is_one_confirm_entry(self):
        self.assertEqual(self.removal("tests/refund.test.ts", TS_SPLIT_LEGIT_BASE, TS_SPLIT_LEGIT_HEAD, stack="ts"),
                         (0, [("confirm", "test `refund is never negative, whatever the input amount is` renamed to "
                                          "`refund is capped at the order, whatever the input amount is`, "
                                          "assertions changed")]))

    def test_a_ts_rename_whose_call_ends_in_an_options_object_reads_the_callback_body(self):
        base = TS_SPLIT_LEGIT_BASE.replace("  },\n)\n", "  },\n  { timeout: 5000 },\n)\n")
        head = TS_SPLIT_LEGIT_HEAD.replace("  },\n)\n", "  },\n  { timeout: 5000 },\n)\n")
        self.assertEqual(self.removal("tests/refund.test.ts", base, head, stack="ts"),
                         (0, [("confirm", "test `refund is never negative, whatever the input amount is` renamed to "
                                          "`refund is capped at the order, whatever the input amount is`, "
                                          "assertions changed")]))

    def test_an_unrelated_test_in_place_of_a_removed_one_stays_a_fail(self):
        rc, got = self.entries(UNRELATED)
        self.assertEqual(rc, 1)
        self.assertEqual(got, [("fail", "test fn `T::test_the_budget_gone_keeps_every_mutant_missed` removed")])


if __name__ == "__main__":
    unittest.main()
