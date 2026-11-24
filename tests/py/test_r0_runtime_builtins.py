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
import unittest.mock

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

    def r0(self, repo, stack, rc=(0,)):
        r = _kit.run_cli(["red", "--repo", repo, "--base", "HEAD", "--head", "HEAD", "--stack", stack,
                          "--test-paths", "tests/**", "--r0", self.cache])
        self.assertIn(r.returncode, rc, r.stderr + r.stdout)
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

    def test_python_addopts_in_the_project_config_does_not_change_the_listing(self):
        """review S1: `addopts = "-q"` made the listing `-qq` (one line per file, no test ids): 0/0 read pass."""
        repo = self.repo({"pyproject.toml": '[project]\nname = "x"\nversion = "0"\n\n[tool.pytest.ini_options]\n'
                                            'pythonpath = ["."]\naddopts = "-q"\n',
                          "lib.py": "def inc(n):\n    return n + 1\n",
                          "tests/test_lib.py": "from lib import inc\n\n\ndef test_inc():\n    assert inc(1) == 2\n"})
        c = self.r0(repo, "python")
        if not PY3_PYTEST:
            return self.check_env(c)
        self.check_pass(c, 6)

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


    def rust_repo(self, integration):
        """review S2: a lib test the scanner cannot see (made by a macro) and an integration test in tests/a.rs."""
        lib = ("pub fn inc(x: i32) -> i32 { x + 1 }\n#[cfg(test)]\nmod tests {\n    macro_rules! mk { ($n:ident) => { "
               "#[test] fn $n() { assert_eq!(super::inc(1), 2); } } }\n    mk!(adds);\n}\n")
        return self.repo({"Cargo.toml": '[package]\nname = "cr"\nversion = "0.1.0"\nedition = "2021"\n',
                          "src/lib.rs": lib,
                          "tests/a.rs": f"#[test]\nfn {integration}() {{ assert_eq!(cr::inc(1), 2); }}\n"})

    def test_rust_a_found_test_matches_one_listed_test_by_its_module_path(self):
        for name in ("adds", "other"):
            with self.subTest(integration=name):
                c = self.r0(self.rust_repo(name), "rust", (0, 1))
                if not CARGO:
                    return self.check_env(c)
                # listed: `tests::adds` (src/lib.rs, the macro's: unseen) and `<name>` (tests/a.rs): one found, one missed
                self.assertEqual(c["census"]["repo"], {"found": 1, "listed": 2, "misses": ["tests::adds"]}, c)


    def test_rust_the_miss_is_named_by_its_module_path(self):
        """src/foo.rs's test is seen, src/bar.rs's (a macro's) is not: the miss is bar's, matched by module path."""
        seen = "#[cfg(test)]\nmod tests {\n    #[test]\n    fn x() { assert_eq!(1, 1); }\n}\n"
        unseen = ("#[cfg(test)]\nmod tests {\n    macro_rules! mk { ($n:ident) => { #[test] fn $n() { assert_eq!(1, 1); } "
                  "} }\n    mk!(x);\n}\n")
        repo = self.repo({"Cargo.toml": '[package]\nname = "cr"\nversion = "0.1.0"\nedition = "2021"\n',
                          "src/lib.rs": "pub mod bar;\npub mod foo;\n", "src/foo.rs": seen, "src/bar.rs": unseen})
        c = self.r0(repo, "rust", (0, 1))
        if not CARGO:
            return self.check_env(c)
        self.assertEqual(c["census"]["repo"], {"found": 1, "listed": 2, "misses": ["bar::tests::x"]}, c)


    def test_cargo_subcommand_probe_keeps_the_program_rules_for_its_binary(self):
        """review N2: `cargo mutants --version` runs `cargo-mutants` from PATH: that binary is resolved by the same
        rules as cargo (on PATH's absolute entries, never in the reviewed checkout)."""
        repo = self.repo({"Cargo.toml": '[package]\nname = "cr"\nversion = "0.1.0"\nedition = "2021"\n',
                          "src/lib.rs": "pub fn inc(x: i32) -> i32 { x + 1 }\n", "bin/cargo-mutants": "#!/bin/sh\necho x\n"})
        os.chmod(os.path.join(repo, "bin", "cargo-mutants"), 0o755)
        with unittest.mock.patch.dict(os.environ, {"PATH": os.path.join(repo, "bin") + os.pathsep + os.environ["PATH"]}):
            r = _kit.run_cli(["r0", "--repo", repo, "--base", "HEAD", "--head", "HEAD", "--stack", "rust",
                              "--fingerprint", "r3"])
        line = json.loads(r.stdout)["probes"][0]
        if not CARGO:
            return self.assertEqual(line, "cargo mutants --version: not probed (not found on PATH)")
        self.assertTrue(line.startswith("cargo mutants --version: not probed (`cargo-mutants` in the reviewed checkout: "),
                        line)


if __name__ == "__main__":
    unittest.main()
