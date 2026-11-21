"""scripts/orch-status.py (#38): "is it stuck?" for agent worktrees in one call.

main(argv, run=..., procs=...) in this process. git runs for real on throwaway repos (a pushed branch is a bare remote);
`gh` and the process list are fakes. The process readers are tested on a fake /proc and fake ps / powershell output."""
import json
import os
import subprocess
import tempfile
import unittest

import _kit

st = _kit.load("orch-status")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           *args], check=True, capture_output=True, text=True).stdout.strip()


def write(repo, rel, text="x\n"):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="\n") as f:
        f.write(text)


class Repos(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = os.path.realpath(t.name)
        self.remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", self.remote], check=True)
        self.wt = os.path.join(self.tmp, "wt-agent-7")
        os.makedirs(self.wt)
        git(self.wt, "init", "-q", "-b", "main")
        git(self.wt, "remote", "add", "origin", self.remote)
        write(self.wt, "a.py")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "base")
        git(self.wt, "push", "-q", "origin", "main")
        git(self.wt, "checkout", "-q", "-b", "agent/x")
        self.checks = [{"name": "a", "state": "SUCCESS", "bucket": "pass"},
                       {"name": "b", "state": "FAILURE", "bucket": "fail"},
                       {"name": "c", "state": "PENDING", "bucket": "pending"},
                       {"name": "d", "state": "SUCCESS", "bucket": "pass"}]
        self.gh_rc, self.gh_err = 0, ""
        self.procs = []
        self.gh_calls = []

    def commit(self, msg, rel="a.py", text=None):
        write(self.wt, rel, text or msg + "\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", msg)

    def fake_run(self, argv, env=None, cwd=None):
        if argv[0] == "gh":
            self.gh_calls.append((list(argv), cwd))
            return self.gh_rc, json.dumps(self.checks) if self.gh_rc in (0, 8) else "", self.gh_err
        return st.run_cmd(argv, env, cwd)

    def status(self, *wts):
        r = _kit.run_cli(list(wts or [self.wt]), main=lambda a: st.main(a, run=self.fake_run, procs=lambda: self.procs))
        return r


class Commits(Repos):
    def test_commits_ahead_of_the_pushed_branch(self):
        self.commit("one")
        git(self.wt, "push", "-q", "-u", "origin", "agent/x")
        self.commit("two")
        self.commit("three")
        r = self.status()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(out[0], f"{self.wt} [agent/x]")
        self.assertIn("  commits: 2 ahead of origin/agent/x", out)

    def test_pushed_without_upstream_uses_the_remote_branch(self):
        self.commit("one")
        git(self.wt, "push", "-q", "origin", "agent/x")
        self.commit("two")
        self.assertIn("  commits: 1 ahead of origin/agent/x", self.status().stdout.splitlines())

    def test_up_to_date(self):
        self.commit("one")
        git(self.wt, "push", "-q", "-u", "origin", "agent/x")
        self.assertIn("  commits: 0 ahead of origin/agent/x (all pushed)", self.status().stdout.splitlines())

    def test_never_pushed_counts_from_origin_main(self):
        self.commit("one")
        self.commit("two")
        self.assertIn("  commits: not pushed; 2 ahead of origin/main", self.status().stdout.splitlines())

    def test_never_pushed_and_no_origin_main(self):
        git(self.wt, "remote", "remove", "origin")
        self.assertIn("  commits: not pushed (no origin/main)", self.status().stdout.splitlines())

    def test_last_commit_age_and_subject(self):
        self.commit("fix the parser")
        line = [x for x in self.status().stdout.splitlines() if x.startswith("  last commit: ")][0]
        self.assertTrue(line.endswith(" ago: fix the parser"), line)


class Dirty(Repos):
    def test_clean(self):
        self.assertIn("  dirty: none", self.status().stdout.splitlines())

    def test_dirty_files_are_counted_and_named(self):
        write(self.wt, "a.py", "changed\n")
        write(self.wt, "new.py")
        self.assertIn("  dirty: 2 file(s): a.py, new.py", self.status().stdout.splitlines())

    def test_many_dirty_files_are_cut_at_five(self):
        for i in range(7):
            write(self.wt, f"f{i}.py")
        self.assertIn("  dirty: 7 file(s): f0.py, f1.py, f2.py, f3.py, f4.py (+2 more)", self.status().stdout.splitlines())


