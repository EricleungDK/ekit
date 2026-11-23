"""R0 static half (#20): `mech-review.py r0` proves the stack adapter against the cheat suite and the negative controls,
git and adapter only. Through cli.main in this process (R3's mutmut sees only in-process calls)."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest

import _kit

CHEATS = ["delete", "comment-out", "rename", "skip", "expected-value", "weaken-assert", "suppression"]
CONTROLS = ["rename-same-asserts", "reorder-asserts", "helper-asserts", "empty-diff"]


class Repo:
    def __init__(self, tmp):
        self.path = tmp
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.path, "-c", "user.email=t@t", "-c", "user.name=t",
                               "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout

    def commit(self, files, msg="c"):
        for rel, text in files.items():
            full = os.path.join(self.path, rel)
            if text is None:
                os.remove(full)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", newline="\n") as f:
                f.write(text)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()


def tmp_repo(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    repo = Repo(tmp.name)
    return repo, repo.commit({"README.md": "x\n"}, "base")


def r0(repo, base, head, *extra):
    return _kit.run_cli(["r0", "--repo", repo.path, "--base", base, "--head", head, *extra])


class BuiltinsPass(unittest.TestCase):
    """C1: the static half passes against every built-in stack: each cheat caught, each control clean."""

    def check_stack(self, stack):
        repo, base = tmp_repo(self)
        r = r0(repo, base, base, "--stack", stack)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = json.loads(r.stdout)
        c = env["checks"]["R0"]
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual(c["half"], "static")
        self.assertEqual({x["case"]: x["status"] for x in c["cases"] if x["kind"] in ("cheat", "control")},
                         dict.fromkeys(CHEATS + CONTROLS, "pass"))
        self.assertEqual(env["entries"], [])
        self.assertEqual(env["summary"], f"pass {base} (0 fail, 0 confirm; ran: R0; skipped: R1 R2 R3 R4)")

    def test_rust(self):
        self.check_stack("rust")

    def test_python(self):
        self.check_stack("python")

    def test_ts(self):
        self.check_stack("ts")


MINI = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.toml")
MINI_FIXTURES = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "mini.r0")
FUNCTIONS = '\n[functions]\nshapes = ["fn NAME (...) ...{...}"]\n'


def has_tomllib():
    return importlib.util.find_spec("tomllib") is not None  # adapter files need python 3.11+


def adapter_copy(case, text):
    """an adapter file with this text in a temp dir (no fixture dir beside it): its path."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    path = os.path.join(tmp.name, "mini.toml")
    with open(path, "w", newline="\n") as f:
        f.write(text)
    return path


def mini_text():
    with open(MINI) as f:
        return f.read()


@unittest.skipUnless(has_tomllib(), "adapter files need python 3.11+ (tomllib)")
class AdapterFiles(unittest.TestCase):
    """C2, C3: R0 proves an adapter file the same way; a weak one fails and names the cheat or control it got wrong."""

    def run_r0(self, adapter, fixtures=MINI_FIXTURES):
        repo, base = tmp_repo(self)
        r = r0(repo, base, base, "--stack", "mini", "--adapter", adapter, "--fixtures", fixtures)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return r.returncode, json.loads(r.stdout)

    def test_a_good_adapter_file_passes_and_each_malformed_table_fails_to_load_cleanly(self):
        rc, env = self.run_r0(adapter_copy(self, mini_text() + FUNCTIONS))
        c = env["checks"]["R0"]
        self.assertEqual((rc, c["status"], env["entries"]), (0, "pass", []), c)
        got = {x["case"]: (x["status"], x["got"]) for x in c["cases"] if x["kind"] == "malformed"}
        self.assertEqual({k: v[0] for k, v in got.items()},
                         {"ident-chars": "pass", "empty-asserts": "pass", "unbalanced-brackets": "pass"})
        self.assertIn("(ident-chars): lexer.ident_chars: `(` cannot be part of a word", got["ident-chars"][1])
        self.assertIn("(empty-asserts): asserts: no assert shape", got["empty-asserts"][1])
        self.assertIn("(unbalanced-brackets): lexer.brackets[0]: `(`: want an opener and a closer",
                      got["unbalanced-brackets"][1])

    def test_an_adapter_that_misses_a_skip_marker_fails_and_names_the_skip_cheat(self):
        weak = mini_text().replace('skip = ["xtest"]\n', "") + FUNCTIONS
        rc, env = self.run_r0(adapter_copy(self, weak))
        c = env["checks"]["R0"]
        self.assertEqual((rc, c["status"]), (1, "fail"))
        self.assertEqual([x["case"] for x in c["cases"] if x["status"] == "fail"], ["skip"])
        self.assertEqual([(e["check"], e["class"], e["severity"]) for e in env["entries"]],
                         [("R0", "adapter-fix", "fail")])
        self.assertIn("cheat `skip` gave no R2 fail: #[ignore] / skip / xfail / only on a test entry",
                      env["entries"][0]["problem"])

    def test_an_adapter_that_flags_an_honest_helper_fails_and_names_the_control(self):
        rc, env = self.run_r0(MINI)  # mini.toml has no [functions]: asserts moved into a helper read as dropped
        c = env["checks"]["R0"]
        self.assertEqual((rc, c["status"]), (1, "fail"))
        self.assertEqual([x["case"] for x in c["cases"] if x["status"] == "fail"], ["helper-asserts"])
        self.assertEqual(len(env["entries"]), 1)
        self.assertIn("control `helper-asserts` gave 1 entries: assertions in test `adds` dropped from 2 to 0 "
                      "(want no entry)", env["entries"][0]["problem"])

    def test_a_cheat_with_no_fixture_reads_unproven_and_never_all_pass(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for fn in os.listdir(MINI_FIXTURES):
            if not fn.startswith("suppression."):
                with open(os.path.join(MINI_FIXTURES, fn)) as src, open(os.path.join(tmp.name, fn), "w") as dst:
                    dst.write(src.read())
        rc, env = self.run_r0(adapter_copy(self, mini_text() + FUNCTIONS), fixtures=tmp.name)
        c = env["checks"]["R0"]
        self.assertEqual((rc, c["status"], env["entries"]), (0, "unproven", []))
        self.assertEqual([(x["case"], x["got"]) for x in c["cases"] if x["status"] == "unproven"],
                         [("suppression", "no fixture `suppression.mini.r0`")])
        self.assertIn("unproven (no fixture): suppression", c["note"])
        self.assertFalse(env["summary"].startswith("all pass"))
        self.assertIn("unproven: R0", env["summary"])


if __name__ == "__main__":
    unittest.main()
