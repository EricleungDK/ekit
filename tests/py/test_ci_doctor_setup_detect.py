"""doctor on a repo no built-in fits (#23, ci-doctor's setup mode): it reports what it detected (the project's folder,
manifests, language, build tool, test framework and target OS, and the repo's own CI workflows) in `setup`, with one
`no-adapter` entry, so the skill starts from it. Several projects are still an ask, never a guess. Through
`cli.main(["doctor", ...])`, read-only (`--no-trial`)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import _kit
from test_adapter_cli import Repo

POM = ("<project>\n  <dependencies>\n    <dependency>\n      <groupId>org.junit.jupiter</groupId>\n"
       "      <artifactId>junit-jupiter</artifactId>\n    </dependency>\n  </dependencies>\n</project>\n")
JAVA = {"pom.xml": POM, "src/main/java/com/example/Calc.java": "class Calc {}\n",
        "src/test/java/com/example/CalcTest.java": "class CalcTest {}\n"}
LINUX = "no Windows- or Apple-only project file"
CALLER = "EricleungDK/ekit/.github/workflows/"
WPF = ("`{}` is a WPF app (UseWPF, the WPF project type or a PresentationFramework reference): it builds and runs on "
       "Windows only")
ASK = "pick one with --project-dir, --stack (a built-in, or the build of a project with no adapter) or both"
PUSH_TEST = ("on: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-24.04\n    steps:\n"
             "      - run: mvn -B test\n")


class SetupDetection(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(os.path.join(tmp.name, "r"))

    def doctor(self, files, *flags):
        self.repo.commit(files, "c")
        return self.again(*flags)

    def java_adapter(self):
        with open(os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "java.toml"), encoding="utf-8") as f:
            return f.read()

    def again(self, *flags):
        r = _kit.run_cli(["doctor", "--repo", self.repo.path, "--no-trial", *flags])
        return r.returncode, json.loads(r.stdout)

    def entries(self, env):
        return [(e["class"], e["severity"], e["file"], e["problem"], e["hint"]) for e in env["entries"]]

    def test_a_maven_repo_reports_its_project_for_setup(self):
        rc, env = self.doctor(JAVA)
        self.assertEqual(rc, 1)
        self.assertEqual((env["detected"], env["mode"]), ({"stack": None, "project_dir": None}, "setup"))
        self.assertEqual(env["setup"], {"projects": [{
            "project_dir": ".", "manifests": ["pom.xml"], "language": "java", "build": "maven",
            "test_framework": "junit5", "target_os": "linux", "target_os_why": LINUX}], "own_ci": []})
        self.assertEqual(self.entries(env), [(
            "adapter-fix", "fail", "pom.xml", "no built-in or adapter file covers `pom.xml` (java, maven)",
            "set up its adapter with ci-doctor's setup mode, starting from `setup`")])

    def test_own_ci_counts_workflows_with_a_build_or_test_job_on_push_or_pull_request(self):
        rc, env = self.doctor(dict(JAVA, **{
            ".github/workflows/ci.yml": PUSH_TEST.replace("jobs:", f"jobs:\n  m:\n    uses: {CALLER}mech-review.yml@v0"),
            ".github/workflows/release.yml": "on:\n  release:\n    types: [published]\njobs:\n  r:\n    steps: []\n",
            ".github/workflows/tags.yml": "on:\n  push:\n    tags: ['v*']\njobs:\n  r:\n    steps: []\n",
            ".github/workflows/only-ekit.yml": f"on: pull_request\njobs:\n  m:\n    uses: {CALLER}mech-review.yml@v0\n",
            ".github/workflows/nightly.yaml": "'on':\n  schedule:\n    - cron: '0 3 * * *'\njobs:\n  t:\n    steps: []\n",
            ".github/workflows/pr.yaml": "\"on\":\n  pull_request:\n  # a comment\n\njobs:\n  build:  # the build\n"
                                        "    steps: []\n",
            ".github/workflows/branches.yml": "on:\n  push:\n    branches: [main]\n    tags: ['v*']\njobs:\n  t:\n"
                                              "    steps: []\n",
            ".github/workflows/merge.yml": "on: merge_group\njobs:\n  t:\n    steps: []\n",
            ".github/workflows/scalar.yml": "on: push # every push\njobs:\n  t:\n    steps: []\n"}))
        self.assertEqual(env["setup"]["own_ci"], [".github/workflows/branches.yml", ".github/workflows/ci.yml",
                                                  ".github/workflows/merge.yml", ".github/workflows/pr.yaml",
                                                  ".github/workflows/scalar.yml"])

    def test_own_ci_lists_the_workflows_that_call_no_ekit_workflow(self):
        rc, env = self.doctor(dict(JAVA, **{
            ".github/workflows/ci.yml": PUSH_TEST,
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
            "target_os_why": WPF.format("App/App.csproj")}])

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
        self.assertEqual((rc, env["detected"], env["inputs"], env["mode"]),
                         (1, {"stack": None, "project_dir": None}, {}, "ask"))
        self.assertEqual([p["project_dir"] for p in env["setup"]["projects"]], ["backend"])
        self.assertEqual(self.entries(env), [(
            "needs-human", "fail", "", "several projects: ts in frontend, java (maven, no adapter) in backend",
            ASK)])

    def test_the_answer_picks_one_project(self):
        files = dict({f"backend/{k}": v for k, v in JAVA.items()},
                     **{"frontend/package.json": '{"name": "web"}\n', "frontend/src/a.ts": "export const a = 1\n"})
        rc, env = self.doctor(files, "--project-dir", "backend")
        self.assertEqual([(p["project_dir"], p["language"]) for p in env["setup"]["projects"]], [("backend", "java")])
        self.assertEqual([e["file"] for e in env["entries"]], ["backend/pom.xml"])
        rc, env = self.again("--project-dir", "frontend")
        self.assertEqual((env["detected"], env["setup"], env["mode"]),
                         ({"stack": "ts", "project_dir": "frontend"}, None, "adopt"))

    def test_two_projects_no_built_in_covers_are_an_ask(self):
        rc, env = self.doctor(dict({f"api/{k}": v for k, v in JAVA.items()},
                                   **{"app/App.csproj": "<Project />\n"}))
        self.assertEqual(env["setup"]["projects"], [
            {"project_dir": "api", "manifests": ["pom.xml"], "language": "java", "build": "maven",
             "test_framework": "junit5", "target_os": "linux", "target_os_why": LINUX},
            {"project_dir": "app", "manifests": ["App.csproj"], "language": "csharp", "build": "dotnet",
             "test_framework": None, "target_os": "linux", "target_os_why": LINUX}])
        self.assertEqual([e["problem"] for e in env["entries"]],
                         ["several projects: java (maven, no adapter) in api, csharp (dotnet, no adapter) in app"])

    def test_the_shallowest_project_wins_across_built_in_and_uncovered_manifests(self):
        cases = (  # files, (detected stack, mode, setup projects): the deeper project is tooling, whichever way round
            ({"Cargo.toml": "[package]\nname = \"a\"\n", "src/lib.rs": "", "tools/gen/pom.xml": POM},
             ("rust", "adopt", None)),
            (dict(JAVA, **{"web/package.json": '{"name": "web"}\n', "web/src/a.ts": ""}), (None, "setup", ["."])),
            ({"package.json": '{"name": "app"}\n', "android/build.gradle": "", "android/settings.gradle": "",
              "ios/App.xcodeproj/project.pbxproj": ""}, ("ts", "adopt", None)),
            ({"package.json": '{"name": "app"}\n', "tools/x/pyproject.toml": "[project]\n"}, ("ts", "adopt", None)))
        for n, (files, (stack, mode, folders)) in enumerate(cases):
            with self.subTest(case=n):
                repo = Repo(os.path.join(self.repo.path + "-" + str(n), "r"))
                repo.commit(files, "c")
                env = json.loads(_kit.run_cli(["doctor", "--repo", repo.path, "--no-trial"]).stdout)
                self.assertEqual((env["detected"]["stack"], env["mode"],
                                  [p["project_dir"] for p in env["setup"]["projects"]] if env["setup"] else None),
                                 (stack, mode, folders))

    def test_an_uncovered_project_beside_the_repos_found_adapter_is_set_up_once_picked(self):
        rc, env = self.doctor({"backend/pom.xml": POM, ".ekit/adapters/java.toml": self.java_adapter(),
                               "svc/go.mod": "module svc\n"})
        self.assertEqual((env["mode"], [e["problem"] for e in env["entries"]]),
                         ("ask", ["several projects: java in backend, go (go, no adapter) in svc"]))
        rc, env = self.again("--stack", "go", "--project-dir", "svc")
        self.assertEqual((env["mode"], [e["file"] for e in env["entries"]]), ("setup", ["svc/go.mod"]))
        rc, env = self.again("--project-dir", "svc")
        self.assertEqual(env["mode"], "setup")

    def test_an_orphaned_adapter_file_keeps_an_answered_pick_in_setup(self):
        orphan = self.java_adapter().replace('manifests = ["pom.xml"]', 'manifests = []')
        rc, env = self.doctor(dict(JAVA, **{".ekit/adapters/java.toml": orphan}), "--project-dir", ".")
        self.assertEqual(env["mode"], "setup")

    def test_the_plans_ignore_folders_hold_no_project(self):
        rc, env = self.doctor({"app/package.json": '{"name": "app"}\n', "tools/go.mod": "module tools\n",
                               ".ekit/stack-plan.toml": 'ignore = ["tools"]\n\n[[stack]]\nname = "app"\n'
                                                        'folder = "app"\nadapter = "ts"\nstatus = "current"\n'})
        self.assertEqual((env["detected"], env["mode"], env["setup"]), ({"stack": "ts", "project_dir": "app"},
                                                                       "adopt", None))

    def test_two_built_in_projects_are_an_ask_too(self):
        rc, env = self.doctor({"a/Cargo.toml": "[package]\nname = \"a\"\n", "b/pyproject.toml": "[project]\n"})
        self.assertEqual((env["mode"], [e["problem"] for e in env["entries"]]),
                         ("ask", ["several projects: python in b, rust in a"]))

    def test_a_built_in_stack_and_a_folder_with_no_manifest_adopt_as_told(self):
        rc, env = self.doctor(JAVA, "--stack", "rust", "--project-dir", "crates/x")
        self.assertEqual((env["detected"], env["mode"], env["setup"]),
                         ({"stack": "rust", "project_dir": "crates/x"}, "adopt", None))

    def test_own_ci_fails_closed_on_a_trigger_it_cannot_read(self):
        job = "jobs:\n  t:\n    steps: []\n"
        rc, env = self.doctor(dict(JAVA, **{
            ".github/workflows/list.yml": "on:\n  - push\n  - pull_request\n" + job,
            ".github/workflows/quoted.yml": "on: [\"pull_request\"]\n" + job,
            ".github/workflows/flow.yml": "on: {push: {branches: [main]}}\n" + job,
            ".github/workflows/none.yml": job,
            ".github/workflows/list-release.yml": "on:\n  - release\n" + job,
            ".github/workflows/scalar-release.yml": "on: 'release'\n" + job}))
        self.assertEqual(env["setup"]["own_ci"], [".github/workflows/flow.yml", ".github/workflows/list.yml",
                                                  ".github/workflows/none.yml", ".github/workflows/quoted.yml"])

    def test_own_ci_reads_flow_jobs_tag_filters_and_pull_request_target(self):
        rc, env = self.doctor(dict(JAVA, **{
            ".github/workflows/flow-jobs.yml": "on: push\njobs: {test: {runs-on: x, steps: [{run: mvn test}]}}\n",
            ".github/workflows/empty-jobs.yml": "on: push\njobs: {}\n",
            ".github/workflows/tags-ignore.yml": "on:\n  push:\n    tags-ignore: ['v*']\njobs:\n  t:\n    steps: []\n",
            ".github/workflows/target.yml": "on: pull_request_target\njobs:\n  t:\n    steps: []\n"}))
        self.assertEqual(env["setup"]["own_ci"], [".github/workflows/flow-jobs.yml", ".github/workflows/target.yml"])

    def test_a_plan_entry_naming_an_adapter_file_missing_or_unread_is_repair(self):
        for adapter, why in (("ci/none.toml", "missing"), ("ci/bad.toml", "unread")):
            with self.subTest(why=why):
                repo = Repo(os.path.join(self.repo.path + "-" + why, "r"))
                repo.commit(dict(JAVA, **{"ci/bad.toml": "format = 1\n", ".ekit/stack-plan.toml":
                                          f'[[stack]]\nname = "api"\nfolder = "."\nadapter = "{adapter}"\n'
                                          'status = "current"\n'}), "c")
                env = json.loads(_kit.run_cli(["doctor", "--repo", repo.path, "--no-trial"]).stdout)
                self.assertEqual(env["mode"], "repair")
                self.assertIn((".ekit/stack-plan.toml", "fail"), [(e["file"], e["severity"]) for e in env["entries"]])

    def test_an_adapter_file_the_plan_names_outside_ekit_adapters_is_the_repos_own(self):
        adapter = self.java_adapter().replace('manifests = ["pom.xml"]', 'manifests = ["calc.json"]')
        rc, env = self.doctor(dict(JAVA, **{"ci/calc.toml": adapter, ".ekit/adapters/java.toml": adapter,
                                            ".ekit/stack-plan.toml":
                                            '[[stack]]\nname = "a"\nfolder = "."\nadapter = "ci/calc.toml"\n'
                                            'status = "planned"\n[[stack]]\nname = "b"\nfolder = "lib"\n'
                                            'adapter = ".ekit/adapters/java.toml"\nstatus = "planned"\n'}))
        self.assertEqual((env["mode"], [e["problem"] for e in env["entries"]]), ("repair", [
            "no adapter lists `pom.xml` (java, maven), and the repo's own adapter files `.ekit/adapters/java.toml`, "
            "`ci/calc.toml` find no project: one may be meant for it"]))

    def test_two_projects_in_one_folder_are_an_ask_that_stack_answers(self):
        cases = (
            ({"package.json": '{"name": "web"}\n', "src/a.ts": ""}, "ts in ., java (maven, no adapter) in .", "maven"),
            ({"build.gradle": ""}, "java (gradle, no adapter) in ., java (maven, no adapter) in .", "gradle"))
        for extra, names, build in cases:
            with self.subTest(names=names):
                repo = Repo(os.path.join(self.repo.path + "-" + build, "r"))
                repo.commit(dict(JAVA, **extra), "c")
                env = json.loads(_kit.run_cli(["doctor", "--repo", repo.path, "--no-trial"]).stdout)
                self.assertEqual([(e["problem"], e["hint"]) for e in env["entries"]], [(f"several projects: {names}", ASK)])
                r = _kit.run_cli(["doctor", "--repo", repo.path, "--no-trial", "--stack", build, "--project-dir", "."])
                env = json.loads(r.stdout)
                self.assertEqual(([p["build"] for p in env["setup"]["projects"]], [e["file"] for e in env["entries"]]),
                                 ([build], [{"maven": "pom.xml", "gradle": "build.gradle"}[build]]))
        rc, env = self.doctor({"Package.swift": "let package = Package(name: \"Kit\")\n",
                               "Kit.xcodeproj/project.pbxproj": ""})
        self.assertEqual([e["problem"] for e in env["entries"]],
                         ["several projects: swift (swiftpm, no adapter) in ., swift (xcode, no adapter) in ."])
        rc, env = self.again("--stack", "xcode")
        self.assertEqual([(p["build"], p["target_os"]) for p in env["setup"]["projects"]], [("xcode", "macos")])

    def test_a_build_named_with_stack_and_none_there_is_no_match(self):
        rc, env = self.doctor(JAVA, "--stack", "gradle")
        self.assertEqual([(e["class"], e["problem"]) for e in env["entries"]],
                         [("needs-human", "no project found for gradle")])
        rc, env = self.again("--stack", "gradle", "--project-dir", ".")
        self.assertEqual((env["setup"], [e["problem"] for e in env["entries"]]),
                         (None, ["no project found for gradle in ."]))

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
                          for p in env["setup"]["projects"]],
                         [(["build.gradle.kts", "settings.gradle.kts"], "kotlin", "gradle", "testng")])

    def test_a_groovy_gradle_build_with_junit_4(self):
        rc, env = self.doctor({"build.gradle": "dependencies { testImplementation 'junit:junit:4.13.2' }\n",
                               "src/main/java/Calc.java": ""})
        self.assertEqual([(p["manifests"], p["language"], p["build"], p["test_framework"])
                          for p in env["setup"]["projects"]], [(["build.gradle"], "java", "gradle", "junit4")])

    def test_language_and_framework_come_from_the_projects_own_files(self):
        self.repo.commit({
            "fs/App.sln": "", "fs/src/A.fs": "", "fs/src/B.fs": "", "fs/src/C.cs": "",
            "fs/tests/App.Tests/App.Tests.csproj": "<PackageReference Include=\"NUnit\" />\n",
            "ms/App.csproj": "<PackageReference Include=\"MSTest.TestFramework\" />\n", "ms/A.cs": "",
            "objc/Old.xcodeproj/project.pbxproj": "SDKROOT = macosx;\n", "objc/Old/main.m": "", "objc/Old/App.m": "",
            "objc/Old/View.swift": ""}, "c")
        got = {d: [(p["language"], p["build"], p["test_framework"], p["target_os"]) for p in
                   self.again("--project-dir", d)[1]["setup"]["projects"]] for d in ("fs", "ms", "objc")}
        self.assertEqual(got, {"fs": [("fsharp", "dotnet", "nunit", "linux")],  # a test project under tests/ counts
                               "ms": [("csharp", "dotnet", "mstest", "linux")],
                               "objc": [("objective-c", "xcode", None, "macos")]})

    def test_only_the_shallowest_uncovered_projects_count(self):
        rc, env = self.doctor(dict(JAVA, **{"tools/go.mod": "module tools\n", "tools/gen/go.mod": "module gen\n"}))
        self.assertEqual([(p["project_dir"], p["build"]) for p in env["setup"]["projects"]], [(".", "maven")])

    def test_fixture_and_vendored_folders_hold_no_project_and_no_evidence(self):
        rc, env = self.doctor({"tests/fixtures/app/pom.xml": POM, "vendor/lib/go.mod": "module lib\n"})
        self.assertEqual((env["setup"], env["mode"], [e["problem"] for e in env["entries"]]),
                         (None, None, ["no project found: no pyproject.toml, setup.py, setup.cfg, Cargo.toml, "
                                       "package.json"]))
        rc, env = self.doctor({"App.sln": "", "App/App.csproj": "<Project />\n",
                               "examples/Demo/Demo.csproj": "<UseWPF>true</UseWPF> <Package Include=\"xunit\" />"})
        self.assertEqual([(p["test_framework"], p["target_os"]) for p in env["setup"]["projects"]], [(None, "linux")])

    def test_an_adapter_file_named_like_a_built_in_keeps_the_adopt_flow(self):
        with open(os.path.join(_kit.SCRIPTS, "mech_review", "adapters", "ts.toml"), encoding="utf-8") as f:
            adapter = f.read()
        rc, env = self.doctor({"package.json": '{"name": "web"}\n', "src/a.ts": "export const a = 1\n",
                               ".ekit/adapters/ts.toml": adapter})
        self.assertEqual((env["detected"], env["setup"]), ({"stack": "ts", "project_dir": "."}, None))
        self.assertFalse([e for e in env["entries"] if "adapter file" in e["problem"]])

    def test_junit_platform_is_junit_5(self):
        cases = {"gradle": {"build.gradle.kts": "dependencies { testImplementation(libs.junit.jupiter) }\n"
                                                "tasks.test { useJUnitPlatform() }\n// junit:junit was dropped\n"},
                 "catalog": {"build.gradle.kts": "dependencies { testImplementation(libs.junit.jupiter) }\n"},
                 "kotlin-test": {"build.gradle.kts": 'dependencies { testImplementation(kotlin("test")) }\n'
                                                     "tasks.test { useJUnitPlatform() }\n"},
                 "spring": {"pom.xml": "<project><artifactId>spring-boot-starter-test</artifactId></project>\n"},
                 "platform": {"build.gradle": "test { useJUnitPlatform() }\n"}}
        for name, files in cases.items():
            with self.subTest(name=name):
                repo = Repo(os.path.join(self.repo.path + "-" + name, "r"))
                repo.commit(files, "c")
                env = json.loads(_kit.run_cli(["doctor", "--repo", repo.path, "--no-trial"]).stdout)
                self.assertEqual([p["test_framework"] for p in env["setup"]["projects"]], ["junit5"])

    def test_every_wpf_signal_reads_windows(self):
        guid = "<ProjectTypeGuids>{60DC8134-EBA5-43B8-BCC9-BB4BC16C2548};{FAE04EC0}</ProjectTypeGuids>"
        cases = {"classic-guid": {"App/App.csproj": f"<Project>{guid}</Project>"},
                 "presentation": {"App/App.csproj": '<Project><Reference Include="PresentationFramework" /></Project>'},
                 "props": {"Directory.Build.props": "<Project><PropertyGroup><UseWPF> True </UseWPF></PropertyGroup>"
                                                    "</Project>", "App/App.csproj": "<Project />"},
                 "utf16": {"App/App.csproj": None}, "utf16be": {"App/App.csproj": None}}
        for name, files in cases.items():
            with self.subTest(name=name):
                repo = Repo(os.path.join(self.repo.path + "-" + name, "r"))
                files = dict({"App.sln": ""}, **files)
                if name.startswith("utf16"):
                    os.makedirs(os.path.join(repo.path, "App"))
                    with open(os.path.join(repo.path, "App", "App.csproj"), "wb") as f:
                        text = "\ufeff<Project><UseWPF>true</UseWPF></Project>"
                        f.write(text.encode("utf-16-le" if name == "utf16" else "utf-16-be"))
                    del files["App/App.csproj"]
                repo.commit(files, "c")
                env = json.loads(_kit.run_cli(["doctor", "--repo", repo.path, "--no-trial"]).stdout)
                file = "Directory.Build.props" if name == "props" else "App/App.csproj"
                self.assertEqual([(p["target_os"], p["target_os_why"]) for p in env["setup"]["projects"]],
                                 [("windows", WPF.format(file))])

    def test_a_wpf_or_ios_word_in_a_comment_or_another_name_is_not_one(self):
        rc, env = self.doctor({"App.csproj": "<Project><!-- <UseWPF>true</UseWPF> --></Project>"})
        self.assertEqual([p["target_os"] for p in env["setup"]["projects"]], ["linux"])
        rc, env = self.doctor({"App.csproj": "<Project />", "Package.swift": "", "go.mod": ""}, "--stack", "swiftpm")
        for text in ("// platforms: [.iOS(.v15)]\nlet p = 1\n", "/* .iOS(.v15) */\n",
                     "let ext = Product.Kind.iOSApplicationExtension\n", "let p = Package(platforms: [.macOS(.v13)])\n"):
            with self.subTest(text=text):
                self.repo.commit({"Package.swift": text}, "c")
                env = self.again("--stack", "swiftpm")[1]
                self.assertEqual([p["target_os"] for p in env["setup"]["projects"]], ["linux"])

    def test_a_comment_marker_inside_a_string_is_no_comment(self):
        gradle = ('tasks.test { include("**/*Test.class") }\n'
                  'dependencies { testImplementation("org.junit.jupiter:junit-jupiter:5.10.0") }\n'
                  "tasks.test { exclude('**/*IT.class') } // a */ in a comment\n")
        rc, env = self.doctor({"build.gradle.kts": gradle})
        self.assertEqual([p["test_framework"] for p in env["setup"]["projects"]], ["junit5"])
        swift = ('let package = Package(name: "Kit", resources: [.copy("Assets/*")],\n'
                 '    platforms: [.iOS(.v16)], path: "a*/b", url: "https://example.com/kit")\n'
                 'let doc = """\n  /* not a comment */ "quoted" \n  """\n')
        rc, env = self.doctor({"Package.swift": swift}, "--stack", "swiftpm")
        self.assertEqual([p["target_os"] for p in env["setup"]["projects"]], ["macos"])

    def test_every_manifest_of_one_build_in_a_folder_is_one_project(self):
        adapter = self.java_adapter().replace('name = "java"', 'name = "kgradle"').replace(
            'manifests = ["pom.xml"]', 'manifests = ["build.gradle.kts"]')
        rc, env = self.doctor({"build.gradle.kts": "", "settings.gradle.kts": "", ".ekit/adapters/kgradle.toml": adapter})
        self.assertEqual((env["detected"], env["setup"], env["mode"]),
                         ({"stack": "kgradle", "project_dir": "."}, None, "repair"))

    def test_settings_gradle_is_the_build_root(self):
        rc, env = self.doctor({"settings.gradle.kts": 'include("app")\n', "app/build.gradle.kts": "",
                               "buildSrc/build.gradle.kts": "", "app/src/main/kotlin/A.kt": ""})
        self.assertEqual([(p["project_dir"], p["manifests"], p["language"]) for p in env["setup"]["projects"]],
                         [(".", ["settings.gradle.kts"], "kotlin")])
        self.assertEqual([e["file"] for e in env["entries"]], ["settings.gradle.kts"])

    def test_a_plan_entry_naming_an_adapter_file_outside_ekit_adapters_is_the_repos_adapter(self):
        with open(os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "java.toml"), encoding="utf-8") as f:
            adapter = f.read()
        rc, env = self.doctor(dict(JAVA, **{"ci/java.toml": adapter, ".ekit/stack-plan.toml":
                                            '[[stack]]\nname = "api"\nfolder = "."\nadapter = "ci/java.toml"\n'
                                            'status = "current"\n'}))
        self.assertEqual((env["detected"], env["setup"], env["mode"]),
                         ({"stack": "java", "project_dir": "."}, None, "repair"))
        self.assertEqual([(e["file"], e["severity"]) for e in env["entries"]], [("ci/java.toml", "confirm")])

    def test_a_stack_plan_that_does_not_read_is_named(self):
        rc, env = self.doctor(dict(JAVA, **{".ekit/stack-plan.toml": "[[stack]]\nname = 1\n"}))
        self.assertEqual([(e["class"], e["severity"], e["file"]) for e in env["entries"]][0],
                         ("adapter-fix", "fail", ".ekit/stack-plan.toml"))
        self.assertRegex(env["entries"][0]["problem"], r"^the stack plan does not read: \.ekit/stack-plan\.toml at ")
        self.assertEqual(env["mode"], "repair")

    def test_an_existing_adapter_file_that_lists_no_manifest_routes_to_repair_not_setup(self):
        rc, env = self.doctor(dict(JAVA, **{".ekit/adapters/java.toml": self.java_adapter().replace(
            'manifests = ["pom.xml"]', "manifests = []")}))
        self.assertEqual([(e["class"], e["severity"], e["file"], e["problem"]) for e in env["entries"]], [(
            "adapter-fix", "fail", "pom.xml",
            "no adapter lists `pom.xml` (java, maven), and the repo's own adapter files "
            "`.ekit/adapters/java.toml` find no project: one may be meant for it")])
        self.assertEqual(env["entries"][0]["hint"], "repair or extend that adapter file (ci-doctor's repair mode, #24) "
                                                    "rather than set up a second one; the owner decides")
        self.assertEqual(env["mode"], "repair")

    def test_an_xcode_adapter_listing_project_pbxproj_is_no_second_project(self):
        adapter = self.java_adapter().replace('name = "java"', 'name = "xcode"').replace(
            'manifests = ["pom.xml"]', 'manifests = ["project.pbxproj"]').replace('extensions = [".java"]',
                                                                              'extensions = [".swift"]')
        rc, env = self.doctor({"Shop.xcodeproj/project.pbxproj": "", ".ekit/adapters/xcode.toml": adapter})
        self.assertEqual((env["setup"], [e["file"] for e in env["entries"]]), (None, [".ekit/adapters/xcode.toml"]))

    def test_doctor_reads_a_built_in_named_adapter_file_as_resolve_does(self):
        override = open(os.path.join(_kit.SCRIPTS, "mech_review", "adapters", "ts.toml"), encoding="utf-8").read()
        override = override.replace('manifests = ["package.json"]', 'manifests = ["deno.json"]')
        self.assertIn('manifests = ["deno.json"]', override)
        rc, env = self.doctor({"deno.json": "{}\n", "src/a.ts": "", ".ekit/adapters/ts.toml": override})
        got = json.loads(_kit.run_cli(["resolve", "--repo", self.repo.path, "--base", "HEAD", "--head", "HEAD"]).stdout)
        self.assertEqual((got["stack"], got["project_dir"]), ("ts", "."))
        self.assertEqual(env["detected"], {"stack": "ts", "project_dir": "."})
        self.repo.commit({".ekit/adapters/ts.toml": "format = 1\n"}, "broken")
        got = json.loads(_kit.run_cli(["resolve", "--repo", self.repo.path, "--base", "HEAD", "--head", "HEAD"]).stdout)
        self.assertIn(".ekit/adapters/ts.toml", got["error"])
        rc, env = self.again()
        self.assertIn((".ekit/adapters/ts.toml", "fail"), [(e["file"], e["severity"]) for e in env["entries"]])
        self.assertEqual(env["mode"], "repair")

    def test_with_no_toml_reader_doctor_names_this_machine_and_routes_nothing(self):
        self.repo.commit(dict(JAVA, **{".ekit/adapters/java.toml": self.java_adapter()}), "c")
        with mock.patch.dict(sys.modules, {"tomllib": None}):
            rc, env = self.again()
        self.assertEqual((env["detected"], env["setup"], env["mode"]),
                         ({"stack": None, "project_dir": None}, None, None))
        self.assertEqual([(e["class"], e["severity"], e["file"], e["problem"], e["hint"]) for e in env["entries"]], [(
            "env", "fail", "", "this python cannot read the repo's adapter files and stack plan (tomllib, python 3.11 "
            "or newer): doctor cannot tell which manifests they cover", "rerun doctor with python 3.11 or newer")])

    def test_a_manifest_the_repos_adapter_file_lists_is_no_setup_candidate(self):
        with open(os.path.join(_kit.ROOT, "tests", "fixtures", "adapters", "java.toml"), encoding="utf-8") as f:
            adapter = f.read()
        rc, env = self.doctor(dict(JAVA, **{".ekit/adapters/java.toml": adapter}))
        self.assertEqual((rc, env["detected"], env["setup"]), (1, {"stack": "java", "project_dir": "."}, None))
        self.assertEqual(self.entries(env), [(
            "adapter-fix", "confirm", ".ekit/adapters/java.toml",
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
        self.assertEqual(env["entries"][0]["hint"], "repair it (ci-doctor's repair mode, #24), then rerun doctor")


if __name__ == "__main__":
    unittest.main()
