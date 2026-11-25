"""The Java reference adapter (#22): tests/fixtures/adapters/java.toml, a test fixture and no built-in, runs Java end
to end through the CLI (cli.main in this process) on a Maven/JUnit 5 fixture repo (tests/fixtures/java: base/, and one
head per case laid over it): R2, R1, R4, R3 through PIT, and R0's static and runtime halves.

The real toolchain (mvn and a JDK; Maven Central for the first run) gives the real runner's output: no stub stands in.
A machine without it reads `n/a` (env), never pass, and no test is skipped: each asserts what this machine must give
(the pattern of test_r0_runtime_builtins). The no-JDK cases hide mvn from PATH, or point JAVA_HOME at no JDK, and run
everywhere. R0's runtime half runs only on the stack's target OS (linux): elsewhere it is n/a, named."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import _kit
from scripts.mech_review import adapter_file, r0_runtime

FIXTURES = os.path.join(_kit.ROOT, "tests", "fixtures")
JAVA = os.path.join(FIXTURES, "adapters", "java.toml")
REPO = os.path.join(FIXTURES, "java")
CASES = ("r2", "red", "weak", "broken")
TEST = "src/test/java/com/example/CalcTest.java"
CALC = "src/main/java/com/example/Calc.java"


def toolchain():
    """mvn on PATH, and a JDK it starts with (`mvn --version` exits 0)."""
    mvn = shutil.which("mvn")
    return bool(mvn) and subprocess.run([mvn, "--version"], capture_output=True).returncode == 0


TOOLCHAIN = toolchain()
LINUX = r0_runtime.host_os() == "linux"


def copy_tree(src, dst):
    for top, _, files in os.walk(src):
        for fn in files:
            full = os.path.join(top, fn)
            out = os.path.join(dst, os.path.relpath(full, src))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copyfile(full, out)


class Fixture(unittest.TestCase):
    """the fixture repo: `main` holds base/, a branch per case holds its head (the case's files over base/)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(self.tmp, "repo")
        copy_tree(os.path.join(REPO, "base"), self.repo)
        self.git("init", "-q", "-b", "main")
        self.commit("base")
        for case in CASES:
            self.git("checkout", "-q", "-b", case, "main")
            copy_tree(os.path.join(REPO, case), self.repo)
            self.commit(case)
        self.git("checkout", "-q", "main")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                               "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)

    def cli(self, check, head, *extra, rc=(0, 1)):
        r = _kit.run_cli([check, "--repo", self.repo, "--base", "main", "--head", head, "--stack", "java",
                          "--adapter", JAVA, "--test-paths", "src/test/**", *extra])
        self.assertIn(r.returncode, rc, r.stderr + r.stdout)
        return json.loads(r.stdout)

    def branch(self, name, start, files):
        """a branch from start with files ({path: text}, or {path: (old, new)} to replace in the file there)."""
        self.git("checkout", "-q", "-b", name, start)
        for path, text in files.items():
            full = os.path.join(self.repo, path)
            if isinstance(text, tuple):
                with open(full) as f:
                    old = f.read()
                self.assertIn(text[0], old)
                text = old.replace(*text)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(text)
        self.commit(name)
        self.git("checkout", "-q", "main")
        return name

    def red(self, head, *extra):
        return self.cli("red", head, "--head-branch", "claude/t22", *extra)

    def check_env(self, check):
        self.assertEqual(check["status"], "n/a", check)
        self.assertIn("(env)", check["note"], check)


def ents(env, check):
    return [(e["severity"], e["file"], e["line"], e["problem"]) for e in env["entries"] if e["check"] == check]


class Reference(unittest.TestCase):
    def test_it_is_marked_a_test_fixture_and_names_linux_and_its_commands(self):
        with open(JAVA) as f:
            head = f.read().split("\nformat = 1\n")[0]
        self.assertTrue(head.startswith("# TEST FIXTURE, NOT A SUPPORTED BUILT-IN."), head)
        self.assertIn("#25 deletes it", head)
        a = adapter_file.load(JAVA)
        self.assertEqual((a.name, a.target_os, a.manifests), ("java", "linux", ("pom.xml",)))
        self.assertEqual(a.commands, {"install": "mvn -B -ntp dependency:go-offline",
                                      "build": "mvn -B -ntp test-compile",
                                      "lint": "mvn -B -ntp test-compile -Dmaven.compiler.showWarnings=true "
                                              "-Dmaven.compiler.failOnWarning=true",
                                      "test": "mvn -B -ntp test"})
        self.assertEqual(a.test_argv(a.commands["test"], TEST, "CalcTest.adds"),
                         ["mvn", "-B", "-ntp", "test", "-Dtest=CalcTest#adds"])
        self.assertFalse(os.path.exists(os.path.join(_kit.ROOT, "scripts", "mech_review", "adapters", "java.toml")))
        self.assertIn("org.pitest:pitest-maven:1.17.4:mutationCoverage", a.mutation_tool["args"])  # S5: pinned here


class NotOffered(Fixture):
    def test_resolve_and_auto_never_offer_the_reference(self):
        r = _kit.run_cli(["resolve", "--repo", self.repo, "--base", "main", "--head", "main"])
        self.assertEqual(json.loads(r.stdout)["stack"], None, r.stdout)
        r = _kit.run_cli(["r2", "--repo", self.repo, "--base", "main", "--head", "r2", "--stack", "java"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("argument --stack: invalid choice: 'java'", r.stderr)


class R2(Fixture):
    def test_removed_skipped_and_expected_value_entries(self):
        env = self.cli("r2", "r2")
        self.assertEqual(ents(env, "R2"), [
            ("confirm", TEST, 13, "expected value changed in `CalcTest.adds`: was 3, now 4"),
            ("fail", TEST, 17, "test fn `CalcTest.subtracts` removed"),
            ("fail", TEST, 19, "test `CalcTest.negates` marked @Disabled, or with a condition that can skip it")])

    def test_r0_static_half_proves_the_reference(self):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", "main", "--head", "main", "--stack", "java",
                          "--adapter", JAVA, "--test-paths", "src/test/**"])
        self.assertEqual(r.returncode, 0, r.stderr)
        c = json.loads(r.stdout)["checks"]["R0"]
        self.assertEqual((c["status"], c["note"]), ("pass", "static half: 17 of 17 cases proved"), c)


class NoJdk(Fixture):
    """without a JDK the result is n/a (env), never a pass: mvn not on PATH, or mvn with JAVA_HOME at no JDK."""

    def no_mvn(self):
        bin_ = os.path.join(self.tmp, "bin")
        os.makedirs(bin_)
        os.symlink(shutil.which("git"), os.path.join(bin_, "git"))
        return mock.patch.dict(os.environ, {"PATH": bin_})

    def test_no_mvn_on_path(self):
        with self.no_mvn():
            red = self.red("red", "--r0", os.path.join(self.tmp, "r0"))
            mut = self.cli("mutants", "weak", "--r0", os.path.join(self.tmp, "r0"))
        for c in ("R1", "R4"):
            self.assertEqual(red["checks"][c]["status"], "n/a", red["checks"][c])
            self.assertTrue(red["checks"][c]["note"].startswith("toolchain absent: `mvn` not found (env)"), red["checks"][c])
        self.assertEqual(mut["checks"]["R3"]["note"], "pit not installed (env): `mvn` not runnable "
                                                     "(mutation.tool.command); install it (setup-command) or set mutants-cmd")
        self.assertEqual(ents(red, "R1") + ents(red, "R4") + ents(mut, "R3"), [])
        for env in (red, mut):
            self.assertEqual(env["checks"]["R0"]["status"], "n/a", env["checks"]["R0"])

    def test_java_home_at_no_jdk(self):
        with mock.patch.dict(os.environ, {"JAVA_HOME": os.path.join(self.tmp, "no-jdk")}):
            red = self.red("red")
        for c in ("R1", "R4"):
            self.check_env(red["checks"][c])
        if shutil.which("mvn"):
            self.assertIn("JAVA_HOME environment variable is not defined correctly", red["checks"]["R1"]["note"])


class RoundOneR2(Fixture):
    """review round 1 of #22: cheats R2 must name on the reference adapter."""

    def test_a_condition_annotation_is_a_skip(self):  # B4
        head = self.branch("cond", "main", {TEST: ("    @Test\n    void subtracts", "    @Test\n    @DisabledOnOs(OS.LINUX)\n"
                                                   "    void subtracts")})
        head = self.branch("cond2", head, {TEST: ("    @Test\n    void negates", "    @Test\n    @EnabledOnOs(OS.WINDOWS)\n"
                                                  "    void negates")})
        self.assertEqual([(s, p) for s, _, _, p in ents(self.cli("r2", head), "R2")], [
            ("fail", "test `CalcTest.subtracts` marked @Disabled, or with a condition that can skip it"),
            ("fail", "test `CalcTest.negates` marked @Disabled, or with a condition that can skip it")])

    def test_pit_config_in_the_pom_and_a_skip_annotation_are_named(self):  # B3
        pom = ("<artifactId>pitest-maven</artifactId>\n        <version>1.17.4</version>\n",
               "<artifactId>pitest-maven</artifactId>\n        <version>1.17.4</version>\n        <configuration>\n"
               "          <excludedMethods>\n            <param>mul</param>\n          </excludedMethods>\n"
               "        </configuration>\n")
        head = self.branch("hide", "weak", {"pom.xml": pom, CALC: ("    public static int mul(", "    @DoNotMutate\n"
                                                                   "    public static int mul(")})
        got = [(e["severity"], e["class"], e["file"], e["problem"]) for e in self.cli("r2", head)["entries"]]
        self.assertEqual(len(got), 2, got)
        self.assertTrue(any(f == "pom.xml" and c == "needs-human" and "PIT config (pom.xml or .mvn/)" in p for _, c, f, p in got), got)
        self.assertTrue(any(f == CALC and c == "needs-human" and "@DoNotMutate" in p for _, c, f, p in got), got)

    def test_a_spaced_or_commented_marker_is_still_a_skip(self):  # round 2, B1
        head = self.branch("spaced", "main", {TEST: ("    @Test\n    void subtracts", "    @ /* later */ Disabled\n"
                                                     "    @Test\n    void subtracts")})
        head = self.branch("escaped", head, {TEST: ("    @Test\n    void negates", "    @Test \\u0040Disabled\n    void negates")})
        self.assertEqual([(s, p) for s, _, _, p in ents(self.cli("r2", head), "R2")], [
            ("fail", "test `CalcTest.subtracts` marked @Disabled, or with a condition that can skip it"),
            ("fail", "test `CalcTest.negates` marked @Disabled, or with a condition that can skip it")])

    def test_maven_config_and_suffix_named_skip_annotations_are_named(self):  # round 2, B2 and B4
        head = self.branch("mvncfg", "weak", {".mvn/maven.config": "-DexcludedMethods=mul\n",
                                              ".mvn/jvm.config": "-Dx=y\n", ".mvn/extensions.xml": "<extensions/>\n",
                                              CALC: ("    public static int mul(", "    @ MyGenerated\n"
                                                     "    public static int mul(")})
        got = sorted((e["file"], e["class"]) for e in self.cli("r2", head)["entries"])
        self.assertEqual(got, [(".mvn/extensions.xml", "needs-human"), (".mvn/jvm.config", "needs-human"),
                               (".mvn/maven.config", "needs-human"), (CALC, "needs-human")])

    def test_all_with_the_adapter_proves_it_with_its_fixtures(self):  # S8
        c = self.cli("all", "main", "--head-branch", "claude/t22")["checks"]["R0"]
        self.assertEqual((c["status"], c["note"]), ("pass", "static half: 17 of 17 cases proved"), c)


class Run(Fixture):
    """R1 and R4 through [run]: surefire's -Dtest=Class#method, read from its counts."""

    def test_a_new_test_red_on_the_base_passes_r1_and_r4(self):
        env = self.red("red")
        if not TOOLCHAIN:
            return [self.check_env(env["checks"][c]) for c in ("R1", "R4")]
        self.assertEqual({c: env["checks"][c] for c in ("R1", "R4")}, {
            "R1": {"status": "pass", "note": "1 of 1 new or changed test(s) fail on the base's production code "
                                             "(1 compile-red)"},
            "R4": {"status": "pass", "note": "1 new or changed test(s) run 5x at head"}})

    def test_a_guard_test_fails_r1_and_a_test_red_at_head_fails_r4(self):
        env = self.red("broken")
        if not TOOLCHAIN:
            return [self.check_env(env["checks"][c]) for c in ("R1", "R4")]
        self.assertEqual(ents(env, "R1"), [("fail", TEST, 27, "no new or changed test fails without this PR's "
                                                          "production change: `CalcTest.addsOnes` pass on the base's "
                                                          "code too")])
        self.assertEqual(ents(env, "R4"), [("fail", TEST, 27, "test `CalcTest.addsOnes` failed 5 of 5 runs at head "
                                                          "(fail)")])

    def test_a_failing_test_that_prints_the_jdk_message_is_still_a_fail(self):  # B2
        say = ('        System.out.println("The JAVA_HOME environment variable is not defined correctly");\n'
               '        System.out.println("JAVA_HOME not found");\n')
        head = self.branch("printer", "broken", {TEST: ("    void addsOnes() {\n", "    void addsOnes() {\n" + say)})
        env = self.red(head)
        if not TOOLCHAIN:
            return self.check_env(env["checks"]["R4"])
        self.assertEqual([(s, p) for s, _, _, p in ents(env, "R4")],
                         [("fail", "test `CalcTest.addsOnes` failed 5 of 5 runs at head (fail)")])


class Mutation(Fixture):
    """R3 through PIT: the changed classes, then ekit's changed-line filter."""

    def test_a_weak_test_leaves_missed_mutants_on_the_changed_line(self):
        env = self.cli("mutants", "weak")
        if not TOOLCHAIN:
            return self.check_env(env["checks"]["R3"])
        self.assertEqual(ents(env, "R3"), [
            ("fail", CALC, 16, f"MISSED mutant {CALC}:16: MathMutator in mul: Replaced integer multiplication with "
                               "division"),
            ("fail", CALC, 16, f"MISSED mutant {CALC}:16: PrimitiveReturnsMutator in mul: replaced int return with 0 "
                               "for com/example/Calc::mul")])

    def test_a_stray_file_outside_src_main_java_leaves_r3_on(self):  # B1
        head = self.branch("stray", "weak", {"tools/Stray.java": "class Stray {}\n"})
        env = self.cli("mutants", head)
        if not TOOLCHAIN:
            return self.check_env(env["checks"]["R3"])
        self.assertEqual([(e["line"], e["problem"].split(": ", 1)[1]) for e in env["entries"]], [
            (16, "MathMutator in mul: Replaced integer multiplication with division"),
            (16, "PrimitiveReturnsMutator in mul: replaced int return with 0 for com/example/Calc::mul")])
        self.assertIn("; not mutated: tools/Stray.java (under none of mutation.tool.module_roots: src/main/java)",
                      env["checks"]["R3"]["note"])

    def test_a_second_top_level_class_in_a_changed_file_is_mutated(self):  # S6
        helper = "\nfinal class Helper {\n    static int twice(int n) {\n        return n + n;\n    }\n}\n"
        test = ("    @Test\n    void subtracts", "    @Test\n    void twice() {\n        assertTrue(Helper.twice(2) >= 0);"
                "\n    }\n\n    @Test\n    void subtracts")
        head = self.branch("helper", "main", {CALC: ("    }\n}\n", "    }\n}\n" + helper), TEST: test})
        env = self.cli("mutants", head)
        if not TOOLCHAIN:
            return self.check_env(env["checks"]["R3"])
        self.assertEqual([(e["line"], e["problem"].split(": ", 1)[1]) for e in env["entries"]], [
            (22, "PrimitiveReturnsMutator in twice: replaced int return with 0 for com/example/Helper::twice"),
            (22, "MathMutator in twice: Replaced integer addition with subtraction")])

    def test_a_file_in_the_default_package_leaves_r3_on(self):  # round 2, B3: `{package}*` was a bare `*`
        head = self.branch("toplevel", "weak", {"src/main/java/Top.java": "public final class Top {\n    private Top() {\n"
                                                "    }\n}\n"})
        env = self.cli("mutants", head)
        if not TOOLCHAIN:
            return self.check_env(env["checks"]["R3"])
        self.assertEqual(env["checks"]["R3"]["status"], "fail", env["checks"]["R3"])
        self.assertEqual([(e["file"], e["line"]) for e in env["entries"]], [(CALC, 16), (CALC, 16)])

    def test_a_strong_test_leaves_none(self):
        env = self.cli("mutants", "red")
        if not TOOLCHAIN:
            return self.check_env(env["checks"]["R3"])
        self.assertEqual(env["checks"]["R3"]["status"], "pass", env["checks"]["R3"])
        self.assertTrue(env["checks"]["R3"]["note"].startswith("8/8 tested: 0 missed in the diff, 0 missed outside the "
                                                               "diff, 0 unlocated, 8 caught"), env["checks"]["R3"])


class RuntimeHalf(Fixture):
    """R0's runtime half on the reference: the census matches every test the runner lists (JUnit's dry run), the
    runner controls read right, and the R3 control tells the weak fixture from the strong one."""

    def test_run_part(self):
        c = self.red("red", "--r0", os.path.join(self.tmp, "r0"))["checks"]["R0"]
        if not LINUX:
            return self.assertIn("the stack runs on linux (target-os)", c["note"], c)
        if not TOOLCHAIN:
            self.assertEqual(c["status"], "n/a", c)
            return self.assertTrue(all(x["got"].startswith("env") for x in c["cases"] if x["status"] == "n/a"), c)
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual({x["case"]: x["status"] for x in c["cases"]}, dict.fromkeys(
            ["census-repo", "census-fixtures", "control-pass", "control-fail", "control-skipped", "control-build",
             "control-no-such-test", "skip-idiom"], "pass"))
        self.assertEqual(c["census"], {"repo": {"found": 4, "listed": 4, "misses": []},
                                       "fixtures": {"found": 4, "listed": 4, "misses": []}})
        self.assertTrue(c["probes"][0].startswith("mvn --version: Apache Maven "), c["probes"])

    def test_r3_part(self):
        c = self.cli("mutants", "red", "--r0", os.path.join(self.tmp, "r0"))["checks"]["R0"]
        if not LINUX:
            return self.assertIn("the stack runs on linux (target-os)", c["note"], c)
        if not TOOLCHAIN:
            return self.assertEqual({x["case"]: x["status"] for x in c["cases"]}, {"r3-weak": "n/a", "r3-strong": "n/a"})
        self.assertEqual((c["status"], {x["case"]: x["status"] for x in c["cases"]}),
                         ("pass", {"r3-weak": "pass", "r3-strong": "pass"}), c)


class Commands(Fixture):
    def test_each_command_runs_on_the_fixture(self):
        a = adapter_file.load(JAVA)
        if not TOOLCHAIN:
            return self.check_env(self.red("red")["checks"]["R1"])
        for k in ("install", "build", "lint", "test"):
            with self.subTest(k):
                r = subprocess.run(a.commands[k].split(), cwd=self.repo, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertIn("Tests run: 3, Failures: 0, Errors: 0, Skipped: 0", r.stdout)


if __name__ == "__main__":
    unittest.main()
