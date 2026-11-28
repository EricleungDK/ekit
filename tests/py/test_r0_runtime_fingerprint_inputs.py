"""R0 runtime half (#106): a cached pass is reused only for what it proved. Each input that changes what a part
proves changes its fingerprint (`r0 --fingerprint`, the key the workflow's cache restores): the runner the checkout
picks, the TypeScript toolchain installed in node_modules (Stryker, the runner's version), the Rust toolchain pin, the
JDK a Java adapter's build tool runs on, and the runner's fixture variant, read from the same tree as the fingerprint
(the head), never the caller's. A pass cached before such a change is not reused: the part reads `(ran)`. All through
cli.main in this process."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import _kit
from test_r0_runtime import MINIRUN_FX, Case, adapter_text

MAVEN = os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "maven.toml")

# minirun with two runners: `fast` when the checkout holds fast.flag (its command `mini test --fast`), else `plain`
RUNNERS = ('[[run.runner]]\nname = "fast"\nmatch = "--fast"\ncommand = "mini test --fast"\n'
           'when = { file = "fast.flag" }\n\n[[run.runner]]\nname = "plain"\n\n')


def with_runners(text):
    return text.replace("[run.list]", RUNNERS + "[run.list]", 1)


class _Repo(unittest.TestCase):
    """a git repo of a built-in stack in a temp dir; fp() is `r0 --fingerprint PART` on it."""
    stack = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("MECH_TEST_STUB", None)
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                               "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout.strip()

    def write(self, files):
        for p, text in files.items():
            full = os.path.join(self.repo, p)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(text)

    def commit(self, files):
        self.write(files)
        self.git("add", "-A")
        self.git("commit", "-qm", "c", "--allow-empty")
        return self.git("rev-parse", "HEAD")

    def fp(self, part, head, *extra):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", head, "--head", head, "--stack", self.stack,
                          "--fingerprint", part, *extra])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        got = json.loads(r.stdout)
        self.assertEqual(got["key"], f"ekit-r0-{part}-{got['fingerprint']}")
        return got["fingerprint"]


def pkg(*deps):
    return json.dumps({"name": "p", "devDependencies": {d: "1.0.0" for d in deps}}) + "\n"


def installed(version):
    return json.dumps({"name": "x", "version": version}) + "\n"


class TsToolchain(_Repo):
    stack = "ts"

    def setUp(self):
        super().setUp()
        with open(os.path.join(self.repo, ".gitignore"), "w") as f:
            f.write("node_modules/\n")

    def test_the_runner_the_checkout_picks_changes_the_r3_fingerprint(self):
        """the issue's example: a PR that switches vitest -> jest must not reuse a vitest R3-control pass"""
        vitest = self.fp("r3", self.commit({"package.json": pkg("vitest")}))
        jest = self.fp("r3", self.commit({"package.json": pkg("jest")}))
        self.assertNotEqual(vitest, jest)

    def test_the_stryker_version_in_node_modules_changes_the_r3_fingerprint(self):
        head = self.commit({"package.json": pkg("vitest")})
        self.write({"node_modules/@stryker-mutator/core/package.json": installed("9.0.0")})
        old = self.fp("r3", head)
        self.write({"node_modules/@stryker-mutator/core/package.json": installed("10.0.0")})
        self.assertNotEqual(self.fp("r3", head), old)

    def test_the_runners_version_in_node_modules_changes_both_fingerprints(self):
        head = self.commit({"package.json": pkg("vitest")})
        self.write({"node_modules/vitest/package.json": installed("2.1.9")})
        old = {part: self.fp(part, head) for part in ("run", "r3")}
        self.write({"node_modules/vitest/package.json": installed("3.2.7")})
        self.assertEqual({part: self.fp(part, head) != old[part] for part in ("run", "r3")}, {"run": True, "r3": True})

    def test_an_unchanged_tree_keeps_its_fingerprint(self):
        head = self.commit({"package.json": pkg("vitest")})
        self.write({"node_modules/vitest/package.json": installed("2.1.9")})
        self.assertEqual(self.fp("r3", head), self.fp("r3", head))


