import unittest
from unittest import mock

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


class TestIgnoredWaivers(unittest.TestCase):
    WHY = "the comment was edited after posting; post a new comment"

    def test_each_ignored_waiver_gets_a_line_under_the_headline_naming_who_without_pinging(self):
        env = dict(envelope([entry()]), waivers_ignored=[{"id": "R2-deadbeef", "by": "eric", "why": self.WHY, "url": "u"}])
        body = comment.render(env)
        self.assertTrue(body.startswith(f"{comment.MARKER}\n## mech-review\n\n**{env['summary']}**\n\n"
                                        f"Waiver ignored: R2-deadbeef by `eric`: {self.WHY}\n\nhead `{SHA}`\n"), body[:400])
        self.assertNotIn("@eric", body)

    def test_a_backtick_in_a_login_cannot_break_out_of_the_code_span(self):
        env = dict(envelope([entry()]), waivers_ignored=[{"id": "R2-deadbeef", "by": "a`b", "why": "w", "url": "u"}])
        self.assertIn("\nWaiver ignored: R2-deadbeef by `a'b`: w\n", comment.render(env))

    def test_waived_lines_come_before_ignored_ones(self):
        env = waiver.apply(envelope([entry(), entry(eid="R2-11111111")]), {"R2-deadbeef": {"by": "eric", "reason": "moved"}})
        env["waivers_ignored"] = [{"id": "R2-11111111", "by": "ann", "why": self.WHY, "url": "u"}]
        self.assertIn(f"\n\nWaived: R2-deadbeef by `eric`: moved\nWaiver ignored: R2-11111111 by `ann`: {self.WHY}\n\nhead",
                      comment.render(env))

    def test_an_ignored_waiver_keeps_the_check_red(self):
        env = dict(envelope([entry()]), waivers_ignored=[{"id": "R2-deadbeef", "by": "eric", "why": self.WHY, "url": "u"}])
        self.assertEqual(comment.exit_code(env), 1)


class TestLineCaps(unittest.TestCase):
    WHY = TestIgnoredWaivers.WHY

    def env(self, waived, ignored):
        ids = [f"R2-{i:08x}" for i in range(waived + ignored)]
        env = waiver.apply(envelope([entry(eid=i) for i in ids]), {i: {"by": "eric", "reason": "ok"} for i in ids[:waived]})
        env["waivers_ignored"] = [{"id": i, "by": "ann", "why": self.WHY, "url": "u"} for i in ids[waived:]]
        return env

    def test_the_first_20_waived_and_20_ignored_get_a_line_and_the_rest_a_count(self):
        body = comment.render(self.env(25, 21))
        self.assertIn("\nWaived: R2-00000013 by `eric`: ok\n…and 5 more waived\n"
                      f"Waiver ignored: R2-00000019 by `ann`: {self.WHY}\n", body)
        self.assertIn(f"\nWaiver ignored: R2-0000002c by `ann`: {self.WHY}\n…and 1 more ignored\n\nhead", body)
        self.assertEqual((body.count("\nWaived: "), body.count("\nWaiver ignored: ")), (20, 20))

    def test_exactly_20_of_each_needs_no_count(self):
        body = comment.render(self.env(20, 20))
        self.assertEqual((body.count("\nWaived: "), body.count("\nWaiver ignored: ")), (20, 20))
        self.assertNotIn("…and ", body)

    def test_700_waived_and_700_ignored_stay_within_the_limit(self):
        body = comment.render(self.env(700, 700))
        self.assertLessEqual(len(body), comment.COMMENT_LIMIT)
        self.assertIn("\n…and 680 more waived\n", body)
        self.assertIn("\n…and 680 more ignored\n", body)

    def test_a_fallback_still_too_big_is_cut_at_a_line_and_says_so(self):
        wide = [dict(entry(eid=f"R2-{i:08x}"), problem="|" * 300, file="|" * 300, forbidden="|" * 300) for i in range(60)]
        body = comment.render(envelope(wide))
        self.assertLessEqual(len(body), comment.COMMENT_LIMIT)
        self.assertTrue(body.endswith(" |\n\nComment cut at the size limit. Full result: `mech-review-json` artifact of "
                                      "this run.\n"), body[-300:])
        self.assertTrue(body.startswith(comment.MARKER + "\n## mech-review\n"))