class Processes(Repos):
    def test_live_test_processes_in_the_worktree(self):
        self.procs = [
            {"pid": 11, "age": "4m", "cwd": self.wt, "cmd": "python3 -m pytest tests/py"},
            {"pid": 12, "age": "1m", "cwd": "/elsewhere", "cmd": "mutmut run"},
            {"pid": 13, "age": "9m", "cwd": None, "cmd": f"bash verify-wsl.sh {self.wt} 'bash tests/run.sh'"},
            {"pid": 14, "age": None, "cwd": None,
             "cmd": "python3 -m mutmut run --max-children 4 in /home/u/.cache/ekit-verify/wt-agent-7"},
            {"pid": 15, "age": "2m", "cwd": self.wt, "cmd": "vim a.py"},
        ]
        out = self.status().stdout.splitlines()
        i = out.index("  processes: 3 live")
        self.assertEqual(out[i + 1:i + 4], [
            "    pid 11 (4m) python3 -m pytest tests/py",
            f"    pid 13 (9m) bash verify-wsl.sh {self.wt} 'bash tests/run.sh'",
            "    pid 14 python3 -m mutmut run --max-children 4 in /home/u/.cache/ekit-verify/wt-agent-7",
        ])

    def test_a_worktree_name_inside_a_longer_name_is_not_a_match(self):
        self.procs = [{"pid": 1, "age": "1m", "cwd": None, "cmd": "pytest /x/wt-agent-77/tests"}]
        self.assertIn("  processes: none", self.status().stdout.splitlines())

    def test_a_long_command_is_cut(self):
        self.procs = [{"pid": 1, "age": "1m", "cwd": self.wt, "cmd": "pytest " + "x" * 300}]
        line = [x for x in self.status().stdout.splitlines() if x.startswith("    pid 1 ")][0]
        self.assertEqual(len(line), len("    pid 1 (1m) ") + 120)
        self.assertTrue(line.endswith("..."))

    def test_no_process_list_is_a_note_not_a_crash(self):
        self.procs = "unavailable on this host (no /proc, ps or powershell)"
        self.assertIn("  processes: unavailable on this host (no /proc, ps or powershell)", self.status().stdout.splitlines())


class Ci(Repos):
    def test_ci_counts_by_bucket(self):
        out = self.status().stdout.splitlines()
        self.assertIn("  CI: 2 pass, 1 fail, 1 pending", out)
        self.assertEqual(self.gh_calls, [(["gh", "pr", "checks", "agent/x", "--json", "name,state,bucket"], self.wt)])

    def test_pending_checks_exit_8_still_count(self):
        self.gh_rc = 8
        self.assertIn("  CI: 2 pass, 1 fail, 1 pending", self.status().stdout.splitlines())

    def test_no_checks_yet(self):
        self.checks = []
        self.assertIn("  CI: no checks yet", self.status().stdout.splitlines())

    def test_no_pr(self):
        self.gh_rc, self.gh_err = 1, 'no pull requests found for branch "agent/x"\n'
        self.assertIn('  CI: no PR (no pull requests found for branch "agent/x")', self.status().stdout.splitlines())

    def test_gh_missing(self):
        self.gh_rc, self.gh_err = 127, "gh: not found\n"
        self.assertIn("  CI: no PR (gh: not found)", self.status().stdout.splitlines())


class Args(Repos):
    def test_several_worktrees_and_a_bad_one(self):
        bad = os.path.join(self.tmp, "nope")
        os.makedirs(bad)
        r = self.status(self.wt, bad)
        self.assertEqual(r.returncode, 2)
        out = r.stdout.splitlines()
        self.assertEqual(out[0], f"{self.wt} [agent/x]")
        self.assertTrue(any(x.startswith(f"{bad}: not a git worktree (") for x in out), out)

    def test_no_worktree_is_a_usage_error(self):
        r = _kit.run_cli([], main=lambda a: st.main(a, run=self.fake_run, procs=lambda: []))
        self.assertEqual(r.returncode, 2)

    def test_procs_are_read_once_for_all_worktrees(self):
        n = []

        def procs():
            n.append(1)
            return []

        _kit.run_cli([self.wt, self.wt], main=lambda a: st.main(a, run=self.fake_run, procs=procs))
        self.assertEqual(n, [1])