class RustPin(_Repo):
    stack = "rust"

    def setUp(self):
        super().setUp()
        self.files = {"Cargo.toml": '[package]\nname = "p"\nversion = "0.1.0"\nedition = "2021"\n',
                      "src/lib.rs": "pub fn f() -> u8 { 1 }\n"}

    def test_the_toolchain_toml_pin_changes_the_run_fingerprint(self):
        old = self.fp("run", self.commit({**self.files, "rust-toolchain.toml": '[toolchain]\nchannel = "1.80.0"\n'}))
        new = self.fp("run", self.commit({"rust-toolchain.toml": '[toolchain]\nchannel = "1.81.0"\n'}))
        self.assertNotEqual(old, new)

    def test_a_plain_rust_toolchain_pin_changes_the_r3_fingerprint(self):
        old = self.fp("r3", self.commit({**self.files, "rust-toolchain": "1.80.0\n"}))
        new = self.fp("r3", self.commit({"rust-toolchain": "1.81.0\n"}))
        self.assertNotEqual(old, new)

    def test_the_pin_in_the_project_dir_counts_too(self):
        crate = {f"crate/{p}": t for p, t in self.files.items()}
        old = self.fp("run", self.commit({**crate, "crate/rust-toolchain": "1.80.0\n"}), "--project-dir", "crate")
        new = self.fp("run", self.commit({"crate/rust-toolchain": "1.81.0\n"}), "--project-dir", "crate")
        self.assertNotEqual(old, new)


# `mvn --version` as Maven prints it: the JDK it runs on (JAVA_HOME's) in the `Java version:` line
MVN = r'''#!/usr/bin/env python3
import os
here = os.path.dirname(os.path.abspath(__file__))
print("Apache Maven 3.9.11 (3e54c93a704957b63ee3494413a2b544fd3d825b)")
print("Maven home: /opt/maven")
print("Java version: " + open(os.path.join(here, "java-version")).read().strip() + ", vendor: Test, runtime: "
      + os.environ.get("JAVA_HOME", "(none)"))
'''


class Jdk(_Repo):
    """the kit's Java adapter (tests/fixtures/adapters/maven.toml): its probe of `mvn --version` keeps the JDK line."""
    stack = "maven"

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "mvn"), "w") as f:
            f.write(MVN)
        os.chmod(os.path.join(self.bin, "mvn"), 0o755)
        self.java("17.0.9")
        os.environ["PATH"] = self.bin + os.pathsep + os.environ["PATH"]
        os.environ["JAVA_HOME"] = "/opt/jdk-17"
        self.head = self.commit({"pom.xml": "<project/>\n"})

    def java(self, version):
        with open(os.path.join(self.bin, "java-version"), "w") as f:
            f.write(version + "\n")

    def fp(self, part="run", head=None, *extra):
        return super().fp(part, head or self.head, "--adapter", MAVEN, *extra)

    def test_the_jdk_version_changes_the_run_fingerprint(self):
        old = self.fp()
        self.java("21.0.5")
        self.assertNotEqual(self.fp(), old)

    def test_java_home_reaches_the_probe(self):
        old = self.fp()
        os.environ["JAVA_HOME"] = "/opt/jdk-21"
        self.assertNotEqual(self.fp(), old)

    def test_the_probe_line_names_maven_and_the_jdk(self):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", self.head, "--head", self.head, "--stack", "maven",
                          "--adapter", MAVEN, "--fingerprint", "run"])
        probes = json.loads(r.stdout)["probes"]
        self.assertEqual(probes[0], "mvn --version: Apache Maven 3.9.11 (3e54c93a704957b63ee3494413a2b544fd3d825b); "
                                    "Java version: 17.0.9, vendor: Test, runtime: /opt/jdk-17", probes)


class _Runners(Case):
    """minirun with two runners (`fast` when the checkout holds fast.flag) and a fixture dir with a `runtime-fast/`
    variant: the `runtime/` project plus fast.flag, so its controls run `mini test --fast`."""

    def setUp(self):
        super().setUp()
        self.runners = self.adapter(with_runners(adapter_text()))
        self.fx = os.path.join(self.tmp, "fx")
        shutil.copytree(MINIRUN_FX, self.fx)
        shutil.copytree(os.path.join(self.fx, "runtime"), os.path.join(self.fx, "runtime-fast"))
        with open(os.path.join(self.fx, "runtime-fast", "project", "fast.flag.r0"), "w") as f:
            f.write("")

    def run_part(self, which, head, *extra):
        r = _kit.run_cli([which, "--repo", self.repo, "--base", self.base, "--head", head, "--stack", "minirun",
                          "--adapter", self.runners, "--fixtures", self.fx, "--test-paths", "tests/**",
                          "--r0", self.cache, *extra])
        self.assertIn(r.returncode, (0, 1), r.stderr + r.stdout)
        return json.loads(r.stdout)["checks"]["R0"]

    def fingerprint(self, part, head):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", self.base, "--head", head, "--stack", "minirun",
                          "--adapter", self.runners, "--fixtures", self.fx, "--fingerprint", part])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout)["fingerprint"]


