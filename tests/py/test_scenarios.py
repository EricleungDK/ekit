import contextlib
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts import scenarios
from _kit import symlink  # a skip naming the refusal where the OS will not make links


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

    def run_all(self, script):
        write(self.repo, ".ekit/scenarios/one/run.sh", script)
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

    def main(self, script, *args):
        """the runner's entry, in-process: (exit code, stdout, results.json)"""
        write(self.repo, ".ekit/scenarios/one/run.sh", script)
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
