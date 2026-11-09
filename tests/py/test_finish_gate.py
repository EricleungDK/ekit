"""finish-gate.py in-process: the hook payload goes in on stdin, the runner is a fake, the decision comes out on stdout."""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import _kit

fg = _kit.load("finish-gate")

DONE = "Work is in.\n\n## Finish: done\n| Criterion | Status | Evidence |"
BLOCKED = "## Finish: blocked\nBlocker: no token"


class Runner:
    """Stands in for scenarios.py: `tree` is the tree-hash answer, `check` the (rc, text) of `check`."""

    def __init__(self):
        self.tree, self.check, self.calls = (0, "T0"), (0, ""), []

    def __call__(self, repo, cmd):
        self.calls.append(cmd)
        return self.tree if cmd == "tree-hash" else self.check


class GateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(os.path.realpath(self.tmp.name), "repo")
        os.mkdir(self.repo)
        subprocess.run(["git", "-C", self.repo, "init", "-q"], check=True)
        self.runner = Runner()
        for p in (mock.patch.object(fg, "STATE", os.path.join(self.tmp.name, "state")),
                  mock.patch.object(fg, "runner", self.runner)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def hook(self, *flags, session="s1", cwd=None, **payload):
        data = dict({"session_id": session, "cwd": cwd or self.repo}, **payload)
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(data))), mock.patch("sys.argv", ["finish-gate.py", *flags]), \
                contextlib.redirect_stdout(out):
            fg.main()
        return json.loads(out.getvalue()) if out.getvalue() else None

    def start(self, session="s1", arm=True):
        self.hook("--baseline", session=session)
        if arm:
            self.hook("--arm", session=session, prompt="/ekit:orchestrate-agent do x")

    def stop(self, msg=None, session="s1", **payload):
        if msg is not None:
            payload["last_assistant_message"] = msg
        return self.hook(session=session, hook_event_name=payload.pop("hook_event_name", "Stop"), **payload)

    def scenarios(self):
        os.makedirs(os.path.join(self.repo, ".ekit", "scenarios"))


class TestArm(GateCase):
    def test_an_unarmed_session_is_never_gated(self):
        self.start(arm=False)
        self.runner.tree = (0, "T1")
        self.assertIsNone(self.stop())

    def test_only_a_prompt_that_starts_with_the_command_arms(self):
        for prompt, armed in (("/ekit:orchestrate-agent fix #3", True), ("  /orchestrate-agent x", True),
                              ("<command-name>/ekit:orchestrate-agent</command-name>", True),
                              ("why does /ekit:orchestrate-agent run?", False), ("/ekit:taste-it", False),
                              ("/ekit:orchestrate-agents", False), ("", False)):
            session = f"s-{abs(hash(prompt))}"
            self.hook("--baseline", session=session)
            self.assertIsNone(self.hook("--arm", session=session, prompt=prompt))
            self.runner.tree = (0, "T1")
            got = self.stop(session=session)
            self.runner.tree = (0, "T0")
            self.assertEqual(got is not None, armed, prompt)


