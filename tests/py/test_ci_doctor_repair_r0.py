"""What judges a repair PR (#24), as the engine does it today, pinned so the repair mode's docs and skill stay true.
An adapter-fix PR that edits only the adapter file: R0's static half in CI (`r0 --base <base> --head <pr>`, no
--adapter) proves the base branch's copy, so the PR reads the same R0 fail until it merges; the edited copy passes when
it is proved at the PR's own head (`--base <pr> --head <pr>`, the proof the repair PR's body carries); and R0's
editing rules read the edit against the base, so a loosened limit or a changed target OS is the `needs-human` entry.
Every call goes through cli.main in this process."""
import json
import os
import unittest

import _kit
from test_stack_plan import PLAN, Repo, plan

ADAPTERS = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters")
BROKEN = ('skip = ["Disabled",', "skip = [")  # no longer reads @Disabled as a skip: R0's `skip` cheat gives no fail


def reference():
    """{repo path: text}: the Java reference adapter as the repo's own `maven` file, its R0 fixtures beside it"""
    with open(os.path.join(ADAPTERS, "java.toml"), encoding="utf-8") as f:
        files = {".ekit/adapters/maven.toml": f.read().replace('name = "java"', 'name = "maven"')}
    src = os.path.join(ADAPTERS, "java.r0")
    for root, _, names in os.walk(src):
        for fn in names:
            with open(os.path.join(root, fn), encoding="utf-8", newline="") as f:
                files[".ekit/adapters/maven.r0/" + os.path.relpath(os.path.join(root, fn), src).replace(os.sep, "/")] = \
                    f.read()
    return files


class AdapterFixPr(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.good = reference()
        broken = dict(self.good)
        broken[".ekit/adapters/maven.toml"] = self.good[".ekit/adapters/maven.toml"].replace(*BROKEN)
        self.base = self.repo.commit(dict(broken, **{"pom.xml": "<project/>\n",
                                                     PLAN: plan(("calc", ".", ".ekit/adapters/maven.toml", "current"))}))

    def r0(self, base, head):
        r = _kit.run_cli(["r0", "--repo", self.repo.path, "--base", base, "--head", head, "--stack", "maven",
                          "--project-dir", "."])
        env = json.loads(r.stdout) if r.stdout else None
        return r, env

    def test_ci_proves_the_base_copy_so_the_repair_pr_reads_the_same_fail(self):
        head = self.repo.commit({".ekit/adapters/maven.toml": self.good[".ekit/adapters/maven.toml"]})
        r, env = self.r0(self.base, head)
        self.assertEqual((r.returncode, env["checks"]["R0"]["status"]), (1, "fail"), r.stderr)
        self.assertEqual([(e["class"], e["problem"].split(": ")[1]) for e in env["entries"]],
                         [("adapter-fix", "cheat `skip` gave no R2 fail")])
        r, env = self.r0(head, head)  # the repair's own proof: its edited copy
        self.assertEqual((r.returncode, env["checks"]["R0"]["status"], env["checks"]["R0"]["note"], env["entries"]),
                         (0, "pass", "static half: 17 of 17 cases proved", []), r.stderr)

    def test_a_loosened_limit_or_a_changed_target_os_needs_a_person(self):
        fixed = self.good[".ekit/adapters/maven.toml"]
        for name, text, want in (
                ("limit", fixed + "\n[limits]\nmax-mutants = 10\n", "`limits.max-mutants` 40 -> 10"),
                ("os", fixed.replace('target-os = "linux"', 'target-os = "windows"'), "target-os linux -> windows")):
            with self.subTest(name):
                head = self.repo.commit({".ekit/adapters/maven.toml": text})
                _, env = self.r0(self.base, head)
                people = [e["problem"] for e in env["entries"] if e["class"] == "needs-human"]
                self.assertEqual(len(people), 1, env["entries"])
                self.assertIn(want, people[0])
                self.repo.git("reset", "-q", "--hard", self.base)

    def test_a_folder_added_to_ignore_needs_a_person(self):
        head = self.repo.commit({PLAN: plan(("calc", ".", ".ekit/adapters/maven.toml", "current"), ignore=["tools"])})
        _, env = self.r0(self.base, head)
        self.assertEqual([e["problem"] for e in env["entries"] if e["class"] == "needs-human"],
                         ["a person decides: `ignore` gains `tools` in .ekit/stack-plan.toml"])


if __name__ == "__main__":
    unittest.main()
