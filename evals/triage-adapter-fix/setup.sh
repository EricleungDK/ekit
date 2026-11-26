#!/bin/bash
# fixture: two PR branches with mech-review results that hold every source of the `adapter-fix` class (#24): on
# claude/calc (mech.json) R0's static and runtime halves (the maven adapter), the drift block D (a manifest no stack
# covers) and, beside them, an agent-fixable R2 entry R0 blocks (held: no fix round until the repaired adapter); on claude/app (mech-app.json) the two CI sources: the
# adapter's parser failed, and the stack plan does not read. Each adapter-fix entry gets its own label, `adapter-fix`,
# and the next action "no edit by the PR's agent": ci-doctor's repair mode, a person's waiver only as the emergency exit.
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\nmech.json\nmech-app.json\n' >> .git/info/exclude  # sandbox HOME files and the input
mkdir -p src/main/java/com/example .ekit/adapters app/src/main/kotlin
printf '<project/>\n' > pom.xml
printf 'package com.example;\n\npublic final class Calc {\n    public static int add(int a, int b) {\n        return a + b;\n    }\n}\n' > src/main/java/com/example/Calc.java
printf 'format = 1\nname = "maven"\n' > .ekit/adapters/maven.toml
printf '[[stack]]\nname = "calc"\nfolder = "."\nadapter = ".ekit/adapters/maven.toml"\nstatus = "current"\n' > .ekit/stack-plan.toml
git add -A; git commit -qm base
base=$(git rev-parse HEAD)
git checkout -qb claude/app
printf 'fun main() = println("app")\n' > app/src/main/kotlin/App.kt
git add -A; git commit -qm "app: kotlin entry point"
sed "s/HEAD_SHA/$(git rev-parse HEAD)/g; s/BASE_SHA/$base/g" > mech-app.json <<'JSON'
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
   "note": "1 fail"
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
   "note": "the stack plan does not read: .ekit/stack-plan.toml at 1a2b3c4d5e6f: stack[1] `web`, field status: `done`: want planned, current or retiring",
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
   "problem": "the stack plan does not read: .ekit/stack-plan.toml at 1a2b3c4d5e6f: stack[1] `web`, field status: `done`: want planned, current or retiring",
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
   "problem": "the adapter's parser failed: `ktfacts` exited 1: unexpected token at 12:3",
   "hint": "fix the parser command or its pinned install step in the adapter file, in a PR of its own; R2 reads nothing of this stack until the parser runs",
   "forbidden": "falling back to patterns, or skipping R2, when the parser fails"
  }
 ],
 "summary": "fail HEAD_SHA (2 fail, 0 confirm)"
}
JSON
git checkout -q main; git checkout -qb claude/calc
printf 'package com.example;\n\npublic final class Calc {\n    public static int add(int a, int b) {\n        return a + b;\n    }\n\n    public static int unused() { // NOPMD\n        return 0;\n    }\n}\n' > src/main/java/com/example/Calc.java
mkdir -p web; printf '{"name": "web"}\n' > web/package.json
git add -A; git commit -qm "calc: unused helper; web: package"
sed "s/HEAD_SHA/$(git rev-parse HEAD)/g; s/BASE_SHA/$base/g" > mech.json <<'JSON'
{
 "ekit": "0.5.0",
 "base": "BASE_SHA",
 "head": "HEAD_SHA",
 "checks": {
  "R0": {
   "status": "fail",
   "note": "static half: 16 of 17 cases proved; failed: skip; runtime half (run): controls: 4 of 5 read right"
  },
  "R1": {
   "status": "n/a",
   "note": "blocked: R0 failed (R0 static half failed for the `maven` adapter)"
  },
  "R2": {
   "status": "n/a",
   "note": "blocked: R0 failed (R0 static half failed for the `maven` adapter)"
  },
  "R3": {
   "status": "skipped",
   "note": "not run here"
  },
  "R4": {
   "status": "n/a",
   "note": "blocked: R0 failed (R0 static half failed for the `maven` adapter)"
  },
  "D": {
   "status": "fail",
   "note": "judged by the base branch's plan",
   "messages": []
  }
 },
 "entries": [
  {
   "id": "R0-2b12725b",
   "check": "R0",
   "class": "adapter-fix",
   "severity": "fail",
   "file": ".ekit/adapters/maven.toml",
   "line": 0,
   "problem": "R0 runtime half (run) failed for the `maven` adapter: control `pass` read error: [INFO] Scanning for projects... (want pass)",
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
   "hint": "repair the adapter (ci-doctor repair mode) in a PR of its own, then re-run R0",
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
   "id": "R2-f3a6a4fd",
   "check": "R2",
   "class": "agent-fixable",
   "severity": "fail",
   "file": "src/main/java/com/example/Calc.java",
   "line": 8,
   "problem": "`NOPMD` added without a reason",
   "hint": "fix the PMD finding, or give the suppression a reason after it: `// NOPMD - why`",
   "forbidden": "a suppression with no reason",
   "blocked": "R0"
  }
 ],
 "summary": "fail HEAD_SHA (4 fail, 0 confirm)"
}
JSON
