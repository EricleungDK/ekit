"""The SessionStart hook in-process: what it puts in the session's context."""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _kit

ss = _kit.load("session-start")
launcher = _kit.load("launcher")


class Context(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(tmp.name), "repo")
        os.mkdir(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        env = mock.patch.dict(os.environ, {"EKIT_STATE": os.path.join(os.path.realpath(tmp.name), "state"),
                                           "EKIT_PY": "py -3"})
        env.start()
        self.addCleanup(env.stop)

    def context(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"cwd": self.repo, "session_id": "s1"}))), \
                contextlib.redirect_stdout(out):
            ss.main()
        return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]

    def test_the_python_the_hook_found_starts_every_printed_command(self):
        ctx = self.context()
        self.assertIn("[ekit] Python: py -3", ctx)
        self.assertIn(f"[ekit] Scenario runner: py -3 {launcher.shown(os.path.join(_kit.SCRIPTS, 'scenarios.py'))}", ctx)

    def test_preflight_names_the_os_and_its_text_is_not_mangled(self):
        ctx = self.context()
        self.assertIn(f"[ekit] Preflight (this env):\nos: {_kit.load('preflight').os_name()}", ctx)
        self.assertNotIn("â", ctx)  # UTF-8 read as cp1252 on Windows

    def test_the_always_on_rules_stay(self):
        ctx = self.context()
        self.assertIn("failure-triage", ctx)
        self.assertNotIn("taste-it", ctx)


PLAN = ".ekit/stack-plan.toml"


def plan(*entries):
    """a stack plan: one [[stack]] table per (name, folder, adapter, status)"""
    return "".join(f'[[stack]]\nname = "{n}"\nfolder = "{f}"\nadapter = "{a}"\nstatus = "{s}"\n\n'
                   for n, f, a, s in entries)


