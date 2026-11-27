#!/bin/bash
# fixture: a Java backend (backend/: the kit's Java fixture repo, tests/fixtures/java/base, Maven) beside a TS frontend
# (frontend/: package.json, vitest). Which one mech-review checks first is the user's call: the run should end with a
# question naming both projects and no commit on any branch, never a guess (#23). The grader support is
# ci-doctor-setup-java's; only its new-commits and main lines matter here.
set -e
here="$(cd "$(dirname "$0")" && pwd -P)"
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n.m2/\n' >> .git/info/exclude  # sandbox HOME files: not the work
mkdir -p backend frontend/src frontend/test
cp -R "$here/../../tests/fixtures/java/base/." backend/
cat > frontend/package.json <<'JSON'
{
  "name": "web",
  "version": "1.0.0",
  "type": "module",
  "scripts": { "test": "vitest run" },
  "devDependencies": { "vitest": "^2.1.9" }
}
JSON
printf 'export function total(xs: number[]): number {\n  return xs.reduce((a, b) => a + b, 0);\n}\n' > frontend/src/total.ts
cat > frontend/test/total.test.ts <<'TS'
import { expect, it } from "vitest";
import { total } from "../src/total";

it("adds the prices", () => expect(total([1, 2])).toBe(3));
TS
git add -A; git commit -qm "backend and frontend"
source "$here/../ci-doctor-setup-java/arm.sh"
arm_verdict '{"status": "current", "folder": "backend", "target_os": "linux", "ci": "write"}'
