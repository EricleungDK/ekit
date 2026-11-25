"""doctor on a repo no built-in fits (#23, ci-doctor's setup mode): it reports what it detected (the project's folder,
manifests, language, build tool, test framework and target OS, and the repo's own CI workflows) in `setup`, with one
`no-adapter` entry, so the skill starts from it. Several projects are still an ask, never a guess. Through
`cli.main(["doctor", ...])`, read-only (`--no-trial`)."""
import json
import os
import tempfile
import unittest

import _kit
from test_adapter_cli import Repo

POM = ("<project>\n  <dependencies>\n    <dependency>\n      <groupId>org.junit.jupiter</groupId>\n"
       "      <artifactId>junit-jupiter</artifactId>\n    </dependency>\n  </dependencies>\n</project>\n")
JAVA = {"pom.xml": POM, "src/main/java/com/example/Calc.java": "class Calc {}\n",
        "src/test/java/com/example/CalcTest.java": "class CalcTest {}\n"}
LINUX = "no Windows- or Apple-only project file"
CALLER = "EricleungDK/ekit/.github/workflows/"


class SetupDetection(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(os.path.join(tmp.name, "r"))

    def doctor(self, files, *flags):
        self.repo.commit(files, "c")
        return self.again(*flags)

    def again(self, *flags):
        r = _kit.run_cli(["doctor", "--repo", self.repo.path, "--no-trial", *flags])
        return r.returncode, json.loads(r.stdout)

    def entries(self, env):
        return [(e["class"], e["file"], e["problem"], e["hint"]) for e in env["entries"]]

    def test_a_maven_repo_reports_its_project_for_setup(self):
        rc, env = self.doctor(JAVA)
        self.assertEqual(rc, 1)
        self.assertEqual(env["detected"], {"stack": None, "project_dir": None})
        self.assertEqual(env["setup"], {"projects": [{
            "project_dir": ".", "manifests": ["pom.xml"], "language": "java", "build": "maven",
            "test_framework": "junit5", "target_os": "linux", "target_os_why": LINUX}], "own_ci": []})
        self.assertEqual(self.entries(env), [(
            "adapter-fix", "pom.xml", "no built-in or adapter file covers `pom.xml` (java, maven)",
            "set up its adapter with ci-doctor's setup mode, starting from `setup`")])

    def test_own_ci_lists_the_workflows_that_call_no_ekit_workflow(self):
        rc, env = self.doctor(dict(JAVA, **{
            ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: mvn -B test\n",
            ".github/workflows/mech-review.yml": f"jobs:\n  m:\n    uses: {CALLER}mech-review.yml@v0\n",
            ".github/workflows/mech-waive.yml": f"jobs:\n  w:\n    uses: {CALLER}mech-waive.yml@v0\n",
            ".github/workflows/notes.txt": "not a workflow\n"}))
        self.assertEqual(env["setup"]["own_ci"], [".github/workflows/ci.yml"])

    def test_a_wpf_app_runs_on_windows(self):
        rc, env = self.doctor({
            "App.sln": "Microsoft Visual Studio Solution File\n",
            "App/App.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\">\n  <PropertyGroup>\n"
                              "    <TargetFramework>net8.0-windows</TargetFramework>\n    <UseWPF>true</UseWPF>\n"
                              "  </PropertyGroup>\n</Project>\n",
            "App/MainWindow.xaml.cs": "class MainWindow {}\n",
            "App.Tests/App.Tests.csproj": "<Project>\n  <ItemGroup>\n    <PackageReference Include=\"xunit\" />\n"
                                          "  </ItemGroup>\n</Project>\n",
            "App.Tests/CalcTests.cs": "class CalcTests {}\n"})
        self.assertEqual(env["setup"]["projects"], [{
            "project_dir": ".", "manifests": ["App.sln"], "language": "csharp", "build": "dotnet",
            "test_framework": "xunit", "target_os": "windows",
            "target_os_why": "`App/App.csproj` sets UseWPF: a WPF app builds and runs on Windows only"}])

    def test_an_ios_app_runs_on_macos(self):
        rc, env = self.doctor({"Shop.xcodeproj/project.pbxproj": "SDKROOT = iphoneos;\n",
                               "Shop/ContentView.swift": "struct ContentView {}\n"})
        self.assertEqual(env["setup"]["projects"], [{
            "project_dir": ".", "manifests": ["Shop.xcodeproj"], "language": "swift", "build": "xcode",
            "test_framework": None, "target_os": "macos",
            "target_os_why": "`Shop.xcodeproj/project.pbxproj`: an Xcode project (an iOS or macOS app) builds on macOS "
                             "only"}])

    def test_a_swift_package_runs_on_macos_only_when_it_names_ios(self):
        ios = "// swift-tools-version:5.9\nlet package = Package(name: \"Kit\", platforms: [.iOS(.v16)])\n"
        rc, env = self.doctor({"Package.swift": ios, "Sources/Kit/Kit.swift": "struct Kit {}\n"})
        self.assertEqual(env["setup"]["projects"], [{
            "project_dir": ".", "manifests": ["Package.swift"], "language": "swift", "build": "swiftpm",
            "test_framework": None, "target_os": "macos",
            "target_os_why": "`Package.swift` names an iOS platform: an iOS app's tests run on macOS only"}])
        rc, env = self.doctor({"Package.swift": ios.replace(".iOS(.v16)", ".macOS(.v13)")})  # a second commit
        self.assertEqual([(p["build"], p["target_os"], p["target_os_why"]) for p in env["setup"]["projects"]],
                         [("swiftpm", "linux", LINUX)])

    def test_a_java_backend_and_a_ts_frontend_are_an_ask_never_a_guess(self):
        files = dict({f"backend/{k}": v for k, v in JAVA.items()},
                     **{"frontend/package.json": '{"name": "web"}\n', "frontend/src/a.ts": "export const a = 1\n"})
        rc, env = self.doctor(files)
        self.assertEqual((rc, env["detected"], env["inputs"]), (1, {"stack": None, "project_dir": None}, {}))
        self.assertEqual([p["project_dir"] for p in env["setup"]["projects"]], ["backend"])
        self.assertEqual(self.entries(env), [(
            "needs-human", "", "several projects: ts in frontend, java (maven, no adapter) in backend",
            "pick one with --project-dir, and --stack for a built-in")])

    def test_the_answer_picks_one_project(self):
        files = dict({f"backend/{k}": v for k, v in JAVA.items()},
                     **{"frontend/package.json": '{"name": "web"}\n', "frontend/src/a.ts": "export const a = 1\n"})
        rc, env = self.doctor(files, "--project-dir", "backend")
        self.assertEqual([(p["project_dir"], p["language"]) for p in env["setup"]["projects"]], [("backend", "java")])
        self.assertEqual([e["file"] for e in env["entries"]], ["backend/pom.xml"])
        rc, env = self.again("--project-dir", "frontend")
        self.assertEqual((env["detected"], env["setup"]), ({"stack": "ts", "project_dir": "frontend"}, None))

    def test_two_projects_no_built_in_covers_are_an_ask(self):
        rc, env = self.doctor(dict({f"api/{k}": v for k, v in JAVA.items()},
                                   **{"app/App.csproj": "<Project />\n"}))
        self.assertEqual([p["project_dir"] for p in env["setup"]["projects"]], ["api", "app"])
        self.assertEqual([e["problem"] for e in env["entries"]],
                         ["several projects: java (maven, no adapter) in api, csharp (dotnet, no adapter) in app"])

    def test_a_built_in_project_above_an_uncovered_one_keeps_the_adopt_flow(self):
        rc, env = self.doctor({"Cargo.toml": "[package]\nname = \"a\"\n", "src/lib.rs": "",
                               "tools/gen/pom.xml": POM})
        self.assertEqual((env["detected"], env["setup"]), ({"stack": "rust", "project_dir": "."}, None))

    def test_a_go_module_tests_with_go_test(self):
        rc, env = self.doctor({"go.mod": "module example.com/calc\n", "calc.go": "package calc\n",
                               "calc_test.go": "package calc\n"})
        self.assertEqual(env["setup"]["projects"], [{
            "project_dir": ".", "manifests": ["go.mod"], "language": "go", "build": "go", "test_framework": "testing",
            "target_os": "linux", "target_os_why": LINUX}])

    def test_a_gradle_build_names_its_language_by_its_sources(self):
        rc, env = self.doctor({"build.gradle.kts": 'dependencies { testImplementation("org.testng:testng:7.10.2") }\n',
                               "settings.gradle.kts": "", "src/main/kotlin/Calc.kt": "", "src/main/kotlin/Add.kt": "",
                               "src/main/java/Legacy.java": ""})
        self.assertEqual([(p["manifests"], p["language"], p["build"], p["test_framework"])
                          for p in env["setup"]["projects"]], [(["build.gradle.kts"], "kotlin", "gradle", "testng")])

    def test_a_groovy_gradle_build_with_junit_4(self):
        rc, env = self.doctor({"build.gradle": "dependencies { testImplementation 'junit:junit:4.13.2' }\n",
                               "src/main/java/Calc.java": ""})
        self.assertEqual([(p["manifests"], p["language"], p["build"], p["test_framework"])
                          for p in env["setup"]["projects"]], [(["build.gradle"], "java", "gradle", "junit4")])

    def test_a_manifest_the_repos_adapter_file_lists_is_no_setup_candidate(self):
        with open(os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "java.toml"), encoding="utf-8") as f:
            adapter = f.read()
        rc, env = self.doctor(dict(JAVA, **{".ekit/adapters/java.toml": adapter}))
        self.assertEqual((rc, env["detected"], env["setup"]), (1, {"stack": "java", "project_dir": "."}, None))
        self.assertEqual(self.entries(env), [(
            "adapter-fix", ".ekit/adapters/java.toml",
            "`java` in . is checked through the repo's adapter file: doctor trial-runs the built-in stacks only",
            "prove it with `r0 --stack java --project-dir .` (static half; `red --r0` runs the runtime half) and "
            "`drift`; ci-doctor's repair mode (#24) takes it from there")])

    def test_an_adapter_file_that_does_not_read_is_named(self):
        rc, env = self.doctor(dict(JAVA, **{".ekit/adapters/java.toml": "format = 1\nname = \"java\"\n"}))
        # its manifests are unknown while it does not read: the pom is a setup candidate too, named after it
        self.assertEqual([(e["file"], e["severity"]) for e in env["entries"]],
                         [(".ekit/adapters/java.toml", "fail"), ("pom.xml", "fail")])
        self.assertRegex(env["entries"][0]["problem"], r"^the repo's adapter file does not read: adapter file "
                                                       r"\.ekit/adapters/java\.toml: ")


if __name__ == "__main__":
    unittest.main()
