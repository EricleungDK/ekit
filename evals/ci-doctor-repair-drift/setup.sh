#!/bin/bash
# fixture: a python package with mech-review and a stack plan on main (one stack, python, at the root). The coding
# branch claude/web (checked out) adds the team's new TypeScript frontend in web/ (package.json, vitest): a manifest no
# stack covers, so the PR's drift check failed D (mech.json, the engine's entry). The run should end on a repair branch
# cut from main whose plan covers web/ (an entry with an adapter that lists package.json: the built-in ts, `planned`
# until the manifest lands) or ignores it, drift clean there and on claude/web merged onto it, main and claude/web as
# they were, and no `mech:` line anywhere (#24). The grader support is ci-doctor-repair-java-runner's.
set -e
here="$(cd "$(dirname "$0")" && pwd -P)"
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n.cache/\nmech.json\n' >> .git/info/exclude  # sandbox HOME files and the input
mkdir -p src/slug tests .ekit .github/workflows
printf '[project]\nname = "slug"\nversion = "1.0"\n' > pyproject.toml
printf 'def slug(s):\n    return s.strip().lower().replace(" ", "-")\n' > src/slug/__init__.py
printf 'from slug import slug\n\n\ndef test_slug():\n    assert slug(" A b ") == "a-b"\n' > tests/test_slug.py
cat > .ekit/stack-plan.toml <<'T'
[[stack]]
name = "slug"
folder = "."
adapter = "python"
status = "current"
T
cat > .github/workflows/mech-review.yml <<'Y'
name: mech-review
on:
  pull_request:
permissions:
  contents: read
  pull-requests: write
jobs:
  mech-review:
    uses: EricleungDK/ekit/.github/workflows/mech-review.yml@v0
    with:
      protected-paths: |
        .github/**
Y
git add -A; git commit -qm "slug: python package, mech-review"
git checkout -qb claude/web
mkdir -p web/src
cat > web/package.json <<'J'
{"name": "slug-web", "private": true, "type": "module",
 "scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "3.2.4", "typescript": "5.8.3"}}
J
printf 'export function title(s: string): string {\n  return s.trim().replace(/-/g, " ");\n}\n' > web/src/title.ts
cat > web/src/title.test.ts <<'TS'
import { expect, test } from "vitest";
import { title } from "./title";

test("title", () => {
  expect(title(" a-b ")).toBe("a b");
});
TS
git add -A; git commit -qm "web: the slug frontend"
head=$(git rev-parse HEAD); base=$(git rev-parse main)
sed "s/HEAD_SHA/$head/g; s/BASE_SHA/$base/g" > mech.json <<'JSON'
{
 "ekit": "0.5.0",
 "base": "BASE_SHA",
 "head": "HEAD_SHA",
 "checks": {
  "R1": {
   "status": "skipped",
   "note": "not run by drift"
  },
  "R2": {
   "status": "skipped",
   "note": "not run by drift"
  },
  "R3": {
   "status": "skipped",
   "note": "not run by drift"
  },
  "R4": {
   "status": "skipped",
   "note": "not run by drift"
  },
  "D": {
   "status": "fail",
   "note": "judged by the base branch's plan",
   "messages": []
  }
 },
 "entries": [
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
  }
 ],
 "summary": "fail HEAD_SHA (1 fail, 0 confirm; ran: D; skipped: R1 R2 R3 R4)"
}
JSON
source "$here/../ci-doctor-repair-java-runner/arm.sh"
arm_repair '{"kind": "drift", "cover": "web"}'
