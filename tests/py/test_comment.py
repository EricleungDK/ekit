import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import comment, waiver
from scripts.mech_review.report import summarize

SHA = "a" * 40
API = "https://api.github.test"
BOT = comment.DEFAULT_AUTHOR


def marker(cid, login=BOT, body=comment.MARKER + "\nold"):
    return {"id": cid, "user": {"login": login}, "body": body}


class Pages:
    """A fake transport: page N of the PR's comments, for exactly this repo and PR. Any other URL is a failure."""

    def __init__(self, *pages):
        self.pages, self.urls = pages, []

    def __call__(self, method, url, payload=None):
        self.urls.append(url)
        prefix = f"{API}/repos/o/r/issues/5/comments?per_page={comment.PER_PAGE}&page="
        if method != "GET" or not url.startswith(prefix):
            raise AssertionError(f"unexpected call {method} {url}")
        n = int(url[len(prefix):])
        return self.pages[n - 1] if n <= len(self.pages) else []


class TestFindMarker(unittest.TestCase):
    def find(self, *pages, author=BOT):
        return comment.find_marker(Pages(*pages), API, "o/r", 5, author)

    def test_the_bots_marker_comment_is_found_by_id(self):
        self.assertEqual(self.find([{"id": 1, "user": {"login": "eric"}, "body": "hi"}, marker(77)]), 77)

    def test_the_first_of_two_marker_comments_wins(self):
        self.assertEqual(self.find([marker(77), marker(78)]), 77)

    def test_a_marker_comment_by_someone_else_is_not_the_bots(self):
        self.assertIsNone(self.find([marker(88, login="mallory")]))

    def test_the_bots_other_comments_are_not_the_marker_comment(self):
        self.assertIsNone(self.find([marker(5, body="deploy preview ready"), marker(6, body="see " + comment.MARKER)]))

    def test_comments_with_no_body_or_no_user_are_passed_over(self):
        self.assertEqual(self.find([{"id": 1, "user": {"login": BOT}}, {"id": 4, "user": {"login": BOT}, "body": None},
                                    {"id": 2, "user": None, "body": comment.MARKER},
                                    {"id": 3, "body": comment.MARKER}, marker(77)]), 77)

    def test_the_default_author_is_the_actions_bot(self):
        self.assertEqual(comment.find_marker(Pages([marker(77)]), API, "o/r", 5), 77)
        self.assertEqual(BOT, "github-actions[bot]")

    def test_another_author_can_be_named(self):
        self.assertEqual(self.find([marker(77), marker(88, login="mallory")], author="mallory"), 88)

    def test_a_full_page_means_there_may_be_another(self):
        filler = [{"id": i, "user": {"login": "eric"}, "body": "x"} for i in range(comment.PER_PAGE)]
        transport = Pages(filler, [marker(77)])
        self.assertEqual(comment.find_marker(transport, API, "o/r", 5), 77)
        self.assertEqual(len(transport.urls), 2)

    def test_a_short_page_is_the_last(self):
        transport = Pages([marker(1, body="x")], [marker(77)])
        self.assertIsNone(comment.find_marker(transport, API, "o/r", 5))
        self.assertEqual(len(transport.urls), 1)


def entry(eid="R2-deadbeef", check="R2", severity="fail"):
    return {"id": eid, "check": check, "class": "agent-fixable", "severity": severity, "file": "tests/a.rs", "line": 7,
            "problem": "removed test fn b", "hint": "restore it", "forbidden": "deleting tests"}


def envelope(entries):
    checks = {c: {"status": "skipped", "note": "not run"} for c in ("R1", "R3", "R4")}
    checks["R2"] = {"status": "fail", "note": ""}
    return {"ekit": "0", "base": "b" * 40, "head": SHA, "checks": checks, "entries": entries,
            "summary": summarize(SHA, checks, entries)}


class TestWaiverLines(unittest.TestCase):
    def lines(self, w):
        e = dict(entry(severity="waived"))
        if w is not None:
            e["waiver"] = w
        return comment._waiver_lines(envelope([e]))

    def test_one_line_per_waived_entry_with_who_and_why(self):
        self.assertEqual(self.lines({"by": "eric", "reason": "moved to e2e"}), ["Waived: R2-deadbeef by `eric`: moved to e2e"])

    def test_a_waiver_with_nothing_recorded_still_reads(self):
        self.assertEqual(self.lines(None), ["Waived: R2-deadbeef by `?`: "])
        self.assertEqual(self.lines({}), ["Waived: R2-deadbeef by `?`: "])

    def test_a_backtick_in_a_login_cannot_break_out_of_the_code_span(self):
        self.assertEqual(self.lines({"by": "a`b", "reason": "r"}), ["Waived: R2-deadbeef by `a'b`: r"])

    def test_entries_that_are_not_waived_get_no_line(self):
        self.assertEqual(comment._waiver_lines(envelope([entry(), entry(eid="R2-11111111", severity="confirm")])), [])


class TestBody(unittest.TestCase):
    W = {"R2-deadbeef": {"by": "eric", "reason": "moved", "url": "u"}}

    def test_the_waiver_block_sits_between_the_headline_and_the_head_line(self):
        env = waiver.apply(envelope([entry()]), self.W)
        body = comment.render(env)
        self.assertTrue(body.startswith(f"{comment.MARKER}\n## mech-review\n\n**{env['summary']}**\n\n"
                                        f"Waived: R2-deadbeef by `eric`: moved\n\nhead `{SHA}`\n\n| id |"), body[:400])

    def test_the_waive_help_follows_the_table_after_one_blank_line(self):
        body = comment.render(envelope([entry()]))
        self.assertTrue(body.startswith(comment.MARKER + "\n## mech-review\n"))
        self.assertIn("| removed test fn b | deleting tests |\n\n" + comment.WAIVE_HELP + "\n\n### JSON\n", body)

    def test_the_help_names_the_command_and_the_job_to_rerun(self):
        self.assertEqual(comment.WAIVE_HELP, "A person with write access can let a `fail` entry through: comment "
                         "`/mech-waive <id> <reason>` on this PR, then re-run this run's failed job (`report`).")


if __name__ == "__main__":
    unittest.main()