class TestSizeBoundaries(unittest.TestCase):
    """render's steps at their exact edges, with COMMENT_LIMIT set per test."""
    TAIL = "\n\n" + comment.CUT_NOTE + "\n"

    def render_at(self, env, limit):
        with mock.patch.object(comment, "COMMENT_LIMIT", limit):
            return comment.render(env)

    def env(self):
        return envelope([entry(eid=f"R2-{i:08x}") for i in range(5)])

    def test_a_comment_exactly_at_the_limit_is_kept_whole(self):
        full = comment.render(self.env())
        self.assertEqual(self.render_at(self.env(), len(full)), full)

    def test_one_char_over_the_limit_the_ready_made_lines_give_way_first(self):
        full = comment.render(self.env())
        body = self.render_at(self.env(), len(full) - 1)
        self.assertIn("\n### JSON\n", body)
        self.assertNotIn("/mech-waive R2-00000000 <why this is OK>", body)

    def test_the_cut_keeps_everything_up_to_the_last_line_break_that_fits(self):
        full = comment.render(self.env())
        no_lines = self.render_at(self.env(), len(full) - 1)
        fallback = self.render_at(self.env(), len(no_lines) - 1)
        self.assertIn("JSON omitted (comment size limit)", fallback)
        # a blank line (two line breaks) right where the room for the note ends: the first break is the last that fits
        p = fallback.index("\n\n| id |")
        body = self.render_at(self.env(), p + len(self.TAIL))
        self.assertEqual(body, fallback[:p] + self.TAIL)
        self.assertEqual(len(body), p + len(self.TAIL))

    def test_a_pipe_in_a_table_cell_is_escaped(self):
        body = comment.render(envelope([dict(entry(), problem="a|b")]))
        self.assertIn("| tests/a.rs:7 | a\\|b | deleting tests |", body)


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
        self.assertIn("| removed test fn b | deleting tests |\n\n" + comment.WAIVE_HELP + "\n\n"
                      "R2-deadbeef · `removed test fn b` (`tests/a.rs:7`)\n```\n/mech-waive R2-deadbeef <why this is OK>\n```\n"
                      "\n### JSON\n", body)

    def test_the_help_names_the_command_and_the_job_to_rerun(self):
        self.assertEqual(comment.WAIVE_HELP, "People with write access can waive a `fail` entry: copy its line below, "
                         "replace `<why this is OK>` with the reason, and post it as a PR comment. The check re-runs on "
                         "its own where the mech-waive workflow is set up; otherwise re-run this run's failed job "
                         "(`report`).")


