"""The sticky comment for several stacks (#17): one comment, a row per stack (name, stack, project dir, its result),
entries labelled with their stack, and each stack's own lines (not run, R0, R3 timing) named by stack."""
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import comment, merge
from scripts.mech_review.report import CHECKS, envelope

BASE, HEAD = "b" * 40, "a" * 40
API = {"name": "api", "stack": "python", "project_dir": "api"}
WEB = {"name": "web", "stack": "ts", "project_dir": "web"}
FAIL = {"id": "R2-0badc0de", "check": "R2", "class": "agent-fixable", "severity": "fail", "file": "web/a.test.ts",
        "line": 4, "problem": "removed test b", "hint": "restore it", "forbidden": "deleting tests"}


def stack_env(entries=(), **more):
    checks = {c: {"status": "skipped", "note": "not run"} for c in CHECKS}
    checks["R2"] = {"status": "fail" if entries else "pass", "note": ""}
    checks.update(more)
    return envelope(BASE, HEAD, list(entries), checks)


def body(*legs):
    return comment.render(merge.combine_stacks(list(legs)))


class TestStacksComment(unittest.TestCase):
    def test_a_row_per_stack_names_it_its_adapter_its_project_dir_and_its_result(self):
        b = body((API, stack_env()), (WEB, stack_env([FAIL])))
        self.assertIn("| stack | adapter | project dir | result |\n|---|---|---|---|\n"
                      f"| api | python | api | pass {HEAD} (0 fail, 0 confirm; ran: R2; skipped: R1 R3 R4) |\n"
                      f"| web | ts | web | fail {HEAD} (1 fail, 0 confirm; ran: R2; skipped: R1 R3 R4) |", b)
        self.assertIn(f"**fail {HEAD} (1 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)**", b)

    def test_each_entry_is_labelled_with_its_stack(self):
        env = merge.combine_stacks([(API, stack_env()), (WEB, stack_env([FAIL]))])
        [e] = env["entries"]
        self.assertIn("| id | stack | severity | file:line | problem | forbidden |", comment.render(env))
        self.assertIn(f"| {e['id']} | web | fail | web/a.test.ts:4 | removed test b | deleting tests |", comment.render(env))
        self.assertIn(f"/mech-waive {e['id']} <why this is OK>", comment.render(env))

    def test_a_stacks_own_lines_are_named_by_stack(self):
        b = body((API, stack_env(R0={"status": "pass", "note": "3 proved"})),
                 (WEB, stack_env(R1={"status": "n/a", "note": "no node"})))
        self.assertIn("api: R0: `3 proved`", b)
        self.assertIn("web: Did not run: R1 (no node)", b)
        self.assertNotIn("Did not run: R1 (web: n/a", b)

    def test_one_stack_reads_as_before_no_stack_table_no_stack_column(self):
        b = comment.render(stack_env([FAIL]))
        self.assertNotIn("| stack |", b)
        self.assertIn("| id | severity | file:line | problem | forbidden |", b)


if __name__ == "__main__":
    unittest.main()
