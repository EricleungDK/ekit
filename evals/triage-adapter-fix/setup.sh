#!/bin/bash
# fixture: two PR branches with mech-review results that hold every source of the `adapter-fix` class (#24), in a repo
# whose files match what each result reports. main holds two stacks: `calc`, the Java fixture repo
# (tests/fixtures/java/base) through the team's maven adapter and its R0 fixtures, and `app`, a Kotlin CLI in app/
# through a parser adapter (kotlin.toml: `ktfacts`, npm 0.4.1). claude/app, cut from main's first commit (its result's
# base), adds a `when` guard (Kotlin 2.1) that ktfacts 0.4.1 cannot parse (App.kt line 12) and sets the plan's
# stack[1] `app` to status `done` (mech-app.json: the two CI sources). main then took the maven adapter from the team's
# JUnit 4 template (`Ignore` in place of `Disabled` in its skip list, surefire 2's per-class summary line), so R0
# fails both halves on claude/calc, cut from that commit, which also adds `mul` (its test, and a bare `// NOPMD`: an
# agent-fixable R2 entry R0 blocks, held with no fix round until the repaired adapter) and web/package.json, a
# manifest no stack covers (mech.json: R0 static and runtime, D). claude/calc ends checked out. Each adapter-fix entry
# gets the label `adapter-fix` and the next action "no edit by the PR's agent": ci-doctor's repair mode, a person's
# waiver only as the emergency exit. tests/py/test_ci_doctor_repair_evals.py runs the kit's drift, r0 (static half)
# and r2 here and checks each entry they give against them, id and text.
# Named limits (not reproduced here): each result is one stack's envelope, though the plan holds two (no `stacks`
# list, and one stack's entry ids); the kotlin adapter has no R0 fixtures; ktfacts is not installed, so its failure is the result's text alone;
# the R0 runtime half, R1 and R4 need Maven and Gradle.
set -e
here="$(cd "$(dirname "$0")" && pwd -P)"
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n.m2/\n.cache/\nmech.json\nmech-app.json\n' >> .git/info/exclude  # sandbox HOME files and the input
cp -R "$here/../../tests/fixtures/java/base/." .
python3 -I - "$here/../../tests/fixtures/adapters" <<'PY'
import os, sys
src = sys.argv[1]
with open(os.path.join(src, "java.toml"), encoding="utf-8") as f:
    body = f.read().split("format = 1\n", 1)[1].replace('name = "java"', 'name = "maven"')
head = ("# The calc team's adapter for Maven, JUnit 5 and PIT.\n"
        "# Format: https://github.com/EricleungDK/ekit/blob/main/docs/mech-review-ci.md#adapter-file\nformat = 1\n")
os.makedirs(".ekit/adapters", exist_ok=True)
with open(".ekit/adapters/maven.toml", "w", encoding="utf-8", newline="\n") as f:
    f.write(head + body)
