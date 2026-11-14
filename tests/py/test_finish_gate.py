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
        self.tree, self.check, self.calls, self.repos = (0, "T0"), (0, ""), [], set()

    def __call__(self, repo, cmd):
        self.calls.append(cmd)
        self.repos.add(repo)
        return self.tree if cmd == "tree-hash" else self.check


class Verifier:
    """Stands in for `task-verify.py check`: `result` is its (rc, text)."""

    def __init__(self):
        self.result, self.calls = (0, ""), []

    def __call__(self, repo, session):
        self.calls.append((repo, session))
        return self.result


class GateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(os.path.realpath(self.tmp.name), "repo")
        os.mkdir(self.repo)
        subprocess.run(["git", "-C", self.repo, "init", "-q"], check=True)
        self.runner, self.verifier = Runner(), Verifier()
        for p in (mock.patch.object(fg, "STATE", os.path.join(self.tmp.name, "state")),
                  mock.patch.object(fg, "runner", self.runner), mock.patch.object(fg, "verifier", self.verifier)):
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

    def test_loop_guard_and_subagent_stops_start_no_runner_process(self):
        self.start()
        del self.runner.calls[:]
        self.stop(stop_hook_active=True)
        self.stop(hook_event_name="SubagentStop")
        self.assertEqual(self.runner.calls, [])
        self.hook("--baseline", session="fresh", stop_hook_active=True)  # a session start always records its tree
        self.assertEqual(self.runner.calls, ["tree-hash"])

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
        self.runner.tree = (3, "T0")  # the runner failed; whatever it printed is not a baseline
        self.start()
        self.runner.tree = (0, "T0")
        self.assertEqual(self.stop()["decision"], "block")

    def test_the_runner_is_asked_about_the_repo_root(self):
        self.scenarios()
        self.start()
        self.runner.tree = (0, "T1")
        self.stop(DONE)
        self.assertEqual(self.runner.repos, {self.repo})

    def test_the_state_kept_for_a_session_is_these_four_files(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.stop()          # blocked: gated
        self.stop(DONE)      # reported
        names = sorted(os.listdir(fg.STATE))
        self.assertEqual([n.split(".", 1)[1].rsplit("-", 1)[0] for n in names], ["armed", "gated", "reported", "sbase"])
        for n in names[1:]:
            self.assertRegex(n, r"^s1\.[a-z]+-[0-9a-f]{12}$")  # per repo: 12 hex of its path

    def test_a_failed_baseline_is_stored_as_the_empty_string(self):
        self.runner.tree = (3, "boom")
        self.start()
        (base,) = [n for n in os.listdir(fg.STATE) if ".sbase-" in n]
        with open(os.path.join(fg.STATE, base)) as f:
            self.assertEqual(f.read(), "")


def task(type="subagent", status="running"):
    """One `background_tasks` entry, as Claude Code sends it on a Stop payload."""
    return {"id": "a547f8e8e20894387", "type": type, "status": status, "description": "unit core", "agent_type": "general-purpose"}


class TestWaiting(GateCase):
    """A stop while a subagent still runs is a wait for its report: the session wakes again, so nothing is asked yet."""

    def test_a_stop_while_a_subagent_runs_is_not_gated(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.assertIsNone(self.stop("waiting for the implementer", background_tasks=[task()]))

    def test_a_wait_does_not_use_up_the_ask_for_that_tree(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.stop(background_tasks=[task()])
        self.assertEqual(self.stop(background_tasks=[])["decision"], "block")

    def test_a_wait_is_allowed_while_the_scenarios_are_red(self):
        self.scenarios()
        self.start()
        self.runner.tree, self.runner.check = (0, "T1"), (1, "FAIL ok")
        self.assertIsNone(self.stop(background_tasks=[task()]))
        self.assertIn("Scenarios not green", self.stop()["reason"])

    def test_a_wait_starts_no_runner_process(self):
        self.start()
        del self.runner.calls[:]
        self.stop(background_tasks=[task()])
        self.assertEqual(self.runner.calls, [])

    def test_one_running_subagent_among_finished_tasks_is_a_wait(self):
        self.start()
        self.runner.tree = (0, "T1")
        self.assertIsNone(self.stop(background_tasks=[task(status="completed"), task("shell"), task()]))

    def test_only_a_running_subagent_is_a_wait(self):
        """A subagent that finished wakes nothing, and a background shell (a dev server) may never end."""
        self.start()
        for n, tasks in enumerate(([task(status="completed")], [task(status="failed")], [task("shell")], [task("bash")], [])):
            self.runner.tree = (0, f"T{n + 1}")
            self.assertEqual(self.stop(background_tasks=tasks)["decision"], "block", tasks)

    def test_a_payload_without_readable_tasks_is_gated_as_before(self):
        self.start()
        for n, tasks in enumerate((None, "running", {"type": "subagent", "status": "running"}, ["subagent"], [None], [{}])):
            self.runner.tree = (0, f"T{n + 1}")
            self.assertEqual(self.stop(background_tasks=tasks)["decision"], "block", tasks)

    def test_an_unarmed_session_stays_silent_while_a_subagent_runs(self):
        self.start(arm=False)
        self.runner.tree = (0, "T1")
        self.assertIsNone(self.stop(background_tasks=[task()]))
        self.assertEqual(os.listdir(fg.STATE), [n for n in os.listdir(fg.STATE) if ".sbase-" in n])


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

    def test_an_ekit_dir_without_scenarios_is_a_plain_repo(self):
        os.makedirs(os.path.join(self.repo, ".ekit"))
        self.start()
        self.runner.tree, self.runner.check = (0, "T1"), (1, "no results")
        self.assertIsNone(self.stop(DONE))
        self.assertNotIn("check", self.runner.calls)

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


class TestVerifyCommands(GateCase):
    """A `done` report stands only when every verify command of the session passed on the files as they are."""

    def work(self):
        self.start()
        self.runner.tree = (0, "T1")

    def test_a_done_report_with_commands_not_green_blocks_every_stop(self):
        self.work()
        self.verifier.result = (1, "`pytest -q`: the run exited 1")
        for _ in range(2):
            out = self.stop(DONE)
            self.assertEqual(out["decision"], "block")
        self.assertEqual(out["reason"], (
            "[ekit] Verify commands not green for the current files: `pytest -q`: the run exited 1. Each task of "
            "this session carries a line `Verify: <command>` (the whole job: one task with the full suite). "
            f"Run each through `python3 {os.path.join(_kit.SCRIPTS, 'task-verify.py')} --repo {self.repo} run -- "
            "<command>`, fix what it shows, then give the finish report again. It cannot pass here → "
            "`## Finish: blocked`."))
        self.assertEqual(self.verifier.calls[-1], (self.repo, "s1"))

    def test_a_done_report_with_green_commands_allows(self):
        self.work()
        self.assertIsNone(self.stop(DONE))
        self.assertEqual(len(self.verifier.calls), 1)

    def test_a_blocked_report_needs_no_green_command(self):
        self.work()
        self.verifier.result = (1, "x")
        self.assertIsNone(self.stop(BLOCKED))
        self.assertEqual(self.verifier.calls, [])

    def test_without_a_report_the_ask_is_the_report(self):
        self.work()
        self.verifier.result = (1, "x")
        self.assertIn("not a finish report", self.stop("still working")["reason"])
        self.assertEqual(self.verifier.calls, [])

    def test_a_tree_reported_while_red_is_not_remembered_as_reported(self):
        self.work()
        self.verifier.result = (1, "x")
        self.stop(DONE)
        self.verifier.result = (0, "")
        self.assertEqual(self.stop("later turn")["decision"], "block")

    def test_red_scenarios_are_named_before_the_commands(self):
        self.work()
        os.makedirs(os.path.join(self.repo, ".ekit", "scenarios"))
        self.runner.check = (1, "last run FAIL")
        self.verifier.result = (1, "x")
        self.assertIn("Scenarios not green", self.stop(DONE)["reason"])


class TestVerifierProcess(unittest.TestCase):
    """fg.verifier for real: it asks task-verify.py about the session's commands in the repo."""

    def test_it_reports_check_for_the_session_and_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(os.path.realpath(tmp), "repo")
            os.mkdir(repo)
            subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
            tv = os.path.join(_kit.SCRIPTS, "task-verify.py")
            with mock.patch.dict(os.environ, {"EKIT_STATE": os.path.join(tmp, "state")}):
                payload = {"hook_event_name": "TaskCreated", "session_id": "s1", "cwd": repo, "task_id": "1",
                           "task_description": "Verify: `true`"}
                subprocess.run(["python3", "-I", tv, "--hook"], input=json.dumps(payload), text=True, check=True)
                self.assertEqual(fg.verifier(repo, "s1"), (1, "`true`: no run recorded"))
                self.assertEqual(fg.verifier(repo, "s2"), (1, "no task of this session has a `Verify:` line"))
                subprocess.run(["python3", "-I", tv, "--repo", repo, "run", "--", "true"], capture_output=True, check=True)
                self.assertEqual(fg.verifier(repo, "s1"), (0, ""))


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

    def test_text_blocks_are_joined_by_newlines_and_other_content_is_empty(self):
        self.assertEqual(fg._text([{"type": "text", "text": "a"}, {"type": "tool_use"}, {"type": "text"}, "x",
                                   {"type": "text", "text": "b"}]), "a\n\nb")
        self.assertEqual(fg._text("plain"), "plain")
        self.assertEqual(fg._text(None), "")
        self.assertEqual(fg._text({"type": "text", "text": "not a list"}), "")

    def test_an_empty_payload_message_falls_back_to_the_transcript(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": "## Finish: done"}}) + "\n")
            f.flush()
            self.assertEqual(fg.last_message({"last_assistant_message": "", "transcript_path": f.name}), "## Finish: done")

    def test_a_sidechain_entry_between_two_parts_of_the_message_is_skipped_not_the_end(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as f:
            rows = [{"type": "assistant", "message": {"content": "## Finish: blocked"}},
                    {"type": "assistant", "isSidechain": True, "message": {"content": "subagent chatter"}},
                    ["not", "a", "dict"],
                    {"type": "assistant", "message": {"content": "Blocker: x"}}]
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")
            f.flush()
            self.assertEqual(fg.last_message({"transcript_path": f.name}), "## Finish: blocked\nBlocker: x")

    def test_bytes_that_are_not_utf8_in_the_transcript_do_not_crash_the_read(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".jsonl") as f:
            f.write(b"\xff\xfe garbage line\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": "## Finish: done"}}).encode() + b"\n")
            f.flush()
            self.assertEqual(fg.report_kind({"transcript_path": f.name}), "done")

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
    def test_the_window_is_keep_days_to_the_second(self):
        now = 1_800_000_000
        os.makedirs(fg.STATE)
        for name, extra in (("at.armed", 0), ("past.armed", 1)):
            p = os.path.join(fg.STATE, name)
            open(p, "w").close()
            os.utime(p, (now - fg.KEEP_DAYS * 86400 - extra,) * 2)
        with mock.patch.object(fg.time, "time", return_value=now):
            fg.prune()
        self.assertEqual(os.listdir(fg.STATE), ["at.armed"])

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
