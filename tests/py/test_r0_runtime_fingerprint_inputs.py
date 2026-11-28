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

    def stryker(self, where, version):
        """a `stryker` at where that answers --version with version, as Stryker 10 does (its version alone)"""
        os.makedirs(where, exist_ok=True)
        prog = os.path.join(where, "stryker")
        with open(prog, "w") as f:
            f.write(f"#!/usr/bin/env python3\nprint({version!r})\n")
        os.chmod(prog, 0o755)
        return prog

    def r3_probes(self, head, prog):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", head, "--head", head, "--stack", "ts",
                          "--fingerprint", "r3", "--mutants-cmd", prog])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        got = json.loads(r.stdout)
        return got["fingerprint"], got["probes"]

    def test_the_mutants_cmd_strykers_version_changes_the_r3_fingerprint(self):
        """review F6: CI runs the pinned Stryker passed as --mutants-cmd (outside the checkout), not node_modules'"""
        head = self.commit({"package.json": pkg("vitest")})
        prog = self.stryker(os.path.join(self.tmp, "stryker-install"), "10.0.0")
        old, probes = self.r3_probes(head, prog)
        self.assertEqual(probes[1:], [f"{prog} --version: 10.0.0"], probes)
        self.stryker(os.path.join(self.tmp, "stryker-install"), "10.1.0")
        self.assertNotEqual(self.r3_probes(head, prog)[0], old)

    def test_a_mutants_cmd_in_the_checkout_is_not_probed(self):
        head = self.commit({"package.json": pkg("vitest")})
        prog = self.stryker(os.path.join(self.repo, "node_modules", ".bin"), "10.0.0")
        self.assertEqual(self.r3_probes(head, prog)[1][1:],
                         [f"{prog} --version: not probed (in the reviewed checkout: {os.path.realpath(prog)})"])

    def plant(self):
        """(marker, the planted node's dir, a Stryker whose `#!/usr/bin/env node` finds node on PATH, a dir outside the
        checkout with a node of its own): the planted node, in the checkout, touches the marker when it runs"""
        marker = os.path.join(self.tmp, "planted-node-ran")
        planted = os.path.join(self.repo, "bin", "node")
        outside = os.path.join(self.tmp, "outside-bin", "node")
        for path, text in ((planted, f"#!/bin/sh\ntouch {marker}\necho v99.0.0\n"),
                           (outside, "#!/bin/sh\necho 10.0.0 from the node outside\n")):
            os.makedirs(os.path.dirname(path))
            with open(path, "w") as f:
                f.write(text)
            os.chmod(path, 0o755)
        prog = os.path.join(self.tmp, "stryker-install", "stryker")
        os.makedirs(os.path.dirname(prog))
        with open(prog, "w") as f:
            f.write("#!/usr/bin/env node\nconsole.log('10.0.0')\n")
        os.chmod(prog, 0o755)
        return marker, os.path.dirname(planted), prog, os.path.dirname(outside)

    def test_a_mutants_cmd_whose_node_is_in_the_checkout_runs_none_of_it(self):
        """review round 2, F7; round 3: a node planted in the checkout, first on PATH, never runs: the probe's PATH
        drops that entry, so Stryker's `env node` finds the node outside (the node probe names the planted one)"""
        head = self.commit({"package.json": pkg("vitest")})
        marker, planted, prog, outside = self.plant()
        os.environ["PATH"] = os.pathsep.join([planted, outside, os.environ["PATH"]])
        real = os.path.realpath(os.path.join(planted, "node"))
        self.assertEqual(self.r3_probes(head, prog)[1], [
            f"node --version: not probed (in the reviewed checkout: {real})",
            f"{prog} --version: 10.0.0 from the node outside"])
        self.assertFalse(os.path.exists(marker))

    def test_a_node_linked_into_the_checkout_is_not_probed(self):
        """a dir outside the checkout whose `node` links into it: the interpreter's real path is checked"""
        head = self.commit({"package.json": pkg("vitest")})
        marker, planted, prog, outside = self.plant()
        os.remove(os.path.join(outside, "node"))
        os.symlink(os.path.join(planted, "node"), os.path.join(outside, "node"))
        os.environ["PATH"] = os.pathsep.join([outside, os.environ["PATH"]])
        real = os.path.realpath(os.path.join(planted, "node"))
        self.assertEqual(self.r3_probes(head, prog)[1][1],
                         f"{prog} --version: not probed (its interpreter `node` in the reviewed checkout: {real})")
        self.assertFalse(os.path.exists(marker))

    def test_a_relative_path_entry_never_reaches_the_probe(self):
        """review round 3, R2: a relative PATH entry resolves against the probe's own dir, where the engine's check of
        `node` never looked: the probe's PATH holds only absolute entries, links resolved, none in the checkout"""
        head = self.commit({"package.json": pkg("vitest")})
        marker, planted, prog, outside = self.plant()
        up = "../" * (len(os.path.realpath(tempfile.gettempdir()).strip(os.sep).split(os.sep)) + 1)
        rel = up + os.path.realpath(planted).lstrip(os.sep)  # the planted bin, as the probe's dir reaches it
        link = os.path.join(self.tmp, "linked-bin")
        os.symlink(planted, link)  # an absolute entry whose real path is in the checkout
        os.environ["PATH"] = os.pathsep.join([rel, "", ".", link, outside, os.environ["PATH"]])
        probes = self.r3_probes(head, prog)[1]
        self.assertFalse(os.path.exists(marker), probes)
        self.assertEqual(probes[1], f"{prog} --version: 10.0.0 from the node outside", probes)

    def test_a_mutants_cmd_that_is_no_absolute_path_is_not_probed(self):
        """review round 2, M4: a bare name or a relative path enters the key by its words only"""
        head = self.commit({"package.json": pkg("vitest")})
        for cmd in ("stryker", "node_modules/.bin/stryker"):
            with self.subTest(cmd=cmd):
                fp, probes = self.r3_probes(head, cmd)
                self.assertEqual([p.split(":")[0] for p in probes], ["node --version"])

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

    def test_a_pin_that_cannot_be_read_still_gives_a_key(self):
        """review F3: through the seam, a pin open refuses is a named line, never a traceback with no key"""
        head = self.commit({**self.files, "rust-toolchain": "1.80.0\n"})
        real = open

        def refuse(path, *a, **k):
            if str(path).endswith("rust-toolchain"):
                raise PermissionError(13, "Permission denied", path)
            return real(path, *a, **k)

        with mock.patch("builtins.open", refuse):
            self.assertRegex(self.fp("run", head), "^[0-9a-f]{64}$")

    def test_a_pin_in_a_dir_between_the_root_and_the_project_dir_counts(self):
        """rustup takes the nearest pin up from the project dir: a/rust-toolchain for the project a/b"""
        crate = {f"a/b/{p}": t for p, t in self.files.items()}
        old = self.fp("run", self.commit({**crate, "a/rust-toolchain": "1.80.0\n"}), "--project-dir", "a/b")
        new = self.fp("run", self.commit({"a/rust-toolchain": "1.81.0\n"}), "--project-dir", "a/b")
        self.assertNotEqual(old, new)


