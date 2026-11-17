import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import comment, waiver
from scripts.mech_review.report import summarize

SHA = "a" * 40


def entry(eid="R2-deadbeef", check="R2", severity="fail", cls="agent-fixable"):
    return {"id": eid, "check": check, "class": cls, "severity": severity, "file": "tests/a.rs", "line": 7,
            "problem": "removed test fn b", "hint": "restore it", "forbidden": "deleting tests"}


def envelope(entries, r2="fail"):
    checks = {c: {"status": "skipped", "note": "not run"} for c in ("R1", "R3", "R4")}
    checks["R2"] = {"status": r2, "note": "1 fail, 0 confirm"}
    return {"ekit": "0", "base": "b" * 40, "head": SHA, "checks": checks, "entries": entries,
            "summary": summarize(SHA, checks, entries)}


def note(body, login="owner", assoc="OWNER", kind="User", url="https://github.test/c/1"):
    return {"user": {"login": login, "type": kind}, "author_association": assoc, "body": body, "html_url": url}


class TestCollect(unittest.TestCase):
    def test_owner_comment_waives_the_named_id_with_its_reason(self):
        got = waiver.collect([note("/mech-waive R2-deadbeef: test moved to the e2e suite")])
        self.assertEqual(got, {"R2-deadbeef": {"by": "owner", "reason": "test moved to the e2e suite",
                                               "url": "https://github.test/c/1"}})

    def test_member_and_collaborator_may_waive(self):
        got = waiver.collect([note("/mech-waive R1-00000001 ok", login="m", assoc="MEMBER"),
                              note("/mech-waive R3-00000002 ok", login="c", assoc="COLLABORATOR")])
        self.assertEqual({k: v["by"] for k, v in got.items()}, {"R1-00000001": "m", "R3-00000002": "c"})

    def test_outsiders_cannot_waive(self):
        for assoc in ("CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "NONE", None):
            self.assertEqual(waiver.collect([note("/mech-waive R2-deadbeef because", assoc=assoc)]), {}, assoc)

    def test_a_bot_cannot_waive_even_as_a_collaborator(self):
        self.assertEqual(waiver.collect([note("/mech-waive R2-deadbeef because", kind="Bot", assoc="COLLABORATOR")]), {})

    def test_an_outsiders_comment_does_not_stop_the_owners_later_one(self):
        got = waiver.collect([note("/mech-waive R2-deadbeef: trust me", login="x", assoc="NONE"),
                              note("/mech-waive R2-deadbeef: moved", login="owner")])
        self.assertEqual(got["R2-deadbeef"]["by"], "owner")

    def test_missing_login_url_and_body_are_empty_strings_not_a_crash(self):
        got = waiver.collect([{"user": {}, "author_association": "OWNER", "body": "/mech-waive R2-deadbeef ok"},
                              {"user": None, "author_association": "OWNER", "body": None}])
        self.assertEqual(got, {"R2-deadbeef": {"by": "", "reason": "ok", "url": ""}})

    def test_a_waiver_without_a_reason_is_ignored(self):
        self.assertEqual(waiver.collect([note("/mech-waive R2-deadbeef"), note("/mech-waive R2-deadbeef :  ")]), {})

    def test_the_command_must_open_a_line(self):
        self.assertEqual(waiver.collect([note("please do not /mech-waive R2-deadbeef because reasons")]), {})

    def test_several_lines_in_one_comment_and_surrounding_text(self):
        got = waiver.collect([note("Reviewed.\n/mech-waive R2-deadbeef equivalent\n  /mech-waive R3-0badc0de: dead code\nthanks")])
        self.assertEqual({k: v["reason"] for k, v in got.items()}, {"R2-deadbeef": "equivalent", "R3-0badc0de": "dead code"})

    def test_a_later_comment_replaces_an_earlier_waiver_of_the_same_id(self):
        got = waiver.collect([note("/mech-waive R2-deadbeef first", login="a"), note("/mech-waive R2-deadbeef second", login="b")])
        self.assertEqual((got["R2-deadbeef"]["by"], got["R2-deadbeef"]["reason"]), ("b", "second"))

    def test_ci_entries_and_malformed_ids_are_not_matched(self):
        self.assertEqual(waiver.collect([note("/mech-waive CI-deadbeef infra\n/mech-waive R2-xyz nope\n/mech-waive R5-deadbeef no")]), {})

    def test_the_placeholder_left_in_is_not_a_reason(self):
        self.assertEqual(waiver.PLACEHOLDER, "<why this is OK>")
        self.assertEqual(waiver.collect([note("/mech-waive R2-deadbeef <why this is OK>"),
                                         note("/mech-waive R2-deadbeef:   <why  this is\tOK>  ")]), {})

    def test_a_reason_wholly_wrapped_in_angle_brackets_is_not_a_reason(self):
        self.assertEqual(waiver.collect([note("/mech-waive R2-deadbeef <reason>"), note("/mech-waive R3-0badc0de <>")]), {})

    def test_a_bracketed_reason_longer_than_the_cut_is_still_not_a_reason(self):
        self.assertEqual(waiver.collect([note("/mech-waive R2-deadbeef <" + "x" * 400 + ">")]), {})

    def test_angle_brackets_inside_a_real_reason_are_fine(self):
        got = waiver.collect([note("/mech-waive R2-deadbeef <T> is generic, so the test moved"),
                              note("/mech-waive R3-0badc0de equivalent: a <= b here")])
        self.assertEqual({k: v["reason"] for k, v in got.items()},
                         {"R2-deadbeef": "<T> is generic, so the test moved", "R3-0badc0de": "equivalent: a <= b here"})

    def test_an_edited_comment_cannot_waive(self):
        c = dict(note("/mech-waive R2-deadbeef moved"), created_at="2026-11-01T10:00:00Z", updated_at="2026-11-01T10:05:00Z")
        self.assertEqual(waiver.collect([c]), {})

    def test_a_comment_never_edited_waives(self):
        c = dict(note("/mech-waive R2-deadbeef moved"), created_at="2026-11-01T10:00:00Z", updated_at="2026-11-01T10:00:00Z")
        self.assertEqual(waiver.collect([c]), {"R2-deadbeef": {"by": "owner", "reason": "moved", "url": "https://github.test/c/1"}})

    def test_a_comment_missing_either_timestamp_counts_as_unedited(self):
        got = waiver.collect([dict(note("/mech-waive R2-deadbeef moved"), created_at="2026-11-01T10:00:00Z"),
                              dict(note("/mech-waive R3-0badc0de dead"), updated_at="2026-11-01T10:05:00Z")])
        self.assertEqual({k: v["reason"] for k, v in got.items()}, {"R2-deadbeef": "moved", "R3-0badc0de": "dead"})

    def test_a_long_reason_is_cut_and_its_whitespace_collapsed(self):
        got = waiver.collect([note("/mech-waive R2-deadbeef  a   b\t" + "x" * 400)])
        self.assertEqual(len(got["R2-deadbeef"]["reason"]), waiver.REASON_MAX)
        self.assertEqual(got["R2-deadbeef"]["reason"][:5], "a b x")


EDITED = {"created_at": "2026-11-01T10:00:00Z", "updated_at": "2026-11-01T10:05:00Z"}


class TestRejected(unittest.TestCase):
    def test_an_edited_comment_is_reported_with_who_and_where(self):
        got = waiver.rejected([dict(note("/mech-waive R2-deadbeef moved"), **EDITED)])
        self.assertEqual(got, [{"id": "R2-deadbeef", "by": "owner", "url": "https://github.test/c/1",
                                "why": "the comment was edited after posting; post a new comment"}])

    def test_a_placeholder_reason_is_reported(self):
        got = waiver.rejected([note("/mech-waive R2-deadbeef <why this is OK>"), note("/mech-waive R3-0badc0de <reason>")])
        self.assertEqual(got, [
            {"id": "R2-deadbeef", "by": "owner", "url": "https://github.test/c/1",
             "why": "the reason is still the placeholder; post a new comment with the reason"},
            {"id": "R3-0badc0de", "by": "owner", "url": "https://github.test/c/1",
             "why": "the reason is still the placeholder; post a new comment with the reason"}])

    def test_an_edited_comment_with_a_placeholder_is_reported_as_edited(self):
        got = waiver.rejected([dict(note("/mech-waive R2-deadbeef <why this is OK>"), **EDITED)])
        self.assertEqual([r["why"] for r in got], ["the comment was edited after posting; post a new comment"])

    def test_waivers_that_count_or_never_could_are_not_reported(self):
        self.assertEqual(waiver.rejected([
            note("/mech-waive R2-deadbeef moved"),  # a waiver
            note("/mech-waive R2-11111111"),  # no reason at all
            note("please do not /mech-waive R2-22222222 <why this is OK>"),  # not a command
            dict(note("/mech-waive R2-33333333 <why this is OK>", assoc="CONTRIBUTOR"), **EDITED),  # no write access
            dict(note("/mech-waive R2-44444444 <why this is OK>", kind="Bot", assoc="COLLABORATOR"), **EDITED),
            dict(note("edited, no command"), **EDITED),
            {"user": None, "author_association": "OWNER", "body": None}]), [])

    def test_the_sticky_comment_by_a_machine_user_waives_and_rejects_nothing(self):
        sticky = dict(note(comment.MARKER + "\n## mech-review\n```\n/mech-waive R2-deadbeef real reason\n"
                           "/mech-waive R3-0badc0de <why this is OK>\n```\n", login="ci-user", assoc="MEMBER"), **EDITED)
        self.assertEqual((waiver.collect([sticky]), waiver.rejected([sticky])), ({}, []))
        self.assertEqual(waiver.collect([dict(sticky, created_at=None)]), {})

    def test_the_same_id_rejected_twice_is_reported_once_with_the_later_comment(self):
        got = waiver.rejected([note("/mech-waive R2-deadbeef <why this is OK>", login="a"),
                               dict(note("/mech-waive R2-deadbeef moved", login="b", url="u2"), **EDITED)])
        self.assertEqual(got, [{"id": "R2-deadbeef", "by": "b", "url": "u2",
                                "why": "the comment was edited after posting; post a new comment"}])

    def test_missing_login_and_url_are_empty_strings(self):
        got = waiver.rejected([{"user": {}, "author_association": "OWNER", "body": "/mech-waive R2-deadbeef <x>"}])
        self.assertEqual(got, [{"id": "R2-deadbeef", "by": "", "url": "",
                                "why": "the reason is still the placeholder; post a new comment with the reason"}])


class TestApply(unittest.TestCase):
    W = {"R2-deadbeef": {"by": "owner", "reason": "moved", "url": "u"}}

    def test_a_waived_fail_entry_no_longer_fails_the_check(self):
        out = waiver.apply(envelope([entry()]), self.W)
        self.assertEqual(out["entries"][0]["severity"], "waived")
        self.assertEqual(out["entries"][0]["waiver"], self.W["R2-deadbeef"])
        self.assertEqual(comment.exit_code(out), 0)
        self.assertEqual(out["checks"]["R2"]["status"], "waived")
        self.assertEqual(out["checks"]["R2"]["note"], "1 fail, 0 confirm; 1 waived by a person")
        self.assertEqual(out["summary"], f"pass {SHA} (0 fail, 0 confirm, 1 waived; ran: R2; skipped: R1 R3 R4)")

    def test_a_check_with_no_note_gets_the_waiver_note_alone(self):
        env = envelope([entry()])
        del env["checks"]["R2"]["note"]
        self.assertEqual(waiver.apply(env, self.W)["checks"]["R2"]["note"], "1 waived by a person")

    def test_other_fail_entries_of_the_check_keep_it_failing(self):
        out = waiver.apply(envelope([entry(), entry(eid="R2-11111111")]), self.W)
        self.assertEqual([e["severity"] for e in out["entries"]], ["waived", "fail"])
        self.assertEqual(out["checks"]["R2"]["status"], "fail")
        self.assertEqual(comment.exit_code(out), 1)
        self.assertEqual(out["summary"], f"fail {SHA} (1 fail, 0 confirm, 1 waived; ran: R2; skipped: R1 R3 R4)")

    def test_an_unknown_id_changes_nothing(self):
        env = envelope([entry(eid="R2-22222222")])
        self.assertIs(waiver.apply(env, self.W), env)

    def test_a_confirm_entry_is_not_waived(self):
        env = envelope([entry(severity="confirm")], r2="pass")
        self.assertIs(waiver.apply(env, self.W), env)

    def test_a_ci_entry_cannot_be_waived(self):
        env = envelope([entry(eid="CI-deadbeef", check="CI", cls="env")])
        self.assertIs(waiver.apply(env, {"CI-deadbeef": self.W["R2-deadbeef"]}), env)

    def test_the_input_envelope_is_not_modified(self):
        env = envelope([entry()])
        waiver.apply(env, self.W)
        self.assertEqual(env["entries"][0]["severity"], "fail")
        self.assertEqual(env["checks"]["R2"]["status"], "fail")

    def test_a_needs_human_entry_can_be_waived_by_the_person_it_waits_for(self):
        out = waiver.apply(envelope([entry(cls="needs-human")]), self.W)
        self.assertEqual(out["entries"][0]["severity"], "waived")
        self.assertEqual(comment.headline(out), out["summary"])


class TestRender(unittest.TestCase):
    def test_the_comment_names_who_waived_and_why_without_pinging(self):
        out = waiver.apply(envelope([entry()]), TestApply.W)
        body = comment.render(out)
        self.assertIn("Waived: R2-deadbeef by `owner`: moved", body)
        self.assertIn("| R2-deadbeef | waived | tests/a.rs:7 |", body)
        self.assertNotIn("@owner", body)

    def test_a_failing_comment_says_how_to_waive_and_a_passing_one_does_not(self):
        self.assertIn("/mech-waive R2-deadbeef <why this is OK>", comment.render(envelope([entry()])))
        self.assertNotIn("/mech-waive", comment.render(waiver.apply(envelope([entry()]), TestApply.W)))
        self.assertNotIn("/mech-waive", comment.render(envelope([entry(eid="CI-deadbeef", check="CI", cls="env")])))


class TestSummary(unittest.TestCase):
    def test_no_waiver_keeps_the_old_summary_shape(self):
        env = envelope([entry(), entry(eid="R2-33333333", severity="confirm")])
        self.assertEqual(env["summary"], f"fail {SHA} (1 fail, 1 confirm; ran: R2; skipped: R1 R3 R4)")


if __name__ == "__main__":
    unittest.main()
