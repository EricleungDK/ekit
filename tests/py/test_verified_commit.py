"""scripts/verified-commit.py (#81): the commit a mech-review result describes is the worktree's head and the pushed tip.

main(argv) in this process. git runs for real on throwaway repos: a pushed branch is a bare remote, and a second clone
of it moves the tip. Results are envelope files written by the test, as `mech-review.py all` prints them."""
import json
import os
import subprocess
import tempfile
import unittest

import _kit

vc = _kit.load("verified-commit")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           *args], check=True, capture_output=True, text=True).stdout.strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as f:
        f.write(text)


class Repos(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = os.path.realpath(t.name)
        self.remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", self.remote], check=True)
        self.wt = os.path.join(self.tmp, "wt")
        os.makedirs(self.wt)
        git(self.wt, "init", "-q", "-b", "main")
        git(self.wt, "remote", "add", "origin", self.remote)
        self.base = self.commit("base")
        git(self.wt, "push", "-q", "origin", "main")
        git(self.wt, "checkout", "-q", "-b", "agent/x")

    def commit(self, msg, repo=None):
        repo = repo or self.wt
        write(os.path.join(repo, "a.py"), msg + "\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", msg)
        return git(repo, "rev-parse", "HEAD")

    def result(self, head, name="mech.json"):
        path = os.path.join(self.tmp, name)
        write(path, json.dumps({"ekit": "0", "base": self.base, "head": head, "checks": {}, "entries": [],
                                "summary": f"pass {head} (0 fail, 0 confirm; ran: R2)"}))
        return path

    def check(self, *argv):
        return _kit.run_cli(list(argv), main=vc.main)

    def push(self):
        git(self.wt, "push", "-q", "-u", "origin", "agent/x")

    def move_remote_tip(self):
        """Another clone pushes a later commit to the branch: the remote tip moves, this worktree does not see it."""
        other = os.path.join(self.tmp, "other")
        subprocess.run(["git", "clone", "-q", "-b", "agent/x", self.remote, other], check=True)
        moved = self.commit("pushed elsewhere", repo=other)
        git(other, "push", "-q", "origin", "agent/x")
        return moved


class Heads(Repos):
    def test_matching_heads_on_a_branch_never_pushed_pass(self):
        head = self.commit("work")
        r = self.check(self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(head, r.stdout)
        self.assertIn("not pushed", r.stdout)

    def test_a_later_worktree_head_is_refused_naming_both_commits(self):
        verified = self.commit("work")
        later = self.commit("one more commit after the check")
        r = self.check(self.result(verified), self.wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"refused: the worktree's head {later} is not the result's head {verified}", r.stdout)


class Pushed(Repos):
    def test_pushed_branch_at_the_verified_head_passes(self):
        head = self.commit("work")
        self.push()
        r = self.check(self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"remote tip of origin/agent/x: {head}", r.stdout)

    def test_remote_tip_moved_by_another_push_is_refused_naming_both_commits(self):
        head = self.commit("work")
        self.push()
        moved = self.move_remote_tip()
        r = self.check(self.result(head), self.wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"refused: the remote tip of origin/agent/x {moved} is not the result's head {head}", r.stdout)

    def test_the_remote_is_asked_not_a_stale_tracking_ref(self):
        # the worktree's origin/agent/x still says `head`; only the remote knows it moved
        head = self.commit("work")
        self.push()
        self.move_remote_tip()
        self.assertEqual(git(self.wt, "rev-parse", "origin/agent/x"), head)
        self.assertEqual(self.check(self.result(head), self.wt).returncode, 1)

    def test_remote_tip_behind_the_verified_head_is_refused_by_default(self):
        old = self.commit("work")
        self.push()
        head = self.commit("fix, not pushed yet")
        r = self.check(self.result(head), self.wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"the remote tip of origin/agent/x {old} is not the result's head {head}", r.stdout)

    def test_upstream_names_the_remote_and_branch_compared(self):
        head = self.commit("work")
        fork = os.path.join(self.tmp, "fork.git")
        subprocess.run(["git", "init", "-q", "--bare", fork], check=True)
        git(self.wt, "remote", "add", "fork", fork)
        git(self.wt, "push", "-q", "-u", "fork", "agent/x:review/x")
        r = self.check(self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"remote tip of fork/review/x: {head}", r.stdout)
        moved = self.commit("pushed to the upstream after the check")
        git(self.wt, "push", "-q", "fork", "agent/x:review/x")
        git(self.wt, "reset", "-q", "--hard", head)
        r = self.check(self.result(head), self.wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"the remote tip of fork/review/x {moved} is not", r.stdout)


class NotPushed(Repos):
    def test_a_branch_the_remote_does_not_have_is_verified_on_the_worktree_head_alone(self):
        head = self.commit("work")
        r = self.check(self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout, f"verified: {head} is the worktree's head; not pushed (origin has no agent/x)\n")

    def test_a_repo_without_the_remote_is_verified_on_the_worktree_head_alone(self):
        head = self.commit("work")
        git(self.wt, "remote", "remove", "origin")
        r = self.check(self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("not pushed (no remote origin)", r.stdout)

    def test_a_detached_head_is_verified_on_the_worktree_head_alone_whatever_the_remote_tip(self):
        head = self.commit("work")
        self.push()
        git(self.wt, "checkout", "-q", "--detach")
        self.move_remote_tip()
        r = self.check(self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("not pushed (detached HEAD)", r.stdout)


class AllowBehind(Repos):
    """Before a push: the verified fixes are not on the remote yet; the remote tip may trail the result's head."""

    def test_tip_behind_the_verified_head_passes(self):
        old = self.commit("work")
        self.push()
        head = self.commit("fix, not pushed yet")
        r = self.check("--allow-behind", self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"the remote tip of origin/agent/x {old} is behind it", r.stdout)

    def test_tip_at_the_verified_head_passes(self):
        head = self.commit("work")
        self.push()
        r = self.check("--allow-behind", self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"remote tip of origin/agent/x: {head}", r.stdout)

    def test_tip_moved_past_the_verified_head_is_still_refused(self):
        head = self.commit("work")
        self.push()
        moved = self.move_remote_tip()
        git(self.wt, "fetch", "-q", "origin")
        r = self.check("--allow-behind", self.result(head), self.wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"refused: the remote tip of origin/agent/x {moved} is not the result's head {head}", r.stdout)

    def test_tip_this_clone_does_not_have_is_refused(self):
        head = self.commit("work")
        self.push()
        moved = self.move_remote_tip()
        r = self.check("--allow-behind", self.result(head), self.wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"refused: the remote tip of origin/agent/x {moved} is not in this clone (fetch, then rerun)",
                      r.stdout)

    def test_worktree_head_past_the_result_is_still_refused(self):
        verified = self.commit("work")
        self.push()
        later = self.commit("after the check")
        r = self.check("--allow-behind", self.result(verified), self.wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"the worktree's head {later} is not the result's head {verified}", r.stdout)


class Expect(Repos):
    """--expect SHA: the head the review request names (#78 §4) must be the result's head too."""

    def test_the_review_requests_head_at_the_result_passes_naming_it(self):
        head = self.commit("work")
        r = self.check("--expect", head, self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout, f"verified: {head} is the review request's head and the worktree's head; not "
                                   "pushed (origin has no agent/x)\n")

    def test_a_short_sha_of_the_result_head_passes(self):
        head = self.commit("work")
        r = self.check("--expect", head[:12], self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_review_request_for_an_earlier_commit_is_refused_naming_both_commits(self):
        requested = self.commit("work")
        later = self.commit("one more commit after the review request")
        r = self.check("--expect", requested, self.result(later), self.wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout, f"refused: the review request's head {requested} is not the result's head "
                                   f"{later}\n")

    def test_it_is_checked_beside_the_remote_tip_with_allow_behind(self):
        self.commit("work")
        self.push()
        head = self.commit("fix, not pushed yet")
        r = self.check("--allow-behind", "--expect", head, self.result(head), self.wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.split(";")[0], f"verified: {head} is the review request's head and the worktree's "
                                                 "head")

    def test_an_expect_that_names_no_commit_is_no_answer(self):
        head = self.commit("work")
        r = self.check("--expect", "0123456789ab", self.result(head), self.wt)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.stderr.split(" (")[0], f"refused: --expect 0123456789ab names no commit in {self.wt}")


class Refusals(Repos):
    """No answer is never a pass: each case exits 2 and says why."""

    def refused(self, result, why, wt=None):
        r = self.check(result, wt or self.wt)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("verified:", r.stdout)
        self.assertIn(why, r.stderr)

    def raw(self, text):
        path = os.path.join(self.tmp, "raw.json")
        write(path, text)
        return path

    def test_missing_result_file(self):
        self.commit("work")
        self.refused(os.path.join(self.tmp, "nope.json"), "refused: cannot read the result")

    def test_result_that_is_not_text(self):
        self.commit("work")
        path = os.path.join(self.tmp, "bin.json")
        with open(path, "wb") as f:
            f.write(b'{"head": "\xff\xfe"}')
        self.refused(path, "refused: cannot read the result")

    def test_result_that_is_not_json(self):
        self.commit("work")
        self.refused(self.raw("pass abc (0 fail)\n"), "refused: the result is not JSON")

    def test_result_that_is_not_an_object(self):
        self.commit("work")
        self.refused(self.raw("[1, 2]"), "refused: the result has no head")

    def test_result_without_a_head(self):
        self.commit("work")
        self.refused(self.raw(json.dumps({"summary": "pass", "entries": []})), "refused: the result has no head")

    def test_result_whose_head_is_not_a_commit_sha(self):
        self.commit("work")
        for head in ("HEAD", "", None, 7, "abc123"):
            with self.subTest(head=head):
                self.refused(self.result(head), "refused: the result's head is not a commit SHA")

    def test_result_from_stdin(self):
        head = self.commit("work")
        import io
        import sys
        old = sys.stdin
        sys.stdin = io.StringIO(json.dumps({"head": head}))
        try:
            r = self.check("-", self.wt)
        finally:
            sys.stdin = old
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_path_that_is_not_a_git_worktree(self):
        head = self.commit("work")
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.refused(self.result(head), f"refused: {plain} is not a git worktree", wt=plain)

    def test_no_git_on_path(self):
        from unittest import mock
        head = self.commit("work")
        empty = os.path.join(self.tmp, "empty-bin")
        os.makedirs(empty)
        with mock.patch.dict(os.environ, {"PATH": empty}):
            self.refused(self.result(head), f"refused: {self.wt} is not a git worktree (git: ")

    def test_remote_that_cannot_be_asked(self):
        head = self.commit("work")
        self.push()
        git(self.wt, "remote", "set-url", "origin", os.path.join(self.tmp, "gone.git"))
        self.refused(self.result(head), "refused: cannot ask origin for agent/x's tip")


if __name__ == "__main__":
    unittest.main()