# `mvn --version` as Maven prints it: the JDK it runs on (JAVA_HOME's) in the `Java version:` line
MVN = r'''#!/usr/bin/env python3
import os
here = os.path.dirname(os.path.abspath(__file__))
open(os.path.join(here, "ran"), "a").close()
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

    def probes(self):
        r = _kit.run_cli(["r0", "--repo", self.repo, "--base", self.head, "--head", self.head, "--stack", "maven",
                          "--adapter", MAVEN, "--fingerprint", "run"])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout)["probes"]

    def test_a_java_home_in_the_reviewed_checkout_is_not_probed(self):
        """mvn would run $JAVA_HOME/bin/java, a file the PR controls: the probe is refused and named, mvn never runs"""
        jdk = os.path.join(self.repo, "jdk")
        os.makedirs(jdk)
        link = os.path.join(self.tmp, "jdk-link")
        os.symlink(jdk, link)
        for java_home in (jdk, link, self.repo):
            with self.subTest(java_home=java_home):
                os.environ["JAVA_HOME"] = java_home
                want = os.path.realpath(java_home)
                self.assertEqual(self.probes()[0], f"mvn --version: not probed (JAVA_HOME in the reviewed checkout: "
                                                   f"{want})")
                self.assertFalse(os.path.exists(os.path.join(self.bin, "ran")))
        os.environ["JAVA_HOME"] = jdk
        old = self.fp()
        self.java("21.0.5")
        self.assertEqual(self.fp(), old)  # nothing of the checkout's JDK reaches the key

    def test_a_relative_java_home_is_not_probed(self):
        """review round 2, F2: a relative JAVA_HOME resolves against wherever mvn runs, not where the engine does: it is
        never passed to a probe, whatever it names"""
        for java_home in ("jdk", "../../" + os.path.relpath(os.path.join(self.repo, "jdk"), "/"), "./x", "~/jdk"):
            with self.subTest(java_home=java_home):
                os.environ["JAVA_HOME"] = java_home
                self.assertEqual(self.probes()[0],
                                 f"mvn --version: not probed (JAVA_HOME is not an absolute path: {java_home})")
                self.assertFalse(os.path.exists(os.path.join(self.bin, "ran")))

    def test_a_per_process_java_home_is_not_probed(self):
        """review round 3, R1: /proc/self/cwd resolves against each process's own cwd: the engine's and mvn's differ"""
        deep = os.path.join(self.tmp, "deep", "a", "b", "c")
        os.makedirs(deep)
        jdk = os.path.join(self.repo, "jdk")
        os.makedirs(jdk)
        here = os.getcwd()
        os.chdir(deep)
        self.addCleanup(os.chdir, here)
        for java_home in ("/proc/self/cwd/../.." + jdk, "/dev/fd/0/../.." + jdk, "/proc/1/root" + jdk):
            with self.subTest(java_home=java_home):
                os.environ["JAVA_HOME"] = java_home
                self.assertEqual(self.probes()[0],
                                 f"mvn --version: not probed (JAVA_HOME names a per-process path: {java_home})")
                self.assertFalse(os.path.exists(os.path.join(self.bin, "ran")))

    def test_the_probe_gets_java_home_resolved(self):
        """review round 3: the probe is handed the path the engine checked (links resolved), never the string"""
        real = os.path.join(self.tmp, "jdks", "jdk-21")
        os.makedirs(real)
        link = os.path.join(self.tmp, "jdk-current")
        os.symlink(real, link)
        os.environ["JAVA_HOME"] = link + os.sep + "."
        self.assertEqual(self.probes()[0], "mvn --version: Apache Maven 3.9.11 (3e54c93a704957b63ee3494413a2b544fd3d"
                                           "825b); Java version: 17.0.9, vendor: Test, runtime: "
                                           + os.path.realpath(real))

    def test_a_java_home_beside_the_checkout_is_probed(self):
        """review round 2, M3: <checkout>2 shares the checkout's prefix and is not in it"""
        os.environ["JAVA_HOME"] = self.repo + "2"
        self.assertEqual(self.probes()[0], "mvn --version: Apache Maven 3.9.11 (3e54c93a704957b63ee3494413a2b544fd3d"
                                           f"825b); Java version: 17.0.9, vendor: Test, runtime: {self.repo}2")

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
             "node_modules/@stryker-mutator/core: 10.0.0",
             "node_modules/@stryker-mutator/jest-runner: (not installed)"],
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
        self.write("crate/inner/rust-toolchain.toml", "x")
        pins = stack.RustAdapter().toolchain_pins(self.root, "crate/inner", "r3")
        self.assertEqual([ln.split(":")[0] for ln in pins],
                         ["rust-toolchain.toml", "crate/rust-toolchain", "crate/inner/rust-toolchain.toml"])
        self.assertEqual(stack.Adapter().toolchain_pins(self.root, ".", "run"), [])

    def test_a_pin_that_does_not_read_is_named_not_read_whole(self):
        """review F3: a committed rust-toolchain link to a huge file, a FIFO, or a file it may not open"""
        from scripts.mech_review import stack
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        huge = os.path.join(outside.name, "huge")
        with open(huge, "wb") as f:
            f.truncate(8 << 20)
        os.symlink(huge, os.path.join(self.root, "rust-toolchain"))
        os.symlink(os.path.join(outside.name, "gone"), os.path.join(self.root, "rust-toolchain.toml"))
        self.assertEqual(stack.RustAdapter().toolchain_pins(self.root, ".", "run"), [
            "rust-toolchain.toml: (unreadable)", "rust-toolchain: (over 65536 bytes)"])
        real = open

        def refuse(path, *a, **k):
            if "rust-toolchain" in str(path):
                raise PermissionError(13, "Permission denied", path)
            return real(path, *a, **k)

        os.remove(os.path.join(self.root, "rust-toolchain"))
        self.write("rust-toolchain", "1.80.0\n")
        with mock.patch("builtins.open", refuse):
            self.assertEqual(stack.RustAdapter().toolchain_pins(self.root, ".", "run"), [
                "rust-toolchain.toml: (unreadable)", "rust-toolchain: (unreadable)"])

    def test_a_pin_at_the_cap_reads_over_it_does_not(self):
        """review round 2, M2: 65536 bytes is a digest, 65537 is over the cap"""
        from scripts.mech_review import stack
        self.write("rust-toolchain", "a" * 65536)
        self.assertEqual(stack.RustAdapter().toolchain_pins(self.root, ".", "run"), [
            "rust-toolchain: sha256 bf718b6f653bebc184e1479f1935b8da974d701b893afcf49e701f3e2f9f9c5a"])
        self.write("rust-toolchain", "a" * 65537)
        self.assertEqual(stack.RustAdapter().toolchain_pins(self.root, ".", "run"),
                         ["rust-toolchain: (over 65536 bytes)"])

    def test_an_oversized_pin_is_never_read_whole(self):
        """review round 2, M1: one read, of at most the cap and a byte"""
        from scripts.mech_review import stack
        self.write("rust-toolchain", "a" * (1 << 20))
        real, sizes = open, []

        class Capped:
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.f.close()

            def read(self, n=-1):
                sizes.append(n)
                return self.f.read(n)

        def opened(path, *a, **k):
            f = real(path, *a, **k)
            return Capped(f) if str(path).endswith("rust-toolchain") else f

        with mock.patch("builtins.open", opened):
            self.assertEqual(stack.RustAdapter().toolchain_pins(self.root, ".", "run"),
                             ["rust-toolchain: (over 65536 bytes)"])
        self.assertEqual(sizes, [65537])

    def test_a_pin_that_is_a_fifo_or_a_dir_is_never_opened(self):
        """a FIFO could block the open: stat says it is one (mocked, so it runs where os.mkfifo does not), and a dir"""
        import stat as st
        from scripts.mech_review import stack
        self.write("rust-toolchain", "1.80.0\n")
        os.makedirs(os.path.join(self.root, "rust-toolchain.toml"))
        real = os.stat

        def fifo(path, *a, **k):
            got = real(path, *a, **k)
            if str(path).endswith(os.sep + "rust-toolchain"):
                return os.stat_result((st.S_IFIFO | 0o644,) + tuple(got)[1:])
            return got

        with mock.patch("os.stat", fifo), mock.patch("builtins.open", side_effect=AssertionError("opened a pin")):
            self.assertEqual(stack.RustAdapter().toolchain_pins(self.root, ".", "run"),
                             ["rust-toolchain.toml: (not a regular file)", "rust-toolchain: (not a regular file)"])


# `gradle --version` as Gradle 8.10 prints it
GRADLE = r'''#!/usr/bin/env python3
print("""
------------------------------------------------------------
Gradle 8.10
------------------------------------------------------------

Build time:    2024-08-14 11:07:45 UTC
Revision:      fef2edbed8af1022cefaf44d4c0514c5f89d7b78

Kotlin:        1.9.24
Groovy:        3.0.22
Ant:           Apache Ant(TM) version 1.10.14 compiled on August 16 2023
Launcher JVM:  21.0.5 (Eclipse Adoptium 21.0.5+11-LTS)
Daemon JVM:    /opt/java/openjdk (no JDK specified, using current Java home)
OS:            Linux 6.8.0 amd64
""")
'''


class Interpreter(unittest.TestCase):
    """guards (review round 2, F7; round 3, R3 and R4): what a probed script's `#!` line makes of the probe, given the
    probe's PATH."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.checkout = os.path.join(tmp.name, "checkout")
        self.out = os.path.join(tmp.name, "out")
        for d in (os.path.join(self.checkout, "bin"), self.out):
            os.makedirs(d)
        self.node = os.path.join(self.checkout, "bin", "node")
        with open(self.node, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(self.node, 0o755)
        self.path = [os.path.realpath(os.path.dirname(self.node))] + [
            d for d in os.environ["PATH"].split(os.pathsep) if d]

    def refused(self, first_line):
        from scripts.mech_review import r0_runtime
        prog = os.path.join(self.out, "tool")
        with open(prog, "w") as f:
            f.write(first_line + "\nrest\n")
        return r0_runtime._interpreter_refused(prog, (self.checkout,), self.path)

    def test_what_each_line_gives(self):
        inside = f"its interpreter `node` in the reviewed checkout: {os.path.realpath(self.node)}"

        def unread(words):
            return f"its `#!` env line is not one plain program name: `{words}`"

        for line, want in (
                ("#!/usr/bin/env node", inside), ("#! /usr/bin/env node", inside), (f"#!{self.node} -x", inside),
                ("#!/usr/bin/env node --x", inside),
                ("#!/usr/bin/env -S node --x", unread("/usr/bin/env -S node --x")),
                ("#!/usr/bin/env -Snode", unread("/usr/bin/env -Snode")),
                ("#!/usr/bin/env --split-string=node", unread("/usr/bin/env --split-string=node")),
                ("#!/usr/bin/env -S -u X node", unread("/usr/bin/env -S -u X node")),
                ("#!/usr/bin/env -S -C /tmp node", unread("/usr/bin/env -S -C /tmp node")),
                ("#!/usr/bin/env A=1 node", unread("/usr/bin/env A=1 node")),
                ("#!/usr/bin/env", unread("/usr/bin/env")),
                ("#!node", "its `#!` interpreter `node` is not an absolute path"),
                ("#!/bin/sh", None), ("#!", None), ("echo no shebang", None), ("#!/usr/bin/env sh", None),
                ("#!/usr/bin/env no-such-program-here", None)):
            with self.subTest(line=line):
                self.assertEqual(self.refused(line), want)

    def test_a_program_that_is_no_regular_file_is_not_read(self):
        """R4: stat first, so a FIFO (stat mocked) is never opened"""
        import stat as st
        from scripts.mech_review import r0_runtime
        prog = os.path.join(self.out, "tool")
        with open(prog, "w") as f:
            f.write("#!/usr/bin/env node\n")
        real = os.stat

        def fifo(path, *a, **k):
            got = real(path, *a, **k)
            return os.stat_result((st.S_IFIFO | 0o755,) + tuple(got)[1:]) if str(path) == prog else got

        with mock.patch("os.stat", fifo), mock.patch("builtins.open", side_effect=AssertionError("opened")):
            self.assertIsNone(r0_runtime._interpreter_refused(prog, (self.checkout,), self.path))
        self.assertIsNone(r0_runtime._interpreter_refused(self.out, (self.checkout,), self.path))
        self.assertIsNone(r0_runtime._interpreter_refused(os.path.join(self.out, "gone"), (self.checkout,), self.path))

    def test_only_the_first_256_bytes_are_read(self):
        """R4: one read of 256 bytes, never the whole program"""
        from scripts.mech_review import r0_runtime
        prog = os.path.join(self.out, "tool")
        with open(prog, "w") as f:
            f.write("#!/usr/bin/env node\n" + "x" * 4096)
        real, sizes = open, []

        class Capped:
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.f.close()

            def read(self, n=-1):
                sizes.append(n)
                return self.f.read(n)

        with mock.patch("builtins.open", lambda p, *a, **k: Capped(real(p, *a, **k))):
            self.assertIsNotNone(r0_runtime._interpreter_refused(prog, (self.checkout,), self.path))
        self.assertEqual(sizes, [256])

    def test_the_probe_path_keeps_only_absolute_real_entries_outside_the_checkout(self):
        from scripts.mech_review import r0_runtime
        link = os.path.join(self.out, "to-bin")
        os.symlink(os.path.dirname(self.node), link)
        other = os.path.join(self.out, "other")
        os.makedirs(other)
        other_link = os.path.join(self.out, "other-link")
        os.symlink(other, other_link)
        path = os.pathsep.join(["", ".", "rel/bin", os.path.dirname(self.node), link, other_link, other, "/usr/bin"])
        with mock.patch.dict(os.environ, {"PATH": path}):
            self.assertEqual(r0_runtime._probe_path((self.checkout,)),
                             [os.path.realpath(other), os.path.realpath("/usr/bin")])


class OrdinaryProbes(unittest.TestCase):
    """guard (review round 3): on an ordinary machine the resolved PATH changes no probe line: each reads what the
    program prints when run with this PATH"""

    def test_each_built_in_probe_reads_what_the_program_prints(self):
        from scripts.mech_review import r0_runtime
        with mock.patch.dict(os.environ):
            os.environ.pop("MECH_TEST_STUB", None)
            for argv in (["python3", "--version"], ["node", "--version"], ["cargo", "--version"]):
                with self.subTest(argv=argv):
                    if shutil.which(argv[0]) is None:
                        self.assertEqual(r0_runtime.probe(argv, False, ()), f"{argv[0]} --version: not probed (not "
                                                                            "found on PATH)")
                        continue
                    r = subprocess.run(argv, capture_output=True, text=True, cwd=tempfile.gettempdir())
                    first = next(ln.strip() for ln in (r.stdout + r.stderr).splitlines() if ln.strip())
                    self.assertEqual(r0_runtime.probe(argv, False, ()), f"{argv[0]} --version: {first}")


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
        """the JDK (Launcher JVM, the first JDK line; Daemon JVM is not kept); the version line kept is Gradle's dash
        separator, its first line (a limit the CI doc names: the Gradle version is not in the key)"""
        self.assertTrue(self.probe(GRADLE).endswith(
            " --version: " + "-" * 60 + "; Launcher JVM:  21.0.5 (Eclipse Adoptium 21.0.5+11-LTS)"))

    def test_a_tool_with_no_jdk_line_keeps_one_line(self):
        self.assertTrue(self.probe('#!/usr/bin/env python3\nprint("tool 1.0")\nprint("Kotlin: 1.9")\n').endswith(
            " --version: tool 1.0"))

    def test_the_jdk_line_comes_before_the_exit_code(self):
        self.assertTrue(self.probe('#!/usr/bin/env python3\nimport sys\nprint("tool 1.0")\nprint("JVM: 17")\n'
                                   'sys.exit(3)\n').endswith(" --version: tool 1.0; JVM: 17 (exit 3)"))


del Case  # imported for subclassing: not run again from this module


if __name__ == "__main__":
    unittest.main()