class Readers(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = t.name

    def proc(self, pid, cmd, start_ticks, cwd=None):
        d = os.path.join(self.root, str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"\0".join(x.encode() for x in cmd) + b"\0")
        fields = [str(pid), "(x y)", "S"] + ["0"] * 18 + [str(start_ticks)] + ["0"] * 10
        with open(os.path.join(d, "stat"), "w") as f:
            f.write(" ".join(fields))
        if cwd:
            os.symlink(cwd, os.path.join(d, "cwd"))

    def test_proc_reads_cmdline_age_and_cwd(self):
        with open(os.path.join(self.root, "uptime"), "w") as f:
            f.write("1000.50 3.0\n")
        self.proc(42, ["python3", "-m", "pytest"], 100 * 700)
        self.proc(43, ["mutmut", "run"], 100 * 995)
        os.makedirs(os.path.join(self.root, "self"))
        os.makedirs(os.path.join(self.root, "44"))  # gone mid-read: no cmdline
        got = sorted(st.proc_list(self.root, ticks=100), key=lambda p: p["pid"])
        self.assertEqual([(p["pid"], p["age"], p["cmd"]) for p in got],
                         [(42, "5m", "python3 -m pytest"), (43, "5s", "mutmut run")])

    def test_proc_cwd(self):
        if os.name == "nt":
            self.skipTest("symlinks")
        with open(os.path.join(self.root, "uptime"), "w") as f:
            f.write("10 1\n")
        self.proc(7, ["pytest"], 0, cwd=self.root)
        self.assertEqual(st.proc_list(self.root, ticks=100)[0]["cwd"], self.root)

    def test_ages(self):
        self.assertEqual([st.age(s) for s in (0, 59, 60, 3599, 3600, 3725, 90000)],
                         ["0s", "59s", "1m", "59m", "1h0m", "1h2m", "25h0m"])

    def test_ps_output(self):
        def run(argv, env=None, cwd=None):
            self.assertEqual(argv, ["ps", "-axo", "pid=,etime=,command="])
            return 0, "  12   05:01 python3 -m pytest -x\n 3 1-02:00:00 mutmut run\n\n", ""

        self.assertEqual(st.ps_list(run), [{"pid": 12, "age": "05:01", "cwd": None, "cmd": "python3 -m pytest -x"},
                                           {"pid": 3, "age": "1-02:00:00", "cwd": None, "cmd": "mutmut run"}])

    def test_ps_failure_is_a_note(self):
        self.assertEqual(st.ps_list(lambda argv, env=None, cwd=None: (1, "", "ps: bad\n")), "unavailable (ps exit 1)")

    def test_powershell_output(self):
        def run(argv, env=None, cwd=None):
            self.assertEqual(argv[:2], ["powershell", "-NoProfile"])
            return 0, json.dumps([{"ProcessId": 5, "CommandLine": "python -m pytest"},
                                  {"ProcessId": 6, "CommandLine": None}]), ""

        self.assertEqual(st.win_list(run), [{"pid": 5, "age": None, "cwd": None, "cmd": "python -m pytest"}])

    def test_powershell_single_object_and_failure(self):
        one = lambda argv, env=None, cwd=None: (0, json.dumps({"ProcessId": 5, "CommandLine": "pytest"}), "")
        self.assertEqual(st.win_list(one), [{"pid": 5, "age": None, "cwd": None, "cmd": "pytest"}])
        self.assertEqual(st.win_list(lambda argv, env=None, cwd=None: (1, "", "x")), "unavailable (powershell exit 1)")

    def test_default_reader_picks_by_host(self):
        calls = []
        run = lambda argv, env=None, cwd=None: calls.append(argv[0]) or (0, "[]", "")
        self.assertEqual(st.processes(run, proc_root=self.root, which=lambda n: None, os_name="posix"),
                         "unavailable on this host (no /proc, ps or powershell)")
        os.makedirs(os.path.join(self.root, "proc"))
        with open(os.path.join(self.root, "proc", "uptime"), "w") as f:
            f.write("1 1\n")
        self.assertEqual(st.processes(run, proc_root=os.path.join(self.root, "proc"), which=lambda n: None), [])
        st.processes(run, proc_root=self.root, which=lambda n: "/bin/ps" if n == "ps" else None, os_name="posix")
        st.processes(run, proc_root=self.root, which=lambda n: "ps", os_name="nt")
        self.assertEqual(calls, ["ps", "powershell"])


if __name__ == "__main__":
    unittest.main()