for root, _, names in os.walk(os.path.join(src, "java.r0")):
    for fn in names:
        rel = os.path.relpath(os.path.join(root, fn), os.path.join(src, "java.r0"))
        os.makedirs(os.path.join(".ekit/adapters/maven.r0", os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(root, fn), encoding="utf-8", newline="") as f, \
                open(os.path.join(".ekit/adapters/maven.r0", rel), "w", encoding="utf-8", newline="") as g:
            g.write(f.read())
PY
cat > .ekit/adapters/kotlin.toml <<'T'
# The app team's adapter for the Kotlin CLI in app/ (Gradle, JUnit 5): its facts come from the ktfacts parser.
# Format: https://github.com/EricleungDK/ekit/blob/main/docs/mech-review-ci.md#parser
format = 1
name = "kotlin"
manifests = ["build.gradle.kts", "settings.gradle.kts"]
extensions = [".kt"]
target-os = "linux"

[commands]
install = "gradle --no-daemon -q dependencies"
build = "gradle --no-daemon testClasses"
lint = ""
test = "gradle --no-daemon test"

[run]
test = ["--tests", "{name}"]

[run.list]
command = "gradle --no-daemon test --dry-run"
pattern = '^(?P<name>[\w$.]+ > \w+)\(\) (?:PASSED|SKIPPED)$'

[run.outcome]
summary = '^(\d+ tests completed, \d+ failed(?:, \d+ skipped)?)$'
passed = '(\d+) tests completed, 0 failed'
failed = '(\d+) failed'
skipped = '(\d+) skipped'
build = '^e: .*\.kt:\d+:\d+ '
no_test = 'No tests found for given includes'

[parser]
command = "ktfacts --format=json"
installer = "npm"
package = "ktfacts"
version = "0.4.1"
T
cat > .ekit/stack-plan.toml <<'T'
[[stack]]
name = "calc"
folder = "."
adapter = ".ekit/adapters/maven.toml"
status = "current"

[[stack]]
name = "app"
folder = "app"
adapter = ".ekit/adapters/kotlin.toml"
status = "current"
T
mkdir -p app/src/main/kotlin app/src/test/kotlin
printf 'rootProject.name = "app"\n' > app/settings.gradle.kts
cat > app/build.gradle.kts <<'K'
plugins {
    kotlin("jvm") version "2.1.0"
    application
}

repositories { mavenCentral() }

dependencies { testImplementation(kotlin("test")) }

application { mainClass.set("com.example.app.AppKt") }

tasks.test { useJUnitPlatform() }
K
cat > app/src/main/kotlin/App.kt <<'K'
package com.example.app

sealed interface Command
data object Greet : Command
data class Farewell(val name: String) : Command

fun parse(args: Array<String>): Command = if (args.isEmpty()) Greet else Farewell(args[0])

fun describe(command: Command): String =
    when (command) {
        Greet -> "Hello"
        is Farewell -> "Bye, ${command.name}"
    }

fun main(args: Array<String>) = println(describe(parse(args)))
K
cat > app/src/test/kotlin/AppTest.kt <<'K'
package com.example.app

import kotlin.test.Test
import kotlin.test.assertEquals

class AppTest {
    @Test
    fun greets() {
        assertEquals("Hello", describe(parse(arrayOf())))
    }

    @Test
    fun saysBye() {
        assertEquals("Bye, Ann", describe(parse(arrayOf("Ann"))))
    }
}
K
git add -A; git commit -qm "ci: mech-review through the maven and kotlin adapters"
app_base=$(git rev-parse HEAD)
git checkout -qb claude/app
python3 -I - <<'PY'
import re
with open("app/src/main/kotlin/App.kt", encoding="utf-8") as f:
    text = f.read()
text = text.replace('        is Farewell -> "Bye, ${command.name}"\n',
                    '        is Farewell if command.name.isBlank() -> "Bye"\n'
                    '        is Farewell -> "Bye, ${command.name}"\n')
with open("app/src/main/kotlin/App.kt", "w", encoding="utf-8", newline="\n") as f:
    f.write(text)
with open("app/src/test/kotlin/AppTest.kt", encoding="utf-8") as f:
    test = f.read()
test = test.replace("    }\n}\n", '    }\n\n    @Test\n    fun saysByeToNoName() {\n'
                                 '        assertEquals("Bye", describe(parse(arrayOf(" "))))\n    }\n}\n')
with open("app/src/test/kotlin/AppTest.kt", "w", encoding="utf-8", newline="\n") as f:
    f.write(test)
with open(".ekit/stack-plan.toml", encoding="utf-8") as f:
    plan = f.read()
with open(".ekit/stack-plan.toml", "w", encoding="utf-8", newline="\n") as f:
    f.write(re.sub(r'status = "current"\n$', 'status = "done"\n', plan))
PY
git add -A; git commit -qm "app: a bare Farewell says Bye; the app stack is done"
head=$(git rev-parse HEAD)
sed "s/HEAD_SHA/$head/g; s/BASE_SHA/$app_base/g; s/PLAN_AT/${head:0:12}/g" > mech-app.json <<'JSON'
{
 "ekit": "0.5.0",
 "base": "BASE_SHA",
 "head": "HEAD_SHA",
 "checks": {
  "R0": {
   "status": "pass",
   "note": "static half: 17 of 17 cases proved"
  },
  "R1": {
   "status": "pass",
   "note": "1 of 1 new or changed test(s) fail on the base's production code"
  },
  "R2": {
   "status": "fail",
   "note": "1 fail, 0 confirm"
  },
  "R3": {
   "status": "skipped",
   "note": "not run here"
  },
  "R4": {
   "status": "pass",
   "note": "5 of 5 runs"
  },
  "D": {
   "status": "fail",
   "note": "the stack plan does not read: .ekit/stack-plan.toml at PLAN_AT: stack[1] `app`, field status: `done`: want planned, current or retiring",
   "messages": []
  }
 },
 "entries": [
  {
   "id": "CI-599b7f05",
   "check": "CI",
   "class": "adapter-fix",
   "severity": "fail",
   "file": ".ekit/stack-plan.toml",
   "line": 0,
   "problem": "the stack plan does not read: .ekit/stack-plan.toml at PLAN_AT: stack[1] `app`, field status: `done`: want planned, current or retiring",
   "hint": "fix the named entry and field in .ekit/stack-plan.toml, in a PR that edits only the plan or its adapter files (its own plan judges it)",
   "forbidden": "deleting the plan or the entry to make the check pass"
  },
  {
   "id": "CI-f2f3b6a8",
   "check": "CI",
   "class": "adapter-fix",
   "severity": "fail",
   "file": "app/src/main/kotlin/App.kt",
   "line": 0,
   "problem": "the adapter's parser failed: parser `ktfacts` on app/src/main/kotlin/App.kt: exited with status 1: App.kt:12:21: expecting '->'",
   "hint": "fix the parser command or its pinned install step in the adapter file, in a PR of its own; R2 reads nothing of this stack until the parser runs",
   "forbidden": "falling back to patterns, or skipping R2, when the parser fails"
  }
 ],
 "summary": "fail HEAD_SHA (2 fail, 0 confirm)"
}
JSON
git checkout -q main
python3 -I - <<'PY'
with open(".ekit/adapters/maven.toml", encoding="utf-8") as f:
    text = f.read()
old = r"""summary = '^(?:\[\w+\] )?(Tests run: \d+, Failures: \d+, Errors: \d+, Skipped: \d+)\s*$'"""
new = (r"""summary = '^(?:\[\w+\] )?(Tests run: \d+, Failures: \d+, Errors: \d+, Skipped: \d+), Time elapsed: [\d.]+ """
       r"""sec(?: <<< FAILURE!)? - in [\w$.]+\s*$'""")
assert old in text and 'skip = ["Disabled",' in text
text = text.replace("# The calc team's adapter for Maven, JUnit 5 and PIT.\n",
                    "# The calc team's adapter for Maven and PIT, from the team's JUnit 4 and surefire 2 template.\n")
text = text.replace('skip = ["Disabled",', 'skip = ["Ignore",').replace(old, new)
with open(".ekit/adapters/maven.toml", "w", encoding="utf-8", newline="\n") as f:
    f.write(text)
PY
git add -A; git commit -qm "ci: the maven adapter from the team's template"
base=$(git rev-parse HEAD)
git checkout -qb claude/calc
python3 -I - <<'PY'
path = "src/main/java/com/example/Calc.java"
with open(path, encoding="utf-8") as f:
    text = f.read()
assert text.endswith("    }\n}\n")
text = text[:-2] + "\n    public static int mul(int a, int b) { // NOPMD\n        return a * b;\n    }\n}\n"
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(text)
path = "src/test/java/com/example/CalcTest.java"
with open(path, encoding="utf-8") as f:
    text = f.read()
assert text.endswith("    }\n}\n")
text = text[:-2] + "\n    @Test\n    void multiplies() {\n        assertEquals(6, Calc.mul(2, 3));\n    }\n}\n"
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(text)
PY
mkdir -p web; printf '{"name": "web"}\n' > web/package.json
git add -A; git commit -qm "calc: multiply; web: package"
sed "s/HEAD_SHA/$(git rev-parse HEAD)/g; s/BASE_SHA/$base/g" > mech.json <<'JSON'
{
 "ekit": "0.5.0",
 "base": "BASE_SHA",
 "head": "HEAD_SHA",
 "checks": {
  "R0": {
   "status": "fail",
   "note": "static half: 16 of 17 cases proved; failed: skip; runtime half (run): fingerprint d3f21f174ec3 (ran); census: 4/4 listed tests found; fixtures census: 4/4; assert density: 0 of 4 tests with no recognised assert, 0% (limit 10%); controls: 1 of 5 read right; failed: control-pass control-fail control-skipped control-no-such-test"
  },
  "R1": {
   "status": "n/a",
   "note": "blocked: R0 failed (R0 static half failed for the `maven` adapter: cheat `skip` gave no R2 fail: #[ignore] / skip / xfail / only on a test entry; R0 runtime half (run) failed for the `maven` adapter: control `pass` read error: [INFO] Scanning for projects... (want pass); control `fail` read error: [INFO] Scanning for projects... (want fail); control `skipped` read error: [INFO] Scanning for projects... (want none); control `no-such-test` read error: [INFO] Scanning for projects... (want none))",
   "before": {
    "status": "pass",
    "note": "1 of 1 new or changed test(s) fail on the base's production code (1 compile-red)"
   }
  },
  "R2": {
   "status": "n/a",
   "note": "blocked: R0 failed (R0 static half failed for the `maven` adapter: cheat `skip` gave no R2 fail: #[ignore] / skip / xfail / only on a test entry; R0 runtime half (run) failed for the `maven` adapter: control `pass` read error: [INFO] Scanning for projects... (want pass); control `fail` read error: [INFO] Scanning for projects... (want fail); control `skipped` read error: [INFO] Scanning for projects... (want none); control `no-such-test` read error: [INFO] Scanning for projects... (want none))",
   "before": {
    "status": "fail",
    "note": "1 fail, 0 confirm"
   }
  },
  "R3": {
   "status": "skipped",
   "note": "not run here"
  },
  "R4": {
   "status": "n/a",
   "note": "blocked: R0 failed (R0 static half failed for the `maven` adapter: cheat `skip` gave no R2 fail: #[ignore] / skip / xfail / only on a test entry; R0 runtime half (run) failed for the `maven` adapter: control `pass` read error: [INFO] Scanning for projects... (want pass); control `fail` read error: [INFO] Scanning for projects... (want fail); control `skipped` read error: [INFO] Scanning for projects... (want none); control `no-such-test` read error: [INFO] Scanning for projects... (want none))",
   "before": {
    "status": "pass",
    "note": "5 of 5 runs"
   }
  },
  "D": {
   "status": "fail",
   "note": "judged by the base branch's plan",
   "messages": []
  }
 },
 "entries": [
  {
   "id": "R0-00e0bfc4",
   "check": "R0",
   "class": "adapter-fix",
   "severity": "fail",
   "file": ".ekit/adapters/maven.toml",
   "line": 0,
   "problem": "R0 runtime half (run) failed for the `maven` adapter: control `pass` read error: [INFO] Scanning for projects... (want pass); control `fail` read error: [INFO] Scanning for projects... (want fail); control `skipped` read error: [INFO] Scanning for projects... (want none); control `no-such-test` read error: [INFO] Scanning for projects... (want none)",
   "hint": "repair the adapter (ci-doctor repair mode) in a PR of its own, then re-run R0; the PR under review never edits its own checker",
   "forbidden": "tuning the adapter or its fixtures until this PR passes"
  },
  {
   "id": "R0-6d261a04",
   "check": "R0",
   "class": "adapter-fix",
   "severity": "fail",
   "file": ".ekit/adapters/maven.toml",
   "line": 0,
   "problem": "R0 static half failed for the `maven` adapter: cheat `skip` gave no R2 fail: #[ignore] / skip / xfail / only on a test entry",
   "hint": "repair the adapter (ci-doctor repair mode) in a PR of its own, then re-run R0; the PR under review never edits its own checker",
   "forbidden": "tuning the adapter or its fixtures until this PR passes"
  },
  {
   "id": "D-7e776699",
   "check": "D",
   "class": "adapter-fix",
   "severity": "fail",
   "file": ".ekit/stack-plan.toml",
   "line": 0,
   "problem": "manifests no stack in .ekit/stack-plan.toml covers: web/package.json",
   "hint": "add a [[stack]] entry for each (its folder, an adapter that lists the manifest), or its folder to `ignore`, in a PR of its own that adds no manifest (`/ekit:ci-doctor` writes it); a person may waive this entry",
   "forbidden": "a plan entry added in this PR (a PR that adds a manifest is judged by the base branch's plan); moving or renaming the manifest so the check does not see it"
  },
  {
   "id": "R2-0734ae9c",
   "check": "R2",
   "class": "agent-fixable",
   "severity": "fail",
   "file": "src/main/java/com/example/Calc.java",
   "line": 19,
   "problem": "`NOPMD` added without a reason",
   "hint": "fix the PMD finding, or give the suppression a reason after it: `// NOPMD - why`",
   "forbidden": "silencing a lint without a reason",
   "blocked": "R0"
  }
 ],
 "summary": "fail HEAD_SHA (4 fail, 0 confirm)"
}
JSON
