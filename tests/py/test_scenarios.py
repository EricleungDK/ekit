import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts import scenarios
from _kit import symlink  # a skip naming the refusal where the OS will not make links

RUN_FILES = ("run.py", "run.sh", "run.ps1")  # #59: the formats a scenario may be written in


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                       capture_output=True, text=True)
    return r.stdout.strip()


def write(repo, name, text, age=0):
    """age (seconds): an old mtime, so git trusts its index entry for the file and does not read it again"""
    path = os.path.join(repo, name)
    with open(path, "w") as f:
        f.write(text)
    if age:
        os.utime(path, (time.time() - age, time.time() - age))


@contextlib.contextmanager
def fd_output():
    """What this process and its children write to stdout and stderr, at the file descriptor level."""
    with tempfile.TemporaryFile() as f:
        saved = os.dup(1), os.dup(2)
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)
        box = []
        try:
            yield box
        finally:
            for fd, old in zip((1, 2), saved):
                os.dup2(old, fd)
                os.close(old)
            f.seek(0)
            box.append(f.read().decode())


class TestTreeHash(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        git(self.repo, "init", "-q")
        write(self.repo, "a.txt", "one\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")

    def tearDown(self):
        self.tmp.cleanup()

    def hash(self):
        return scenarios.tree_hash(self.repo)

    def test_a_clean_tree_hashes_to_heads_tree(self):
        self.assertEqual(self.hash(), git(self.repo, "rev-parse", "HEAD^{tree}"))

    def test_committing_the_same_files_keeps_the_hash(self):
        write(self.repo, "a.txt", "two\n")
        write(self.repo, "new.txt", "n\n")
        dirty = self.hash()
        git(self.repo, "add", "-A")
        self.assertEqual(self.hash(), dirty)
        git(self.repo, "commit", "-q", "-m", "work")
        self.assertEqual(self.hash(), dirty)
        self.assertEqual(dirty, git(self.repo, "rev-parse", "HEAD^{tree}"))

    def test_unchanged_files_beside_a_changed_one_hash_from_the_repos_own_objects(self):
        os.makedirs(os.path.join(self.repo, "pkg", "sub"))
        write(self.repo, "pkg/keep.txt", "keep\n", age=7200)  # old: its blob is looked up, not written again
        write(self.repo, "pkg/sub/deep.txt", "deep\n", age=7200)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "more")
        write(self.repo, "pkg/sub/deep.txt", "deeper\n")
        dirty = self.hash()
        self.assertRegex(dirty, r"^[0-9a-f]{40}$")
        git(self.repo, "commit", "-q", "-am", "work")
        self.assertEqual(dirty, git(self.repo, "rev-parse", "HEAD^{tree}"))

    def test_a_linked_worktree_hashes_its_own_files(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        wt = os.path.join(os.path.realpath(holder.name), "wt")
        git(self.repo, "worktree", "add", "-q", "--detach", wt, "HEAD")
        self.assertEqual(scenarios.tree_hash(wt), git(wt, "rev-parse", "HEAD^{tree}"))
        write(wt, "a.txt", "changed in the worktree\n")
        changed = scenarios.tree_hash(wt)
        self.assertNotEqual(changed, self.hash())
        git(wt, "commit", "-q", "-am", "in worktree")
        self.assertEqual(changed, git(wt, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(self.hash(), git(self.repo, "rev-parse", "HEAD^{tree}"))  # the main checkout is untouched

    def test_a_subdirectory_of_the_repo_hashes_the_whole_tree(self):
        os.makedirs(os.path.join(self.repo, "pkg"))
        write(self.repo, "pkg/keep.txt", "keep\n", age=7200)
        write(self.repo, "pkg/edit.txt", "one\n", age=7200)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "more")
        write(self.repo, "pkg/edit.txt", "two\n")
        self.assertEqual(scenarios.tree_hash(os.path.join(self.repo, "pkg")), self.hash())

    def test_nothing_is_left_in_the_temp_dir(self):
        with tempfile.TemporaryDirectory() as private, mock.patch.object(tempfile, "tempdir", private):
            self.hash()
            self.assertEqual(os.listdir(private), [])

    def test_a_sparse_entry_absent_from_the_worktree_stays_in_the_hash(self):
        write(self.repo, "sparse.txt", "not checked out\n", age=7200)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "sparse")
        git(self.repo, "update-index", "--skip-worktree", "sparse.txt")
        os.remove(os.path.join(self.repo, "sparse.txt"))
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(self.hash(), git(self.repo, "rev-parse", "HEAD^{tree}"))

    def test_objects_reached_through_the_callers_alternates_are_still_reached(self):
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(os.path.realpath(d), "dst")
            git(self.repo, "clone", "-q", "--shared", self.repo, dst)
            alternates = os.path.join(dst, ".git", "objects", "info", "alternates")
            with open(alternates) as f:
                borrowed = f.read().strip()
            os.remove(alternates)
            with mock.patch.dict(os.environ, {"GIT_ALTERNATE_OBJECT_DIRECTORIES": borrowed}):
                old = time.time() - 7200
                os.utime(os.path.join(dst, "a.txt"), (old, old))
                git(dst, "update-index", "--refresh")
                self.assertEqual(scenarios.tree_hash(dst), git(self.repo, "rev-parse", "HEAD^{tree}"))

    def test_the_callers_git_environment_reaches_the_hash(self):
        clean = self.hash()
        write(self.repo, "scratch.tmp", "ignored by the user's own excludes file\n")
        with tempfile.NamedTemporaryFile("w", suffix=".ignore") as f:
            f.write("*.tmp\n")
            f.flush()
            env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.excludesFile", "GIT_CONFIG_VALUE_0": f.name}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(self.hash(), clean)
        self.assertNotEqual(self.hash(), clean)

    def test_git_warnings_do_not_leak_into_the_runners_output(self):
        inner = os.path.join(self.repo, "inner")
        os.mkdir(inner)
        git(inner, "init", "-q")
        git(inner, "commit", "-q", "--allow-empty", "-m", "embedded repo: git add warns about it")
        with fd_output() as out:
            got = self.hash()
        self.assertRegex(got, r"^[0-9a-f]{40}$")
        self.assertEqual(out[0], "")

    def test_a_tree_git_cannot_write_is_exit_3_with_gits_reason_on_stderr(self):
        real = subprocess.run

        def run(argv, **kw):
            if "write-tree" in argv:
                return subprocess.CompletedProcess(argv, 128, b"", b"fatal: git-write-tree: error building trees \xff\n")
            return real(argv, **kw)

        err, out = io.StringIO(), io.StringIO()
        with mock.patch.object(scenarios.subprocess, "run", run), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            self.hash()
        self.assertEqual(stop.exception.code, 3)
        self.assertEqual(err.getvalue(), "cannot hash the working tree: fatal: git-write-tree: error building trees \ufffd\n")
        self.assertEqual(out.getvalue(), "")

    def test_a_git_add_that_dies_is_exit_3_not_a_clean_hash(self):
        real = subprocess.run

        def run(argv, **kw):
            if "add" in argv:
                return subprocess.CompletedProcess(argv, 128, b"", b"fatal: add died\n")
            return real(argv, **kw)

        err = io.StringIO()
        with mock.patch.object(scenarios.subprocess, "run", run), contextlib.redirect_stderr(err), \
                self.assertRaises(SystemExit) as stop:
            self.hash()
        self.assertEqual((stop.exception.code, err.getvalue()), (3, "cannot hash the working tree: fatal: add died\n"))

    def test_the_callers_pathspec_settings_do_not_hide_a_new_file(self):
        clean = self.hash()
        write(self.repo, "stray.txt", "x\n")
        for var in ("GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS"):
            with self.subTest(var), mock.patch.dict(os.environ, {var: "1"}):
                self.assertNotEqual(self.hash(), clean)

    def test_untracked_python_bytecode_does_not_count(self):
        clean = self.hash()
        os.makedirs(os.path.join(self.repo, "pkg", "__pycache__"))
        write(self.repo, "pkg/__pycache__/m.cpython-312.pyc", "b\n")
        write(self.repo, "top.pyc", "b\n")
        write(self.repo, "pkg/old.pyo", "b\n")
        self.assertEqual(self.hash(), clean)
        self.assertEqual(scenarios.tree_hash(os.path.join(self.repo, "pkg")), clean)  # from a subdirectory too

    def test_a_tracked_bytecode_file_still_counts(self):
        write(self.repo, "t.pyc", "one\n", age=7200)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "tracked bytecode")
        clean = self.hash()
        write(self.repo, "t.pyc", "two\n")
        edited = self.hash()
        os.remove(os.path.join(self.repo, "t.pyc"))
        self.assertEqual(len({clean, edited, self.hash()}), 3)

    def test_a_file_that_is_not_bytecode_under_pycache_still_counts(self):
        clean = self.hash()
        os.makedirs(os.path.join(self.repo, "p", "__pycache__"))
        write(self.repo, "p/__pycache__/notes.txt", "x\n")
        self.assertNotEqual(self.hash(), clean)

    def test_a_tracked_edit_and_an_untracked_file_each_change_the_hash(self):
        clean = self.hash()
        write(self.repo, "a.txt", "two\n")
        edited = self.hash()
        self.assertNotEqual(edited, clean)
        write(self.repo, "new.txt", "n\n")
        self.assertNotEqual(self.hash(), edited)

    def test_a_same_size_edit_in_the_second_the_index_was_written_changes_the_hash(self):
        """Racy git: the edit keeps the size and the mtime second git recorded, and the index was written in that same
        second, so only re-reading the file shows it. git status re-reads it; the hash must too. The times are set,
        not waited for: the unit test cannot hit the second boundary by chance."""
        git(self.repo, "config", "core.trustctime", "false")  # a ctime cannot be set; this keeps it out of the compare
        t0, a = 1_700_000_000, os.path.join(self.repo, "a.txt")
        os.utime(a, (t0, t0))
        git(self.repo, "add", "-A")  # the entry now records mtime t0
        clean = self.hash()
        write(self.repo, "a.txt", "two\n")  # same size as "one\n"
        os.utime(a, (t0, t0))
        os.utime(os.path.join(self.repo, ".git", "index"), (t0, t0))  # the index was written in that second too
        edited = self.hash()  # before git status, which would rewrite the index and mark the entry for a re-read
        self.assertNotEqual(edited, clean)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "M a.txt")

    def test_an_ignored_file_does_not_count(self):
        write(self.repo, ".gitignore", "*.log\n")
        before = self.hash()
        write(self.repo, "debug.log", "noise\n")
        self.assertEqual(self.hash(), before)

    def test_hashing_writes_nothing_into_the_repo(self):
        write(self.repo, "new.txt", "n\n")
        before = (git(self.repo, "count-objects", "-v"), git(self.repo, "status", "--porcelain"))
        self.hash()
        self.assertEqual((git(self.repo, "count-objects", "-v"), git(self.repo, "status", "--porcelain")), before)

    def test_a_file_that_is_not_utf8_is_hashed(self):
        with open(os.path.join(self.repo, "latin.txt"), "wb") as f:
            f.write(b"caf\xe9\n")
        one = self.hash()
        with open(os.path.join(self.repo, "latin.txt"), "wb") as f:
            f.write(b"caf\xe9 two\n")
        self.assertRegex(one, r"^[0-9a-f]{40}$")
        self.assertNotEqual(self.hash(), one)

    def test_a_fresh_repo_with_no_commit_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            write(d, "f", "x\n")
            self.assertRegex(scenarios.tree_hash(d), r"^[0-9a-f]{40}$")

    def test_outside_a_git_repo_the_hash_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(scenarios.tree_hash(d), "")

    def test_repo_state_is_head_and_the_tree_hash(self):
        self.assertEqual(scenarios.repo_state(self.repo), (git(self.repo, "rev-parse", "HEAD"), self.hash()))

    def test_an_empty_commit_changes_the_repo_state_but_not_the_hash(self):
        before = scenarios.repo_state(self.repo)
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "by a scenario")
        after = scenarios.repo_state(self.repo)
        self.assertEqual(after[1], before[1])
        self.assertNotEqual(after[0], before[0])


