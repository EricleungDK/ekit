"""R0 runtime half (#21) against the built-in stacks and their real toolchains: `red --r0` on a small repo of each,
with ekit's own fixtures (scripts/mech_review/r0_fixtures/<stack>/runtime). A stack whose toolchain is not on this
machine reads `n/a` (env), never pass: no stub stands in, since the point is the real runner's output, and no test is
skipped (each asserts what this machine must give)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import _kit

PY3 = shutil.which("python3")
PY3_PYTEST = bool(PY3) and subprocess.run([PY3, "-m", "pytest", "--version"], capture_output=True).returncode == 0
CARGO = shutil.which("cargo")


class Builtin(unittest.TestCase):
    def repo(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = os.path.join(tmp.name, "repo")
        self.cache = os.path.join(tmp.name, "cache")
        for p, text in files.items():
            full = os.path.join(repo, p)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(text)
        git = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(git[:3] + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-qm", "base"], check=True)
        return repo

    def r0(self, repo, stack):
        r = _kit.run_cli(["red", "--repo", repo, "--base", "HEAD", "--head", "HEAD", "--stack", stack,
                          "--test-paths", "tests/**", "--r0", self.cache])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout)["checks"]["R0"]

    def check_env(self, c):
        """no toolchain: every case that runs the runner is n/a (env), and the part never reads pass."""
        self.assertEqual(c["status"], "n/a", c)
        ran = {x["case"]: x["status"] for x in c["cases"] if x["case"] != "skip-idiom"}
        self.assertEqual(ran, dict.fromkeys(ran, "n/a"), c)
        self.assertTrue(all(x["got"].startswith("env") for x in c["cases"] if x["status"] == "n/a"), c)

    def check_pass(self, c, fixtures_listed):
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual({x["case"]: x["status"] for x in c["cases"]},
                         dict.fromkeys(["census-repo", "census-fixtures", "control-pass", "control-fail",
                                        "control-skipped", "control-build", "control-no-such-test", "skip-idiom"],
                                       "pass"))
        self.assertEqual(c["census"]["repo"], {"found": 1, "listed": 1, "misses": []})
        self.assertEqual(c["census"]["fixtures"], {"found": fixtures_listed, "listed": fixtures_listed, "misses": []})

    def test_python(self):
        repo = self.repo({"pyproject.toml": '[project]\nname = "x"\nversion = "0"\n\n[tool.pytest.ini_options]\n'
                                            'pythonpath = ["."]\n',
                          "lib.py": "def inc(n):\n    return n + 1\n",
                          "tests/test_lib.py": "from lib import inc\n\n\ndef test_inc():\n    assert inc(1) == 2\n"})
        c = self.r0(repo, "python")
        if not PY3_PYTEST:
            return self.check_env(c)
        # test_passes, test_fails, test_skipped, test_each (once: its [1] [2] ids), TestStyle, CaseStyle
        self.check_pass(c, 6)
        self.assertTrue(c["probes"][1].startswith("python3 -m pytest --version: pytest "), c["probes"])

    def test_rust(self):
        repo = self.repo({"Cargo.toml": '[package]\nname = "x"\nversion = "0.0.0"\nedition = "2021"\n',
                          "src/lib.rs": "pub fn inc(n: i32) -> i32 {\n    n + 1\n}\n\n#[cfg(test)]\nmod tests {\n"
                                        "    #[test]\n    fn incs() {\n        assert_eq!(super::inc(1), 2);\n    }\n}\n"})
        c = self.r0(repo, "rust")
        if not CARGO:
            return self.check_env(c)
        # unit_adds (src/lib.rs, `tests::unit_adds`), passes, fails, skipped (ignored: listed), nested::in_a_mod
        self.check_pass(c, 5)
        self.assertTrue(c["probes"][0].startswith("cargo --version: cargo "), c["probes"])


if __name__ == "__main__":
    unittest.main()