class FixtureVariant(_Runners):
    def test_the_variant_the_head_picks_changes_the_r3_fingerprint(self):
        plain = self.fingerprint("r3", self.base)
        fast = self.fingerprint("r3", self.commit({"fast.flag": ""}))
        self.assertNotEqual(plain, fast)

    def test_the_controls_run_the_variant_of_the_heads_runner_not_the_callers(self):
        head = self.commit({"fast.flag": ""})
        os.remove(os.path.join(self.repo, "fast.flag"))  # the caller's tree picks `plain`; the head picks `fast`
        c = self.run_part("red", head)
        self.assertEqual((c["status"], c["ran"]), ("pass", True), c)
        self.assertEqual(c["fingerprint"], self.fingerprint("run", head))
        controls = [x for x in self.calls() if x.startswith("test ") and "ctl.mini" in x]
        self.assertTrue(controls, self.calls())
        self.assertEqual([x for x in controls if not x.startswith("test --fast ")], [], controls)

    def test_the_r3_control_runs_the_variant_of_the_heads_runner_not_the_callers(self):
        # runtime-fast/ has no strong fixture, runtime/ has one: the case tells the two variants apart
        shutil.rmtree(os.path.join(self.fx, "runtime-fast", "r3", "strong"))
        head = self.commit({"fast.flag": "", "src/calc.mini": "fn add(a, b) { a + b + 0 }\n"})
        os.remove(os.path.join(self.repo, "fast.flag"))  # the caller's tree picks `plain`; the head picks `fast`
        c = self.run_part("mutants", head)
        got = {x["case"]: (x["status"], x["got"]) for x in c["cases"]}
        self.assertEqual(got["r3-strong"], ("unproven", "no fixture runtime/r3/strong/"), c)
        self.assertEqual(got["r3-weak"][0], "pass", c)
        self.assertEqual(c["fingerprint"], self.fingerprint("r3", head))


class CachedPassNotReused(_Runners):
    """A2: a pass cached before the change is not reused; the part reads `(ran)`."""

    def test_an_r3_pass_cached_before_a_runner_switch_is_not_reused(self):
        before = self.commit({"src/calc.mini": "fn add(a, b) { a + b + 0 }\n"})
        c = self.run_part("mutants", before)
        self.assertEqual((c["status"], c["ran"]), ("pass", True), c)
        self.assertEqual(self.run_part("mutants", before)["ran"], False)  # the same tree: the pass is reused
        after = self.commit({"fast.flag": ""})
        c = self.run_part("mutants", after)
        self.assertRegex(c["note"], r"^runtime half \(r3\): fingerprint [0-9a-f]{12} \(ran\); ", c)
        self.assertTrue(c["ran"], c)

    def test_a_run_pass_cached_before_a_jdk_change_is_not_reused(self):
        with open(os.path.join(self.tmp, "version"), "w") as f:
            f.write("mini 1.0.0\nJava version: 17.0.9, vendor: Test\n")
        r, env = self.red()
        self.assertTrue(env["checks"]["R0"]["ran"], env["checks"]["R0"])
        with open(os.path.join(self.tmp, "version"), "w") as f:
            f.write("mini 1.0.0\nJava version: 21.0.5, vendor: Test\n")
        r, env = self.red()
        c = env["checks"]["R0"]
        self.assertRegex(c["note"], r"^runtime half \(run\): fingerprint [0-9a-f]{12} \(ran\); ", c)
        self.assertTrue(c["ran"], c)