class TestFind(unittest.TestCase):
    def test_scenarios_are_the_dirs_with_a_run_sh_parents_first_and_never_inside_fixtures(self):
        with tempfile.TemporaryDirectory() as repo:
            for d in ("a", "a/b", "a-x", "a/fixtures/sample-app", "notes"):
                os.makedirs(os.path.join(repo, ".ekit", "scenarios", d))
            for d in ("a", "a/b", "a-x", "a/fixtures/sample-app"):
                write(repo, f".ekit/scenarios/{d}/run.sh", "exit 0\n")
            write(repo, ".ekit/scenarios/notes/readme.txt", "not a scenario\n")
            self.assertEqual(scenarios.find(repo), ["a", "a/b", "a-x"])


    def test_a_run_py_or_a_run_ps1_makes_a_scenario_too_and_another_python_file_does_not(self):
        with tempfile.TemporaryDirectory() as repo:
            for d, f in (("py", "run.py"), ("ps", "run.ps1"), ("sh", "run.sh"), ("helper", "drive.py"),
                         ("py/fixtures/app", "run.py")):
                os.makedirs(os.path.join(repo, ".ekit", "scenarios", d))
                write(repo, f".ekit/scenarios/{d}/{f}", "\n")
            self.assertEqual(scenarios.find(repo), ["ps", "py", "sh"])

    def test_no_scenarios_names_every_run_file_in_the_layout(self):
        with tempfile.TemporaryDirectory() as repo:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(scenarios.cmd_run(repo), 2)
        self.assertEqual(out.getvalue(),
                         "no scenarios found. expected layout: .ekit/scenarios/<slug>/SCENARIO.md + run.sh, run.py or "
                         "run.ps1 (one of them)\n")


