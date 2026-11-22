#!/bin/bash
# fixture: a JS package (package.json, src/greet.js, test/greet.test.js) whose committed stack plan lists it as one
# current stack, `js` (adapter ts: the built-in covers JS and TS). The run should end with a TS entry in the plan, `js`
# retiring, and a drift check that names no uncovered manifest (#57).
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n' >> .git/info/exclude  # sandbox HOME files: not the work, keep the finish gate quiet
cat > package.json <<'JSON'
{
  "name": "greet",
  "version": "1.0.0",
  "type": "module",
  "main": "src/greet.js",
  "scripts": { "test": "node --test test/" }
}
JSON
mkdir -p src test .ekit
cat > src/greet.js <<'JS'
export function greet(name) {
  if (!name) throw new Error("name is required");
  return `Hello, ${name}!`;
}
JS
cat > test/greet.test.js <<'JS'
import { test } from "node:test";
import assert from "node:assert/strict";
import { greet } from "../src/greet.js";

test("greets by name", () => assert.equal(greet("Ada"), "Hello, Ada!"));
test("a missing name throws", () => assert.throws(() => greet(""), /name is required/));
JS
cat > .ekit/stack-plan.toml <<'TOML'
[[stack]]
name = "js"
folder = "."
adapter = "ts"
status = "current"
TOML
git add -A; git commit -qm "greet: js package, stack plan"