class TreeInputLines(unittest.TestCase):
    """guards: the lines tree_inputs reads from a tree, as the fingerprint hashes them (values from the spec)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def write(self, rel, text):
        full = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)

    def test_ts_names_the_runner_its_variant_and_the_installed_versions(self):
        from scripts.mech_review import r0, r0_runtime, stack
        self.write("package.json", pkg("jest"))
        self.write("node_modules/jest/package.json", installed("29.7.0"))
        self.write("node_modules/@stryker-mutator/core/package.json", installed("10.0.0"))
        fx = r0.builtin_fixtures("ts")
        self.assertEqual(r0_runtime.tree_inputs(stack.TsAdapter(), "r3", fx, self.root), (
            ["runner: jest", "fixture variant: runtime-jest", "node_modules/jest: 29.7.0",
             "node_modules/@stryker-mutator/core: 10.0.0", "node_modules/@stryker-mutator/jest-runner: (not installed)"],
            "jest"))
        self.assertEqual(r0_runtime.tree_inputs(stack.TsAdapter(), "run", fx, self.root)[0],
                         ["runner: jest", "fixture variant: runtime-jest", "node_modules/jest: 29.7.0"])

    def test_a_vitest_checkout_runs_the_plain_variant(self):
        from scripts.mech_review import r0, r0_runtime, stack
        self.write("package.json", pkg("vitest"))
        self.assertEqual(r0_runtime.tree_inputs(stack.TsAdapter(), "run", r0.builtin_fixtures("ts"), self.root)[0],
                         ["runner: vitest", "fixture variant: runtime", "node_modules/vitest: (not installed)"])

    def test_no_runner_and_no_fixtures_read_none(self):
        from scripts.mech_review import r0_runtime, stack
        self.assertEqual(r0_runtime.tree_inputs(stack.PythonAdapter(), "run", None, self.root),
                         (["runner: (none)", "fixture variant: (none)"], None))

    def test_an_installed_version_that_does_not_read(self):
        from scripts.mech_review import stack
        crate = self.root
        for raw, want in (("not json", "(unreadable)"), ("[1]", "(unreadable)"), ('{"version": 3}', "(unreadable)"),
                          ("[" * 5000 + "]" * 5000, "(unreadable)"), (installed("v" * 150), "v" * 100)):
            with self.subTest(raw=raw[:20]):
                self.write("node_modules/vitest/package.json", raw)
                self.assertEqual(stack.installed_version(crate, "vitest"), want)
        self.assertEqual(stack.installed_version(crate, "@scope/none"), "(not installed)")

    def test_rust_names_each_pin_file_with_its_digest(self):
        from scripts.mech_review import stack
        self.write("rust-toolchain.toml", '[toolchain]\nchannel = "1.80.0"\n')
        self.write("crate/rust-toolchain", "1.80.0\n")
        got = stack.RustAdapter().toolchain_pins(self.root, "crate", "run")
        self.assertEqual(got, [
            "rust-toolchain.toml: sha256 c5f938b9c9c5ac70f52219ffd280dd2cc62b306b6f715bab3e71e416fbdf9752",
            "crate/rust-toolchain: sha256 1cb49918acdf75802ef99971dbd732b0b34847ef03a8d830e53c237c0fe9c94b"])
        self.assertEqual(stack.RustAdapter().toolchain_pins(self.root, ".", "r3"), [got[0]])
        self.assertEqual(stack.Adapter().toolchain_pins(self.root, ".", "run"), [])


GRADLE = r'''#!/usr/bin/env python3
print("Gradle 8.10")
print("Kotlin:        1.9.24")
print("Launcher JVM:  21.0.5 (Eclipse Adoptium 21.0.5+11-LTS)")
'''


class JdkLine(unittest.TestCase):
    """guards: the probe keeps a build tool's JDK line beside its version line, and nothing else."""

    def probe(self, text):
        from scripts.mech_review import r0_runtime
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        prog = os.path.join(tmp.name, "tool")
        with open(prog, "w") as f:
            f.write(text)
        os.chmod(prog, 0o755)
        with mock.patch.dict(os.environ):
            os.environ.pop("MECH_TEST_STUB", None)
            return r0_runtime.probe([prog, "--version"], False, ())

    def test_gradles_launcher_jvm_line_is_kept(self):
        self.assertTrue(self.probe(GRADLE).endswith(
            " --version: Gradle 8.10; Launcher JVM:  21.0.5 (Eclipse Adoptium 21.0.5+11-LTS)"))

    def test_a_tool_with_no_jdk_line_keeps_one_line(self):
        self.assertTrue(self.probe('#!/usr/bin/env python3\nprint("tool 1.0")\nprint("Kotlin: 1.9")\n').endswith(
            " --version: tool 1.0"))

    def test_the_jdk_line_comes_before_the_exit_code(self):
        self.assertTrue(self.probe('#!/usr/bin/env python3\nimport sys\nprint("tool 1.0")\nprint("JVM: 17")\n'
                                   'sys.exit(3)\n').endswith(" --version: tool 1.0; JVM: 17 (exit 3)"))


del Case  # imported for subclassing: not run again from this module


if __name__ == "__main__":
    unittest.main()