class TestReadyMadeWaivers(unittest.TestCase):
    def test_one_fail_entry_gets_one_line_to_copy_and_no_all_at_once_block(self):
        body = comment.render(envelope([entry()]))
        self.assertIn("\nR2-deadbeef · `removed test fn b` (`tests/a.rs:7`)\n```\n/mech-waive R2-deadbeef <why this is OK>\n```\n",
                      body)
        self.assertNotIn("All fail entries at once", body)

    def test_two_fail_entries_get_a_line_each_and_one_block_for_both(self):
        body = comment.render(envelope([entry(), entry(eid="R4-11111111", check="R4")]))
        self.assertIn(comment.WAIVE_HELP + "\n\n"
                      "R2-deadbeef · `removed test fn b` (`tests/a.rs:7`)\n```\n/mech-waive R2-deadbeef <why this is OK>\n```\n\n"
                      "R4-11111111 · `removed test fn b` (`tests/a.rs:7`)\n```\n/mech-waive R4-11111111 <why this is OK>\n```\n\n"
                      "All fail entries at once\n```\n/mech-waive R2-deadbeef <why this is OK>\n"
                      "/mech-waive R4-11111111 <why this is OK>\n```\n\n### JSON\n", body)

    def test_confirm_waived_and_ci_entries_get_no_line(self):
        env = waiver.apply(envelope([entry(eid="R2-00000001", severity="confirm"), entry(eid="R2-00000002"),
                                     entry(eid="CI-00000003", check="CI"), entry(eid="R2-00000004")]),
                           {"R2-00000002": {"by": "eric", "reason": "moved"}})
        body = comment.render(env)
        self.assertIn("\n```\n/mech-waive R2-00000004 <why this is OK>\n```\n\n### JSON\n", body)
        self.assertEqual(body.count("/mech-waive "), 1, body)
        self.assertNotIn("All fail entries at once", body)

    def test_a_needs_human_fail_entry_gets_a_line(self):
        e = dict(entry(), **{"class": "needs-human"})
        self.assertIn("\n```\n/mech-waive R2-deadbeef <why this is OK>\n```\n", comment.render(envelope([e])))

    def test_the_label_text_is_cut_like_the_table_and_kept_on_one_line(self):
        e = dict(entry(), problem="a | b\nc", file="x" * 250)
        body = comment.render(envelope([e]))
        self.assertIn("\nR2-deadbeef · `a | b c` (`" + "x" * 199 + "…:7`)\n```\n", body)

    def test_pr_text_in_the_label_is_inert_code_no_ping_no_html(self):
        e = dict(entry(), problem="see `x` and @y", file="tests/@x<details>.py")
        body = comment.render(envelope([e]))
        self.assertIn("\nR2-deadbeef · ``see `x` and @y`` (`tests/@x<details>.py:7`)\n```\n", body)

    def test_a_label_text_that_starts_or_ends_with_a_backtick_is_padded(self):
        self.assertIn("\nR2-deadbeef · `` `x` `` (`` `a.py:7 ``)\n```\n",
                      comment.render(envelope([dict(entry(), problem="`x`", file="`a.py")])))
        self.assertIn("\nR2-deadbeef · `` x` `` (``a.py`b:7``)\n```\n",  # ends with one: padded; one inside: no pad
                      comment.render(envelope([dict(entry(), problem="x`", file="a.py`b")])))

    def test_the_placeholder_is_the_one_waiver_rejects(self):
        self.assertIn("/mech-waive R2-deadbeef " + waiver.PLACEHOLDER + "\n", comment.render(envelope([entry()])))
        self.assertEqual(waiver.collect([{"user": {"login": "o"}, "author_association": "OWNER",
                                          "body": "/mech-waive R2-deadbeef " + waiver.PLACEHOLDER}]), {})

    def test_when_only_the_lines_do_not_fit_they_give_way_and_the_full_table_and_json_stay(self):
        body = comment.render(envelope([dict(entry(eid=f"R2-{i:08x}"), problem="p" * 150) for i in range(70)]))
        self.assertLessEqual(len(body), comment.COMMENT_LIMIT)
        self.assertIn("| R2-00000045 | fail |", body)  # the 70th row
        self.assertNotIn("_showing first", body)
        self.assertIn(comment.WAIVE_HELP + "\n\n" + comment.WAIVE_OMITTED + "\n\n### JSON\n", body)
        self.assertNotIn("\n/mech-waive ", body)

    def test_many_entries_stay_within_the_limit_and_the_lines_give_way_to_a_note(self):
        many = [dict(entry(eid=f"R2-{i:08x}"), problem="p" * 300, file="f" * 300, forbidden="x" * 300) for i in range(300)]
        body = comment.render(envelope(many))
        self.assertLessEqual(len(body), comment.COMMENT_LIMIT)
        self.assertIn("_showing first 50 of 300 entries_\n\n" + comment.WAIVE_HELP + "\n\n"
                      "Waiver lines left out (comment size limit): post `/mech-waive <id> <why this is OK>` with an id "
                      "from the table.\n\nJSON omitted", body)
        self.assertNotIn("\n/mech-waive ", body)


if __name__ == "__main__":
    unittest.main()