class StackPlan(unittest.TestCase):
    """#57: the drift of the repo's committed tree against its stack plan, in the session's context."""

    setUp = Context.setUp
    context = Context.context

    def commit(self, files):
        for rel, text in files.items():
            full = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", newline="\n") as f:
                f.write(text)
        subprocess.run(["git", "-C", self.repo, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                        "commit", "-q", "-m", "c"], check=True)

    def drift_lines(self, ctx):
        return [line for line in ctx.splitlines() if "stack" in line.lower() or "manifest" in line.lower()]

    def test_each_manifest_no_stack_covers_is_named_with_what_to_do(self):
        self.commit({"web/package.json": "{}", "api/pyproject.toml": "[project]\n", "cli/Cargo.toml": "[package]\n",
                     PLAN: plan(("web", "web", "ts", "current"))})
        text = "\n".join(self.drift_lines(self.context()))
        self.assertIn("api/pyproject.toml", text)
        self.assertIn("cli/Cargo.toml", text)
        self.assertNotIn("web/package.json", text)  # covered: the web entry's folder holds it and ts lists it
        self.assertIn(PLAN, text)
        self.assertIn("ci-doctor", text)

    def test_planned_retiring_and_vanished_stacks_each_get_their_message(self):
        self.commit({"app/package.json": "{}", "old/setup.py": "", "svc/main.rs": "",
                     PLAN: plan(("app", "app", "ts", "planned"), ("old", "old", "python", "retiring"),
                                ("svc", "svc", "rust", "current"))})
        text = "\n".join(self.drift_lines(self.context()))
        self.assertRegex(text, r"planned stack `app` \(app\): .*app/package.json.*set its status to current")
        self.assertRegex(text, r"retiring stack `old` \(old\): .*old/setup.py.*finish the migration")
        self.assertRegex(text, r"stack `svc` \(svc\): no Cargo.toml in svc any more: remove the entry `svc`")

    def test_a_repo_with_no_plan_and_a_clean_one_add_nothing(self):
        before = self.context()
        self.commit({"web/package.json": "{}", "api/pyproject.toml": "[project]\n"})
        self.assertEqual(self.context(), before)  # no plan: manifests are not judged
        self.commit({PLAN: plan(("web", "web", "ts", "current"), ("api", "api", "python", "current"))})
        self.assertEqual(self.context(), before)  # every manifest covered, no message

    def test_a_session_in_a_subfolder_reads_the_whole_repo(self):
        self.commit({"web/package.json": "{}", "api/pyproject.toml": "[project]\n",
                     PLAN: plan(("web", "web", "ts", "current"))})
        self.repo = os.path.join(self.repo, "web")
        self.assertIn("api/pyproject.toml", "\n".join(self.drift_lines(self.context())))

    def test_a_folder_that_is_no_git_repo_adds_nothing(self):
        self.repo = os.path.dirname(self.repo)
        self.assertNotIn("[ekit] Stack plan", self.context())

    def test_on_a_python_without_tomllib_one_line_says_311_is_needed_and_ci_still_checks(self):
        self.commit({"web/package.json": "{}", "api/pyproject.toml": "[project]\n"})
        without_plan = self.context().splitlines()
        self.commit({PLAN: plan(("web", "web", "ts", "current"))})
        with mock.patch.dict(sys.modules, {"tomllib": None}):  # None in sys.modules: `import tomllib` raises ImportError
            lines = self.context().splitlines()
        added = [line for line in lines if line not in without_plan]
        self.assertEqual(len(added), 1, added)
        self.assertRegex(added[0], r"^\[ekit\] .*3\.11")
        self.assertIn("CI", added[0])
        self.assertNotIn("api/pyproject.toml", added[0])  # not judged here, and never read as clean
        self.assertEqual([line for line in lines if line != added[0]], without_plan)

    def test_a_malformed_plan_is_one_line_naming_the_problem_never_clean(self):
        self.commit({"web/package.json": "{}"})
        without_plan = self.context().splitlines()
        for text, problem in ((plan(("web", "web", "ts", "done")), "stack[0] `web`, field status: `done`"),
                              ("[[stack]\nname = 'web'\n", "not valid TOML")):
            with self.subTest(problem=problem):
                self.commit({PLAN: text})
                added = [line for line in self.context().splitlines() if line not in without_plan]
                self.assertEqual(len(added), 1, added)
                self.assertRegex(added[0], r"^\[ekit\] ")
                self.assertIn(PLAN, added[0])
                self.assertIn(problem, added[0])

    def test_a_git_error_is_one_line_not_a_crash_and_never_clean(self):
        before = self.context()
        self.commit({"web/package.json": "{}", PLAN: plan(("web", "web", "ts", "current"))})
        tree = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD:web"], capture_output=True, text=True,
                              check=True).stdout.strip()
        os.remove(os.path.join(self.repo, ".git", "objects", tree[:2], tree[2:]))  # the plan reads; the tree does not
        added = [line for line in self.context().splitlines() if line not in before.splitlines()]
        self.assertEqual(len(added), 1, added)
        self.assertRegex(added[0], r"^\[ekit\] Stack plan: the drift check could not run")
        self.assertIn(tree, added[0])  # git's own words name the missing object
        self.assertIn("CI", added[0])

    def test_no_git_on_the_path_is_no_crash(self):
        self.commit({"web/package.json": "{}", PLAN: plan(("api", "api", "python", "current"))})
        saved = os.dup(2)  # finish-gate.py, a child of the hook, prints its own traceback without git: not this test's
        self.addCleanup(os.close, saved)
        with open(os.devnull, "w") as null, mock.patch.dict(os.environ, {"PATH": ""}):
            os.dup2(null.fileno(), 2)
            try:
                ctx = self.context()
            finally:
                os.dup2(saved, 2)
        self.assertIn("[ekit] Preflight (this env):", ctx)

    def started(self):
        """(the session's context, the program of every process the hook started, every address it connected to)"""
        programs, addresses = [], []
        real_popen, real_connect = subprocess.Popen, socket.socket.connect

        class Popen(real_popen):
            def __init__(self, args, *a, **k):
                programs.append(os.path.basename(args[0] if isinstance(args, (list, tuple)) else args.split()[0]))
                super().__init__(args, *a, **k)

        def connect(sock, address):
            addresses.append(address)
            return real_connect(sock, address)

        with mock.patch("subprocess.Popen", Popen), mock.patch.object(socket.socket, "connect", connect):
            ctx = self.context()
        return ctx, programs, addresses

    def test_the_drift_check_starts_nothing_but_git_and_connects_nowhere(self):
        self.commit({"web/package.json": "{}", "api/pyproject.toml": "[project]\n"})
        _, without_plan, _ = self.started()
        self.commit({PLAN: plan(("web", "web", "ts", "retiring"), ("cli", "cli", "rust", "current"))})
        ctx, with_plan, addresses = self.started()
        self.assertIn("api/pyproject.toml", ctx)  # the drift check ran
        extra = list(with_plan)
        for program in without_plan:  # what the hook starts with no plan (finish gate, preflight's tools)
            if program in extra:
                extra.remove(program)
        self.assertTrue(extra, "the drift check starts git")
        self.assertEqual(set(extra), {"git"})
        self.assertEqual(addresses, [])


if __name__ == "__main__":
    unittest.main()