class TestRun(unittest.TestCase):
    """cmd_run in-process: one scenario in a repo, results under EKIT_STATE."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(self.tmp.name), "repo")
        self.state = os.path.join(os.path.realpath(self.tmp.name), "state")
        os.makedirs(os.path.join(self.repo, ".ekit", "scenarios", "one"))
        git(self.repo, "init", "-q")
        write(self.repo, ".ekit/scenarios/one/SCENARIO.md", "- story: s\n")
        p = mock.patch.dict(os.environ, {"EKIT_STATE": self.state})
        p.start()
        self.addCleanup(p.stop)

    def run_all(self, script, run_file="run.sh"):
        write(self.repo, f".ekit/scenarios/one/{run_file}", script)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "scenario")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            failed = scenarios.cmd_run(self.repo)
        with open(os.path.join(scenarios.outdir(self.repo), "results.json")) as f:
            return failed, out.getvalue(), json.load(f)

    def test_a_pass_is_recorded_for_the_tree_that_was_run(self):
        failed, out, doc = self.run_all("exit 0\n")
        self.assertIs(failed, False)
        self.assertEqual(out, "PASS one\nPASS: 1/1 scenarios\n")
        self.assertEqual((doc["verdict"], doc["tree"]), ("PASS", scenarios.tree_hash(self.repo)))

    def test_a_run_py_scenario_passes_and_fails_as_a_run_sh_one_does(self):
        failed, out, doc = self.run_all("import sys\nprint('hi')\nsys.exit(0)\n", "run.py")
        self.assertEqual((failed, out, doc["verdict"]), (False, "PASS one\nPASS: 1/1 scenarios\n", "PASS"))
        failed, out, doc = self.run_all("import sys\nprint('oops', file=sys.stderr)\nsys.exit(3)\n", "run.py")
        self.assertEqual((failed, out, doc["verdict"]), (True, "FAIL one: exit 3\nFAIL: 0/1 scenarios\n", "FAIL"))
        self.assertEqual(doc["scenarios"][0]["exit"], 3)

    def test_run_py_runs_with_the_python_running_the_runner_and_the_scenario_env(self):
        self.run_all("import json, os, sys\n"
                     "keys = ('EKIT_REPO', 'EKIT_SCENARIO_DIR', 'EKIT_PARENT_DIR', 'PYTHONDONTWRITEBYTECODE')\n"
                     "json.dump([sys.executable, os.getcwd()] + [os.environ[k] for k in keys],\n"
                     "          open(os.path.join(os.environ['EKIT_STATE'], 'seen.json'), 'w'))\n", "run.py")
        with open(os.path.join(self.state, "seen.json")) as f:
            exe, cwd, repo, d, parent, nobytecode = json.load(f)
        self.assertEqual((os.path.abspath(exe), repo, d, parent, nobytecode),  # abspath: the same file, `..` or not
                         (os.path.abspath(sys.executable), self.repo, os.path.join(self.repo, ".ekit", "scenarios", "one"), "", "1"))
        self.assertFalse(os.path.realpath(cwd).startswith(self.repo))

    def test_a_run_clears_old_transcripts_of_other_trees_and_keeps_its_own(self):
        write(self.repo, ".ekit/scenarios/one/run.sh", "exit 0\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "scenario")
        other = os.path.join(scenarios.outdir(self.repo), "0" * 40)
        os.makedirs(other)
        # a clock a month ahead: every transcript dir is past the keep window, this run's own included
        ahead = time.time() + 30 * 86400
        with mock.patch.object(scenarios.time, "time", lambda: ahead), contextlib.redirect_stdout(io.StringIO()):
            scenarios.cmd_run(self.repo)
        tree = scenarios.tree_hash(self.repo)
        self.assertFalse(os.path.exists(other))
        self.assertEqual(os.listdir(os.path.join(scenarios.outdir(self.repo), tree)), ["one.log"])

    def test_a_child_run_alone_still_gets_its_parents_dir(self):
        os.makedirs(os.path.join(self.repo, ".ekit", "scenarios", "one", "kid"))
        write(self.repo, ".ekit/scenarios/one/run.sh", "exit 0\n")
        write(self.repo, ".ekit/scenarios/one/kid/SCENARIO.md", "- story: s\n")
        write(self.repo, ".ekit/scenarios/one/kid/run.sh", 'printf %s "$EKIT_PARENT_DIR" > "$EKIT_STATE/parent"\n')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "scenarios")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            scenarios.cmd_run(self.repo, "one/kid")
        self.assertEqual(out.getvalue(), "PASS one/kid\nPASS: 1/1 scenarios\n")
        with open(os.path.join(self.state, "parent")) as f:
            self.assertEqual(f.read(), os.path.join(self.repo, ".ekit", "scenarios", "one"))

    def test_a_file_saved_to_the_artifact_dir_is_kept_beside_the_transcript_and_listed(self):
        failed, _, doc = self.run_all('mkdir -p "$EKIT_ARTIFACT_DIR/shots"; echo png > "$EKIT_ARTIFACT_DIR/shots/home.png"\n')
        art = os.path.join(scenarios.outdir(self.repo), scenarios.tree_hash(self.repo), "one")
        self.assertIs(failed, False)
        self.assertEqual(doc["scenarios"][0]["artifacts"], [os.path.join(art, "shots", "home.png")])
        with open(os.path.join(art, "shots", "home.png")) as f:
            self.assertEqual(f.read(), "png\n")

    def test_a_failing_scenario_keeps_its_artifacts(self):
        failed, _, doc = self.run_all('echo png > "$EKIT_ARTIFACT_DIR/broken.png"; exit 1\n')
        art = os.path.join(scenarios.outdir(self.repo), scenarios.tree_hash(self.repo), "one")
        self.assertIs(failed, True)
        self.assertEqual(doc["scenarios"][0]["artifacts"], [os.path.join(art, "broken.png")])

    def test_a_rerun_on_the_same_tree_lists_only_its_own_artifacts(self):
        write(self.repo, ".ekit/scenarios/one/run.sh",
              'if [ -e "$EKIT_STATE/second" ]; then echo b > "$EKIT_ARTIFACT_DIR/b.png"; '
              'else echo a > "$EKIT_ARTIFACT_DIR/a.png"; touch "$EKIT_STATE/second"; fi\n')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "scenario")
        with contextlib.redirect_stdout(io.StringIO()):
            scenarios.cmd_run(self.repo)
            scenarios.cmd_run(self.repo)
        art = os.path.join(scenarios.outdir(self.repo), scenarios.tree_hash(self.repo), "one")
        with open(os.path.join(scenarios.outdir(self.repo), "results.json")) as f:
            self.assertEqual(json.load(f)["scenarios"][0]["artifacts"], [os.path.join(art, "b.png")])
        self.assertEqual(os.listdir(art), ["b.png"])

    def test_a_child_scenarios_artifacts_sit_beside_its_own_transcript(self):
        os.makedirs(os.path.join(self.repo, ".ekit", "scenarios", "one", "kid"))
        write(self.repo, ".ekit/scenarios/one/run.sh", "exit 0\n")
        write(self.repo, ".ekit/scenarios/one/kid/SCENARIO.md", "- story: s\n")
        write(self.repo, ".ekit/scenarios/one/kid/run.sh", 'echo png > "$EKIT_ARTIFACT_DIR/kid.png"\n')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "scenarios")
        with contextlib.redirect_stdout(io.StringIO()):
            scenarios.cmd_run(self.repo)
        tdir = os.path.join(scenarios.outdir(self.repo), scenarios.tree_hash(self.repo))
        with open(os.path.join(scenarios.outdir(self.repo), "results.json")) as f:
            kid = json.load(f)["scenarios"][1]
        self.assertEqual((kid["transcript"], kid["artifacts"]),
                         (os.path.join(tdir, "one__kid.log"), [os.path.join(tdir, "one__kid", "kid.png")]))

    def test_run_sh_gets_its_own_scenario_dir(self):
        self.run_all('printf %s "$EKIT_SCENARIO_DIR" > "$EKIT_STATE/dir"\n')
        with open(os.path.join(self.state, "dir")) as f:
            self.assertEqual(f.read(), os.path.join(self.repo, ".ekit", "scenarios", "one"))

    def test_a_scenario_that_removes_its_artifact_dir_still_passes(self):
        failed, out, doc = self.run_all('rmdir "$EKIT_ARTIFACT_DIR"\n')
        self.assertEqual((failed, out), (False, "PASS one\nPASS: 1/1 scenarios\n"))
        self.assertNotIn("artifacts", doc["scenarios"][0])

    def test_a_scenario_that_saves_nothing_has_no_artifacts_entry(self):
        _, _, doc = self.run_all("exit 0\n")
        self.assertNotIn("artifacts", doc["scenarios"][0])

    def test_a_scenario_that_commits_in_the_repo_fails_the_run(self):
        failed, out, doc = self.run_all('git -C "$EKIT_REPO" -c user.email=t@t -c user.name=t commit -q --allow-empty -m x\n')
        self.assertIs(failed, True)
        self.assertEqual(doc["verdict"], "FAIL")
        self.assertEqual(doc["reason"], "scenarios modified the repo: run in the temp cwd")
        self.assertIn("FAIL: scenarios modified the repo: run in the temp cwd\n", out)

    def main(self, script, *args, run_file="run.sh"):
        """the runner's entry, in-process: (exit code, stdout, results.json)"""
        write(self.repo, f".ekit/scenarios/one/{run_file}", script)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "scenario")  # a rerun of the same script: same tree
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as e:
            scenarios.main(["--repo", self.repo, "run", *args])
        with open(os.path.join(scenarios.outdir(self.repo), "results.json")) as f:
            return int(e.exception.code or 0), out.getvalue(), json.load(f)

    def test_python_bytecode_left_in_the_repo_is_not_a_repo_change(self):
        # the repo has no .gitignore: bytecode is untracked like any file, yet it is the interpreter's, not the scenario's
        code, out, doc = self.main('mkdir -p "$EKIT_REPO/pkg/__pycache__"\n'
                                   'echo b > "$EKIT_REPO/pkg/__pycache__/m.cpython-312.pyc"; echo b > "$EKIT_REPO/m.pyc"\n')
        self.assertEqual((code, out, doc["verdict"]), (0, "PASS one\nPASS: 1/1 scenarios\n", "PASS"))

    def test_a_real_untracked_file_beside_bytecode_still_fails_the_run(self):
        code, out, doc = self.main('mkdir -p "$EKIT_REPO/__pycache__"; echo b > "$EKIT_REPO/__pycache__/m.pyc"\n'
                                   'echo x > "$EKIT_REPO/stray.txt"\n')
        self.assertEqual((code, doc["reason"]), (1, "scenarios modified the repo: run in the temp cwd"))

    def test_scenarios_run_with_bytecode_writes_off(self):
        with mock.patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": ""}):
            code, out, _ = self.main('[ "$PYTHONDONTWRITEBYTECODE" = 1 ] || { echo "bytecode on" >&2; exit 1; }\n')
        self.assertEqual((code, out), (0, "PASS one\nPASS: 1/1 scenarios\n"))

    def test_a_failed_transcript_stays_until_the_same_scenario_fails_again(self):
        # fails on the 1st and 3rd run, passes on the 2nd: a pass on the same tree rewrites one.log, not the failure kept
        script = ('n=$(cat "$EKIT_STATE/n" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$EKIT_STATE/n"\n'
                  'echo "run $n"; [ $n = 2 ]\n')
        self.main(script)
        code, _, doc = self.main(script)
        self.assertEqual((code, doc["verdict"]), (0, "PASS"))
        kept = os.path.join(scenarios.outdir(self.repo), "failed", "one.log")
        with open(kept) as f:
            self.assertIn("--- stdout ---\nrun 1\n", f.read())
        code, _, doc = self.main(script)
        self.assertEqual((code, doc["scenarios"][0]["failed_transcript"]), (1, kept))
        with open(kept) as f:
            text = f.read()
        self.assertIn("--- stdout ---\nrun 3\n", text)
        self.assertNotIn("run 1\n", text)

    def test_kept_failures_of_a_child_and_a_look_alike_id_do_not_overwrite_each_other(self):
        for d, word in (("one/b", "child"), ("one__b", "look-alike")):
            os.makedirs(os.path.join(self.repo, ".ekit", "scenarios", d))
            write(self.repo, f".ekit/scenarios/{d}/SCENARIO.md", "- story: s\n")
            write(self.repo, f".ekit/scenarios/{d}/run.sh", f"echo {word}; exit 1\n")
        _, _, doc = self.main("exit 0\n")
        kept = {r["id"]: r["failed_transcript"] for r in doc["scenarios"] if r.get("reason")}
        self.assertEqual(sorted(kept), ["one/b", "one__b"])
        self.assertNotEqual(kept["one/b"], kept["one__b"])
        for sid, word in (("one/b", "child"), ("one__b", "look-alike")):
            with open(kept[sid]) as f:
                self.assertIn(f"--- stdout ---\n{word}\n", f.read())

    def test_a_run_failed_only_by_a_repo_change_keeps_a_note_naming_the_change(self):
        code, _, doc = self.main('echo x > "$EKIT_REPO/stray.txt"\n')
        self.assertEqual((code, doc["scenarios"][0].get("reason")), (1, None))
        note = doc["failed_transcript"]
        self.assertEqual(os.path.dirname(note), os.path.join(scenarios.outdir(self.repo), "failed"))
        with open(note) as f:
            self.assertIn("?? stray.txt\n", f.read())

    def add_exits(self, rc):
        """git add, faked at the subprocess boundary, exits rc; every other git call is real"""
        real = subprocess.run

        def run(argv, **kw):
            if argv[3:5] == ["add", "-A"]:
                return subprocess.CompletedProcess(argv, rc, b"", b"error: unable to index file 'x'\n")
            return real(argv, **kw)
        return mock.patch.object(scenarios.subprocess, "run", run)

    def test_a_git_add_that_skipped_a_file_still_hashes_and_passes(self):
        with self.add_exits(1):
            code, out, doc = self.main("exit 0\n")
        self.assertEqual((code, out, doc["verdict"]), (0, "PASS one\nPASS: 1/1 scenarios\n", "PASS"))

    def test_a_git_add_that_dies_with_exit_2_or_128_cannot_hash(self):
        write(self.repo, ".ekit/scenarios/one/run.sh", "exit 0\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "scenario")
        for rc in (2, 128):
            err = io.StringIO()
            with self.subTest(rc), self.add_exits(rc), contextlib.redirect_stderr(err), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as e:
                scenarios.main(["--repo", self.repo, "run"])
            self.assertEqual((e.exception.code, err.getvalue()),
                             (3, "cannot hash the working tree: error: unable to index file 'x'\n"))

    def test_a_failed_transcript_holds_stdout_stderr_and_the_exit_code(self):
        _, _, doc = self.main("echo out; echo err >&2; exit 1\n")
        r = doc["scenarios"][0]
        for path in (r["transcript"], r["failed_transcript"]):
            with open(path, "rb") as f:
                self.assertTrue(f.read().endswith(b"\n--- stdout ---\nout\n\n--- stderr ---\nerr\n\n--- exit: 1 ---\n"))

    def test_a_timed_out_transcript_says_timeout(self):
        with mock.patch.dict(os.environ, {"EKIT_SCENARIO_TIMEOUT": "1"}):
            code, _, doc = self.main("echo out; echo err >&2; sleep 30\n")
        r = doc["scenarios"][0]
        self.assertEqual((code, r["reason"]), (1, "timeout after 1s"))
        with open(r["failed_transcript"], "rb") as f:
            self.assertTrue(f.read().endswith(b"\n--- stdout ---\nout\n\n--- stderr ---\nerr\n\n--- exit: timeout ---\n"))

    def test_a_timeout_stops_the_scenarios_children_too(self):
        """the whole process tree goes, not only bash: a child left behind would hold the run's pipes open"""
        mark = os.path.join(os.path.realpath(self.tmp.name), "late")
        with mock.patch.dict(os.environ, {"EKIT_SCENARIO_TIMEOUT": "1"}):
            t0 = time.time()
            code, out, doc = self.main(f"(sleep 4; echo x > '{mark.replace(os.sep, '/')}') &\nsleep 30\n")
        self.assertEqual((code, doc["scenarios"][0]["reason"]), (1, "timeout after 1s"))
        self.assertLess(time.time() - t0, 20)
        time.sleep(5)
        self.assertFalse(os.path.exists(mark))

    def test_what_a_timed_out_scenario_printed_stays_even_when_a_child_escapes_the_stop(self):
        """a child the stop does not reach keeps the scenario's output open: the transcript still holds what the
        scenario printed, and the run does not wait for that child"""
        escaped = []

        def stop_nothing(p):
            escaped.append(p)  # as if the tree kill missed it

        with mock.patch.dict(os.environ, {"EKIT_SCENARIO_TIMEOUT": "1"}), \
                mock.patch.object(scenarios.shells, "kill_tree", side_effect=stop_nothing):
            t0 = time.time()
            code, _, doc = self.main("echo early; echo err >&2; sleep 30\n")
        took = time.time() - t0
        for p in escaped:
            p.kill()
        r = doc["scenarios"][0]
        self.assertEqual((code, r["reason"]), (1, "timeout after 1s"))
        self.assertLess(took, 25)
        with open(r["failed_transcript"], "rb") as f:
            text = f.read()
        self.assertIn(b"--- stdout ---\nearly\n", text)
        self.assertIn(b"--- stderr ---\nerr\n", text)

    def test_a_background_child_does_not_outlive_its_scenario(self):
        """`server &` then exit 0: the scenario passes, and its child is stopped with it (a server would keep its
        port); a foreground hang still times out"""
        mark = os.path.join(os.path.realpath(self.tmp.name), "late").replace(os.sep, "/")
        code, out, doc = self.main(f"(sleep 3; echo x > '{mark}') &\nexit 0\n")
        self.assertEqual((code, doc["scenarios"][0].get("reason")), (0, None))
        time.sleep(5)
        self.assertFalse(os.path.exists(mark))
        with mock.patch.dict(os.environ, {"EKIT_SCENARIO_TIMEOUT": "1"}):
            code, _, doc = self.main("sleep 30\n")
        self.assertEqual((code, doc["scenarios"][0]["reason"]), (1, "timeout after 1s"))

    def test_a_run_py_timeout_stops_its_whole_tree_a_background_child_included_and_is_a_fail(self):
        mark = os.path.join(os.path.realpath(self.tmp.name), "late")
        child = f"import time; time.sleep(4); open({mark!r}, 'w')"
        script = (f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {child!r}])\n"
                  "print('started', flush=True)\ntime.sleep(30)\n")
        with mock.patch.dict(os.environ, {"EKIT_SCENARIO_TIMEOUT": "1"}):
            t0 = time.time()
            code, out, doc = self.main(script, run_file="run.py")
        self.assertEqual((code, out, doc["scenarios"][0]["reason"]),
                         (1, "FAIL one: timeout after 1s\nFAIL: 0/1 scenarios\n", "timeout after 1s"))
        self.assertLess(time.time() - t0, 20)
        with open(doc["scenarios"][0]["failed_transcript"], "rb") as f:
            text = f.read()
        self.assertTrue(text.startswith(b"command: python run.py\n"), text)
        self.assertTrue(text.endswith(b"\n--- stdout ---\nstarted\n\n--- stderr ---\n\n--- exit: timeout ---\n"), text)
        time.sleep(5)
        self.assertFalse(os.path.exists(mark))

    def test_a_run_py_background_child_does_not_outlive_its_scenario(self):
        mark = os.path.join(os.path.realpath(self.tmp.name), "late")
        child = f"import time; time.sleep(3); open({mark!r}, 'w')"
        code, _, doc = self.main(f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\n",
                                 run_file="run.py")
        self.assertEqual((code, doc["scenarios"][0].get("reason")), (0, None))
        time.sleep(5)
        self.assertFalse(os.path.exists(mark))

    def test_a_run_py_keeps_its_failed_transcript_and_lists_its_artifacts(self):
        code, _, doc = self.main("import os, sys\n"
                                 "open(os.path.join(os.environ['EKIT_ARTIFACT_DIR'], 'shot.png'), 'w').write('png')\n"
                                 "print('out'); print('err', file=sys.stderr); sys.exit(4)\n", run_file="run.py")
        r = doc["scenarios"][0]
        art = os.path.join(scenarios.outdir(self.repo), scenarios.tree_hash(self.repo), "one")
        self.assertEqual((code, r["reason"], r["artifacts"]), (1, "exit 4", [os.path.join(art, "shot.png")]))
        with open(r["failed_transcript"], "rb") as f:
            text = f.read()
        self.assertTrue(text.startswith(b"command: python run.py\n"), text)
        self.assertTrue(text.endswith(b"\n--- stdout ---\nout\n\n--- stderr ---\nerr\n\n--- exit: 4 ---\n"), text)

    def test_python_bytecode_a_run_py_leaves_in_the_repo_is_not_a_repo_change(self):
        code, out, doc = self.main("import os\nd = os.path.join(os.environ['EKIT_REPO'], '__pycache__')\n"
                                   "os.makedirs(d)\nopen(os.path.join(d, 'm.cpython-312.pyc'), 'w').write('b')\n",
                                   run_file="run.py")
        self.assertEqual((code, out, doc["verdict"]), (0, "PASS one\nPASS: 1/1 scenarios\n", "PASS"))
        code, _, doc = self.main("import os\nopen(os.path.join(os.environ['EKIT_REPO'], 'stray.txt'), 'w')\n",
                                 run_file="run.py")
        self.assertEqual((code, doc["reason"]), (1, "scenarios modified the repo: run in the temp cwd"))

    def test_a_repo_path_that_does_not_exist_is_named_not_no_scenarios(self):
        missing = os.path.join(os.path.realpath(self.tmp.name), "nope")
        err = io.StringIO()
        for verb in ("run", "check", "tree-hash"):
            with self.subTest(verb=verb), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as e:
                scenarios.main(["--repo", missing, verb])
            self.assertEqual(e.exception.code, 2)
        self.assertEqual(err.getvalue(), f"scenarios.py: no such directory: {missing}\n" * 3)

    def test_a_machine_without_bash_fails_the_scenario_naming_why(self):
        """#59: not run here (env), never PASS and never a plain FAIL"""
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            code, out, doc = self.main("exit 0\n")
        self.assertEqual((code, doc["scenarios"][0]["reason"]), (1, "bash is not on this machine (env)"))
        self.assertEqual((out, doc["verdict"]),
                         ("NOT-RUN one: bash is not on this machine (env)\nNOT-RUN: 0/1 scenarios\n", "NOT-RUN"))

    def test_a_folder_with_two_or_more_run_files_is_an_error_naming_them_all(self):
        """#59: never a silent pick, and not an env reason (nothing runs, whatever this host has)"""
        mark = os.path.join(self.state, "ran")
        write(self.repo, ".ekit/scenarios/one/run.py", f"open({mark!r}, 'w')\n")
        code, out, doc = self.main(f"touch '{mark}'\n")
        self.assertEqual((code, out, doc["verdict"]),
                         (1, "FAIL one: more than one run file (run.py, run.sh): keep one\nFAIL: 0/1 scenarios\n", "FAIL"))
        self.assertFalse(os.path.exists(mark))
        self.assertEqual(doc["scenarios"][0]["exit"], 1)
        with open(doc["scenarios"][0]["transcript"]) as f:
            self.assertEqual(f.read(), f"command: none\nscenario: {os.path.join(self.repo, '.ekit', 'scenarios', 'one')}\n"
                                       "cwd: \n--- stdout ---\n\n--- stderr ---\n\n--- exit: 1 ---\n")
        self.assertEqual(self.check(), (1, "last run FAIL\n"))
        write(self.repo, ".ekit/scenarios/one/run.ps1", "exit 0\n")
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            code, out, doc = self.main("exit 0\n")
        self.assertEqual((code, doc["scenarios"][0]["reason"]),
                         (1, "more than one run file (run.py, run.sh, run.ps1): keep one"))

    def test_a_directory_named_like_a_run_file_is_not_a_second_run_file(self):
        d = os.path.join(self.repo, ".ekit", "scenarios", "one")
        os.makedirs(os.path.join(d, "run.py"))
        write(self.repo, ".ekit/scenarios/one/run.py/notes.txt", "data\n")
        code, out, _ = self.main("exit 0\n")
        self.assertEqual((code, out), (0, "PASS one\nPASS: 1/1 scenarios\n"))
        os.makedirs(os.path.join(self.repo, "data"))
        symlink(self, os.path.join(self.repo, "data"), os.path.join(d, "run.ps1"))  # a link to a directory
        code, out, _ = self.main("exit 0\n")
        self.assertEqual((code, out), (0, "PASS one\nPASS: 1/1 scenarios\n"))

    def test_can_fail_on_a_folder_with_two_run_files_is_the_error_not_a_proof(self):
        write(self.repo, ".ekit/scenarios/one/run.py", "raise SystemExit(1)\n")
        code, out = self.can_fail("exit 1\n")
        self.assertEqual((code, out.getvalue()), (2, "ERROR one: more than one run file (run.py, run.sh): keep one\n"))

    def fake_shell(self, name):
        """an executable `name` that records its arguments in $EKIT_STATE/argv.json and exits 7"""
        bin_ = os.path.join(os.path.realpath(self.tmp.name), "bin")
        os.makedirs(bin_, exist_ok=True)
        rec = os.path.join(bin_, "rec.py")
        write(bin_, "rec.py", "import json, os, sys\n"
                              "json.dump(sys.argv[1:], open(os.path.join(os.environ['EKIT_STATE'], 'argv.json'), 'w'))\n"
                              "sys.exit(7)\n")
        if os.name == "nt":
            path = os.path.join(bin_, name + ".cmd")
            write(bin_, name + ".cmd", f'@"{sys.executable}" "{rec}" %*\r\n@exit /b %ERRORLEVEL%\r\n')
        else:
            path = os.path.join(bin_, name)
            write(bin_, name, f'#!/bin/sh\nexec "{sys.executable}" "{rec}" "$@"\n')
            os.chmod(path, 0o755)
        return path

    # PowerShell's -File exits 0 on normal termination whatever the last native command gave (about_Pwsh): the
    # script is called from -Command and its last exit code passed on, as bash passes on its last status
    # one line: cmd.exe (the .cmd fake on Windows) ends a command line at a line feed
    PS_LINE = ("$global:LASTEXITCODE = 0; & '{}'; if (-not $?) {{ if ($LASTEXITCODE) {{ exit $LASTEXITCODE }} "
               "else {{ exit 1 }} }}; exit $LASTEXITCODE")

    def test_a_run_ps1_runs_in_pwsh_else_windows_powershell_its_last_exit_code_kept(self):
        script = os.path.join(self.repo, ".ekit", "scenarios", "one", "run.ps1")
        for name in ("pwsh", "powershell"):
            with self.subTest(shell=name):
                fake = self.fake_shell(name)
                with mock.patch.object(scenarios.shells, "find", lambda n, fake=fake, name=name: fake if n == name else None):
                    code, out, doc = self.main("git -C no-such-dir status\n", run_file="run.ps1")
                self.assertEqual((code, out), (1, "FAIL one: exit 7\nFAIL: 0/1 scenarios\n"))
                with open(os.path.join(self.state, "argv.json")) as f:
                    self.assertEqual(json.load(f), ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                                    "-Command", self.PS_LINE.format(script)])
                with open(doc["scenarios"][0]["transcript"]) as f:
                    self.assertTrue(f.read().startswith(f"command: {name} run.ps1\n"))

    def test_a_run_ps1_path_with_quotes_is_one_powershell_literal(self):
        """a ' (or a typographic one, which PowerShell reads as a quote too) is doubled inside the '...' literal"""
        d = os.path.join(self.repo, ".ekit", "scenarios", "it's \u2019q\u2018 \u201alow\u201b $x")  # ' ‘ ’ ‚ ‛: IsSingleQuote
        os.makedirs(d)
        write(d, "SCENARIO.md", "- story: s\n")
        write(d, "run.ps1", "exit 0\n")
        fake = self.fake_shell("pwsh")
        with mock.patch.object(scenarios.shells, "find", lambda n: fake if n == "pwsh" else None):
            self.main("exit 0\n")
        with open(os.path.join(self.state, "argv.json")) as f:
            line = json.load(f)[-1]
        quoted = os.path.join(d, "run.ps1")
        for q in "'\u2018\u2019\u201a\u201b":
            quoted = quoted.replace(q, q * 2)
        self.assertEqual(line, self.PS_LINE.format(quoted))

    def test_a_run_ps1_path_with_wildcard_characters_is_called_literally(self):
        """`&` looks a path up as a wildcard pattern: [ ] * ? (and then a backtick) are escaped with a backtick, which
        the '...' literal keeps; a path with none of them is passed as it is, a backtick included"""
        cases = [("edge[1]", "edge`[1`]"), ("tick`a", "tick`a")]
        if os.name != "nt":  # Windows forbids * and ? in a file name
            cases.append(("a*b?`c", "a`*b`?``c"))
        fake = self.fake_shell("pwsh")
        for sid, escaped in cases:
            with self.subTest(sid=sid):
                d = os.path.join(self.repo, ".ekit", "scenarios", sid)
                os.makedirs(d)
                write(d, "SCENARIO.md", "- story: s\n")
                write(d, "run.ps1", "exit 0\n")
                with mock.patch.object(scenarios.shells, "find", lambda n: fake if n == "pwsh" else None):
                    self.main("exit 0\n", sid)
                with open(os.path.join(self.state, "argv.json")) as f:
                    line = json.load(f)[-1]
                self.assertEqual(line, self.PS_LINE.format(os.path.join(self.repo, ".ekit", "scenarios", escaped,
                                                                        "run.ps1")))

    def test_a_machine_without_powershell_does_not_run_a_run_ps1(self):
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            code, out, doc = self.main("exit 0\n", run_file="run.ps1")
        self.assertEqual((code, out, doc["verdict"]),
                         (1, "NOT-RUN one: PowerShell is not on this machine (env)\nNOT-RUN: 0/1 scenarios\n",
                          "NOT-RUN"))
        self.assertEqual(self.check(), (1, "cannot run here: one: PowerShell is not on this machine (env)\n"))

    def ps_beside(self):
        os.makedirs(os.path.join(self.repo, ".ekit", "scenarios", "ps"))
        write(self.repo, ".ekit/scenarios/ps/SCENARIO.md", "- story: s\n")
        write(self.repo, ".ekit/scenarios/ps/run.ps1", "exit 0\n")

    def test_a_run_with_a_not_run_scenario_on_files_changed_since_reads_stale_not_cannot_run_here(self):
        """the files changed after the run: what the run.py would do now is unknown, so it is no host debt"""
        self.ps_beside()
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            code, out, doc = self.main("pass\n", run_file="run.py")
        self.assertEqual((code, doc["verdict"]), (1, "NOT-RUN"))
        write(self.repo, ".ekit/scenarios/one/run.py", "raise SystemExit(1)\n")
        self.assertEqual(self.check(), (1, "stale: tree changed since run\n"))

    def test_a_filtered_run_of_a_not_run_scenario_reads_partial_not_cannot_run_here(self):
        self.ps_beside()
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            code, out, _ = self.main("raise SystemExit(1)\n", "ps", run_file="run.py")
        self.assertEqual((code, out), (1, "NOT-RUN ps: PowerShell is not on this machine (env)\nNOT-RUN: 0/1 scenarios\n"))
        self.assertEqual(self.check(), (1, "partial run: only 'ps' was run; run all scenarios\n"))

    def test_a_scenario_this_host_cannot_run_beside_a_real_failure_is_a_failed_run(self):
        os.makedirs(os.path.join(self.repo, ".ekit", "scenarios", "two"))
        write(self.repo, ".ekit/scenarios/two/SCENARIO.md", "- story: s\n")
        write(self.repo, ".ekit/scenarios/two/run.py", "raise SystemExit(2)\n")
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            code, out, doc = self.main("exit 0\n")
        self.assertEqual((code, out, doc["verdict"]),
                         (1, "NOT-RUN one: bash is not on this machine (env)\nFAIL two: exit 2\nFAIL: 0/2 scenarios\n",
                          "FAIL"))
        self.assertEqual(self.check(), (1, "last run FAIL\n"))

    def test_a_failed_assert_in_a_run_py_fails_even_when_the_caller_strips_asserts(self):
        for level in ("1", "2"):
            with self.subTest(PYTHONOPTIMIZE=level), mock.patch.dict(os.environ, {"PYTHONOPTIMIZE": level}):
                code, out, _ = self.main("assert False, 'broken'\n", run_file="run.py")
            self.assertEqual((code, out), (1, "FAIL one: exit 1\nFAIL: 0/1 scenarios\n"))

    def test_a_python_that_cannot_name_its_own_executable_does_not_run_a_run_py(self):
        with mock.patch.object(scenarios.sys, "executable", ""):
            code, out, doc = self.main("pass\n", run_file="run.py")
        self.assertEqual((code, out), (1, "NOT-RUN one: Python is not on this machine (env)\nNOT-RUN: 0/1 scenarios\n"))

    def test_a_dangling_run_py_link_is_the_scenario_and_fails_as_itself(self):
        d = os.path.join(self.repo, ".ekit", "scenarios", "one")
        symlink(self, os.path.join(d, "gone.py"), os.path.join(d, "run.py"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertIs(scenarios.cmd_run(self.repo), True)
        self.assertEqual(out.getvalue(), "FAIL one: exit 2\nFAIL: 0/1 scenarios\n")

    def test_a_run_py_needs_no_shell(self):
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            code, out, doc = self.main("print('no shell needed')\n", run_file="run.py")
        self.assertEqual((code, out, doc["verdict"]), (0, "PASS one\nPASS: 1/1 scenarios\n", "PASS"))

    def check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as e:
            scenarios.main(["--repo", self.repo, "check"])
        return e.exception.code, out.getvalue()

    def test_check_after_a_run_this_host_could_not_do_says_it_cannot_run_here(self):
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            self.main("exit 0\n")
        self.assertEqual(self.check(), (1, "cannot run here: one: bash is not on this machine (env)\n"))

    def test_check_after_a_real_failure_is_a_failed_run(self):
        self.main("exit 1\n")
        self.assertEqual(self.check(), (1, "last run FAIL\n"))
        self.main("exit 0\n")
        self.assertEqual(self.check(), (0, ""))

    def can_fail(self, script, stdout=None, run_file="run.sh"):
        """`can-fail HEAD` in-process: (exit code, what it printed). stdout: the stream it writes to."""
        write(self.repo, f".ekit/scenarios/one/{run_file}", script)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "scenario")
        out = stdout or io.StringIO()
        with mock.patch("sys.stdout", out), self.assertRaises(SystemExit) as e:
            scenarios.main(["--repo", self.repo, "can-fail", "HEAD"])
        return int(e.exception.code or 0), out

    def test_can_fail_on_a_host_without_bash_is_n_a_not_a_pass(self):
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            code, out = self.can_fail("exit 0\n")
        self.assertEqual((code, out.getvalue()), (4, "N/A one: bash is not on this machine (env)\n"))

    def test_can_fail_reads_the_same_for_every_run_file(self):
        for run_file, passes, fails in (("run.py", "pass\n", "raise SystemExit(1)\n"), ("run.sh", "exit 0\n", "exit 1\n")):
            with self.subTest(run_file=run_file):
                for other in RUN_FILES:
                    with contextlib.suppress(FileNotFoundError):
                        os.remove(os.path.join(self.repo, ".ekit", "scenarios", "one", other))
                code, out = self.can_fail(fails, run_file=run_file)
                self.assertEqual((code, out.getvalue()), (0, "CAN-FAIL ✓ one\n"))
                code, out = self.can_fail(passes, run_file=run_file)
                self.assertEqual((code, out.getvalue()), (1, "CANNOT FAIL one: passes on baseline HEAD\n"))
        os.remove(os.path.join(self.repo, ".ekit", "scenarios", "one", "run.sh"))
        with mock.patch.object(scenarios.shells, "find", return_value=None):
            code, out = self.can_fail("exit 0\n", run_file="run.ps1")
        self.assertEqual((code, out.getvalue()), (4, "N/A one: PowerShell is not on this machine (env)\n"))

    def test_can_fail_writes_its_mark_to_a_windows_pipe(self):
        """a pipe on Windows reads as cp1252 (as under Claude Code): ✓ must not raise"""
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")
        code, out = self.can_fail("exit 1\n", stream)
        out.flush()
        self.assertEqual((code, out.buffer.getvalue().decode("utf-8")), (0, "CAN-FAIL ✓ one\n"))

    def test_the_kept_failures_outlive_the_transcript_window(self):
        self.main("echo boom; exit 1\n")
        kept = os.path.join(scenarios.outdir(self.repo), "failed", "one.log")
        ahead = time.time() + 30 * 86400
        write(self.repo, "other.txt", "a new tree\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "next")
        with mock.patch.object(scenarios.time, "time", lambda: ahead), contextlib.redirect_stdout(io.StringIO()):
            scenarios.cmd_run(self.repo)
        self.assertTrue(os.path.isfile(kept))


class TestPrune(unittest.TestCase):
    NOW = 1_800_000_000

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = self.tmp.name
        p = mock.patch.object(scenarios.time, "time", return_value=self.NOW)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, age_days, is_dir=True, extra_s=0):
        p = os.path.join(self.out, name)
        if is_dir:
            os.mkdir(p)
        else:
            open(p, "w").close()
        t = self.NOW - age_days * 86400 - extra_s
        os.utime(p, (t, t))
        return p

    def test_the_window_is_keep_days_to_the_second(self):
        at, past = self.make("at", scenarios.KEEP_DAYS), self.make("past", scenarios.KEEP_DAYS, extra_s=1)
        scenarios.prune(self.out, "ccc")
        self.assertEqual((os.path.exists(at), os.path.exists(past)), (True, False))

    def test_a_dir_that_will_not_go_does_not_stop_the_run(self):
        stuck, gone = self.make("stuck", scenarios.KEEP_DAYS + 1), self.make("zgone", scenarios.KEEP_DAYS + 1)
        real = scenarios.shutil.rmtree

        def rmtree(path, ignore_errors=False):  # the filesystem refuses one directory, as a busy or foreign one would
            if path != stuck:
                return real(path, ignore_errors=ignore_errors)
            if not ignore_errors:
                raise PermissionError(13, "Permission denied", path)

        with mock.patch.object(scenarios.shutil, "rmtree", rmtree):
            scenarios.prune(self.out, "ccc")
        self.assertEqual((os.path.exists(stuck), os.path.exists(gone)), (True, False))

    def test_old_transcript_dirs_of_other_trees_go(self):
        old, kept = self.make("aaa", scenarios.KEEP_DAYS + 1), self.make("bbb", scenarios.KEEP_DAYS - 1)
        scenarios.prune(self.out, "ccc")
        self.assertEqual((os.path.exists(old), os.path.exists(kept)), (False, True))

    def test_the_current_trees_dir_stays_however_old(self):
        cur = self.make("ccc", scenarios.KEEP_DAYS * 3)
        scenarios.prune(self.out, "ccc")
        self.assertTrue(os.path.isdir(cur))

    def test_a_symlink_to_a_dir_is_left_alone(self):
        target = self.make("real", scenarios.KEEP_DAYS * 3)
        link = os.path.join(self.out, "link")
        symlink(self, target, link)
        scenarios.prune(self.out, "real")
        self.assertTrue(os.path.islink(link) and os.path.isdir(target))

    def test_files_are_never_removed(self):
        results = self.make("results.json", scenarios.KEEP_DAYS * 3, is_dir=False)
        scenarios.prune(self.out, "ccc")
        self.assertTrue(os.path.isfile(results))


if __name__ == "__main__":
    unittest.main()