class TestWork(GateCase):
    def test_no_change_since_session_start_is_allowed(self):
        self.start()
        self.assertIsNone(self.stop())

    def test_work_without_a_report_blocks_once_per_tree(self):
        self.start()
        self.runner.tree = (0, "T1")
        out = self.stop("all done, trust me")
        self.assertEqual(out["decision"], "block")
        self.assertEqual(out["reason"], "[ekit] Work changed since session start and the last message is not a finish "
                                        "report. " + fg.ASK)
        self.assertIsNone(self.stop("all done, trust me"))
        self.runner.tree = (0, "T2")
        self.assertEqual(self.stop()["decision"], "block")

    def test_the_ask_names_the_report_header(self):
        self.assertIn("`## Finish: done` or `## Finish: blocked`", fg.ASK)

    def test_a_finish_report_allows_and_the_reported_tree_stays_allowed(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.assertIsNone(self.stop(DONE))
        self.assertIsNone(self.stop("answering a follow-up"))
        self.runner.tree = (0, "T2")
        self.assertEqual(self.stop("answering a follow-up")["decision"], "block")

    def test_a_blocked_report_allows_too(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.assertIsNone(self.stop(BLOCKED))

    def test_the_baseline_is_written_once_per_session(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.hook("--baseline")
        self.assertEqual(self.stop()["decision"], "block")

    def test_a_session_with_no_baseline_treats_the_tree_as_work(self):
        self.hook("--arm", prompt="/ekit:orchestrate-agent x")
        self.assertEqual(self.stop()["decision"], "block")

    def test_the_baseline_is_per_repo(self):
        other = os.path.join(os.path.realpath(self.tmp.name), "other")
        os.mkdir(other)
        subprocess.run(["git", "-C", other, "init", "-q"], check=True)
        self.start()
        self.runner.tree = (0, "OTHER")
        self.hook("--baseline", cwd=other)
        self.assertIsNone(self.hook(cwd=other, hook_event_name="Stop"))
        self.assertEqual(self.stop()["decision"], "block")

    def test_stop_hook_active_is_the_loop_guard(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.assertIsNone(self.stop(stop_hook_active=True))

    def test_a_subagent_stop_is_never_gated(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.assertIsNone(self.stop(hook_event_name="SubagentStop"))

    def test_outside_a_git_repo_nothing_is_gated(self):
        self.start()
        with tempfile.TemporaryDirectory() as plain:
            self.assertIsNone(self.hook(cwd=plain, hook_event_name="Stop"))
        self.assertEqual(self.runner.calls, ["tree-hash"])  # the baseline only: the plain dir never reached the runner

    def test_a_failed_baseline_hash_is_stored_empty_so_any_tree_counts_as_work(self):
        self.runner.tree = (3, "boom")
        self.start()
        self.runner.tree = (0, "T0")
        self.assertEqual(self.stop()["decision"], "block")


class TestScenarios(GateCase):
    def test_a_plain_repo_never_runs_check(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.stop(DONE)
        self.assertNotIn("check", self.runner.calls)

    def test_scenarios_not_green_block_every_stop_even_with_a_done_report(self):
        self.scenarios()
        self.start()
        self.runner.tree, self.runner.check = (0, "T1"), (1, "stale: tree changed since run")
        for msg in (None, DONE, DONE):
            out = self.stop(msg)
            self.assertEqual(out["decision"], "block")
            self.assertTrue(out["reason"].startswith("[ekit] Scenarios not green: stale: tree changed since run. Run `python3 "),
                            out["reason"])
            self.assertIn(f"scenarios.py --repo {self.repo} run` and follow the taste-it skill (ekit:taste-it). ", out["reason"])
            self.assertTrue(out["reason"].endswith(fg.ASK))

    def test_green_scenarios_still_need_the_report(self):
        self.scenarios()
        self.start()
        self.runner.tree = (0, "T1")
        out = self.stop()
        self.assertIn("not a finish report", out["reason"])
        self.assertNotIn("Scenarios not green", out["reason"])
        self.assertIsNone(self.stop())

    def test_green_scenarios_and_a_report_allow(self):
        self.scenarios()
        self.start()
        self.runner.tree = (0, "T1")
        self.assertIsNone(self.stop(DONE))
        self.assertIn("check", self.runner.calls)

    def test_a_blocked_report_needs_no_pass(self):
        self.scenarios()
        self.start()
        self.runner.tree, self.runner.check = (0, "T1"), (1, "last run FAIL")
        self.assertIsNone(self.stop(BLOCKED))
        self.assertNotIn("check", self.runner.calls)
        self.assertIsNone(self.stop("a later turn"))

    def test_the_pre_rename_scenarios_dir_counts(self):
        os.makedirs(os.path.join(self.repo, ".ek", "scenarios"))
        self.start()
        self.runner.tree, self.runner.check = (0, "T1"), (1, "no results: run scenarios")
        self.assertIn("Scenarios not green: no results", self.stop(DONE)["reason"])

    def test_a_runner_error_blocks_with_its_last_line(self):
        self.scenarios()
        self.start()
        self.runner.tree = (3, "Traceback (most recent call last):\n  File x\nValueError: boom")
        out = self.stop(DONE)
        self.assertTrue(out["reason"].startswith("[ekit] scenario runner error: ValueError: boom. Run `python3 "), out["reason"])
        self.runner.tree = (2, "")
        self.assertIn("scenario runner error: exit 2. ", self.stop(DONE)["reason"])

    def test_a_check_error_is_a_runner_error_not_a_red_scenario(self):
        self.scenarios()
        self.start()
        self.runner.tree, self.runner.check = (0, "T1"), (3, "cannot hash the working tree: x")
        out = self.stop(DONE)
        self.assertIn("scenario runner error: cannot hash the working tree: x. ", out["reason"])
        self.assertNotIn("Scenarios not green", out["reason"])
        self.runner.check = (2, "")
        self.assertIn("scenario runner error: exit 2. ", self.stop(DONE)["reason"])


class TestReport(unittest.TestCase):
    def kind(self, msg):
        return fg.report_kind({"last_assistant_message": msg})

    def test_the_header_is_read_at_any_heading_level_and_case(self):
        self.assertEqual(self.kind("## Finish: done"), "done")
        self.assertEqual(self.kind("intro\n\n### finish: Blocked\nBlocker: x"), "blocked")
        self.assertEqual(self.kind("# Finish:done"), "done")
        self.assertEqual(self.kind("   ## Finish: done"), "done")

    def test_only_a_heading_line_counts(self):
        for msg in ("Finish: done", "I will write ## Finish: done next", "## Finish: doneish", "## Finishing: done",
                    "    ## Finish: done", "## Finish: maybe", ""):
            self.assertIsNone(self.kind(msg), msg)

    def test_the_transcript_is_read_when_the_payload_has_no_message(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as f:
            rows = [
                {"type": "user", "message": {"content": "/ekit:orchestrate-agent x"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "## Finish: done\nold"}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
                {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "## Finish: done"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Summary."},
                                                              {"type": "tool_use", "name": "x"}]}},
            ]
            f.write("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
            f.flush()
            data = {"transcript_path": f.name}
            self.assertEqual(fg.last_message(data), "Summary.")
            self.assertIsNone(fg.report_kind(data))
            f.write(json.dumps({"type": "assistant", "message": {"content": "## Finish: blocked\nBlocker: x"}}) + "\n")
            f.flush()
            self.assertEqual(fg.last_message(data), "Summary.\n## Finish: blocked\nBlocker: x")
            self.assertEqual(fg.report_kind(data), "blocked")

    def test_the_payload_message_wins_over_the_transcript(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": "## Finish: done"}}) + "\n")
            f.flush()
            self.assertEqual(fg.last_message({"last_assistant_message": "hello", "transcript_path": f.name}), "hello")

    def test_no_message_and_no_transcript_is_empty(self):
        self.assertEqual(fg.last_message({}), "")
        self.assertEqual(fg.last_message({"transcript_path": "/nonexistent/ekit.jsonl", "last_assistant_message": ""}), "")

    def test_only_the_tail_of_a_long_transcript_is_read(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": "## Finish: done"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": "x" * (fg.TAIL + 10)}}) + "\n")
            f.flush()
            self.assertIsNone(fg.report_kind({"transcript_path": f.name}))


class TestPrune(GateCase):
    def test_session_start_drops_state_older_than_the_keep_window(self):
        self.start(session="old")
        state = fg.STATE
        old = time.time() - (fg.KEEP_DAYS + 1) * 86400
        for name in os.listdir(state):
            os.utime(os.path.join(state, name), (old, old))
        self.start(session="new")
        names = os.listdir(state)
        self.assertEqual([n for n in names if n.startswith("old.")], [])
        self.assertEqual(sorted(n.split(".")[1].split("-")[0] for n in names), ["armed", "sbase"])

    def test_recent_state_stays(self):
        self.start(session="a")
        self.start(session="b")
        self.assertEqual(len([n for n in os.listdir(fg.STATE) if n.startswith("a.")]), 2)


if __name__ == "__main__":
    unittest.main()
