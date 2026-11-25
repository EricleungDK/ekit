"""The eval mistake-to-check-cochange asks for a co-change rule whose incident is #12. Its scaffold must make that answer
work as the kit reads it: a rule naming #12 resolves (R2's guard is silent) and proves itself (R0), and the repo's own
history repeats the mistake (#15), so the rule has a second example to stand on."""
import json
import os
import subprocess
import tempfile
import unittest

import _kit
from scripts import shells  # bash: Git Bash on Windows, where a bare "bash" starts WSL's launcher
from test_eval_scaffold import case_dir

CASE = case_dir("mistake-to-check-cochange")
RULE = '''format = 1

[[rule]]
id = "core-changelog"
trigger = ["app/**"]
require = ["CHANGELOG.md"]
reason = "a behaviour change under app/ updates CHANGELOG.md"
incident = "{incident}"
flagged = ["app/core.py"]
control = ["app/core.py", "CHANGELOG.md"]
'''


class CoChangeScaffold(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(tmp.name), "repo")
        os.mkdir(self.repo)
        bash = shells.find("bash")
        subprocess.run([bash, os.path.join(CASE, "setup.sh")], cwd=self.repo, check=True, capture_output=True,
                       env=shells.env_for(bash, "bash"))

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, text=True).stdout.strip()

    def commit_rule(self, incident):
        os.makedirs(os.path.join(self.repo, ".ekit"), exist_ok=True)
        with open(os.path.join(self.repo, ".ekit", "co-change.toml"), "w") as f:
            f.write(RULE.format(incident=incident))
        base = self.git("rev-parse", "HEAD")
        self.git("add", "-A")
        self.git("commit", "-qm", "co-change rule")
        return base, self.git("rev-parse", "HEAD")

    def check(self, name, base, head):
        r = _kit.run_cli([name, "--repo", self.repo, "--base", base, "--head", head, "--stack", "python",
                          "--test-paths", "tests/**"])
        self.assertIn(r.returncode, (0, 1), r.stderr)  # 2: usage or git error, no result
        return json.loads(r.stdout)

    def test_the_history_holds_the_incident_and_a_second_example(self):
        for pr in ("#12", "#15"):
            sha = self.git("log", "--format=%H", "--grep", f"({pr})")
            changed = self.git("show", "--format=", "--name-only", sha).split()
            self.assertEqual(changed, ["app/core.py"], pr)

    def test_a_rule_naming_12_proves_itself_and_r2_guards_nothing(self):
        base, head = self.commit_rule("#12")
        r0 = self.check("r0", base, head)
        self.assertEqual([(c["case"], c["status"]) for c in r0["checks"]["R0"]["co-change"]],
                         [("core-changelog:flagged", "pass"), ("core-changelog:control", "pass")])
        r2 = self.check("r2", base, head)
        self.assertEqual([e for e in r2["entries"] if e["file"] == ".ekit/co-change.toml"], [])

    def test_a_rule_naming_a_pr_the_history_lacks_is_refused(self):
        """Control: the guard does read the incident, so the #12 pass above is the scaffold's history at work."""
        base, head = self.commit_rule("#99")
        r2 = self.check("r2", base, head)
        got = [e for e in r2["entries"] if e["file"] == ".ekit/co-change.toml"]
        self.assertEqual([(e["severity"], e["class"]) for e in got], [("fail", "agent-fixable")], got)


if __name__ == "__main__":
    unittest.main()
