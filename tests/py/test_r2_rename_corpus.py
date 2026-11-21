"""R2 rename pairing (#41) is a cheat surface: two unrelated tests that pair turn a deleted test into a `confirm`. Each
row is one test shape seen in real suites; a new shape the pairing must handle goes here as one more row. `confirm`: a
real rename whose asserts changed pairs; `fail`: an unrelated replacement stays a removed test. Shapes with a test of
their own live in test_r2_rename.py; this table holds the rest, through `cli.main(["r2", ...])` on a fixture repo."""
import json
import os
import tempfile
import unittest

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from test_adapter_cli import Repo, r2

VITEST = ("package.json", '{"name":"x","devDependencies":{"vitest":"1.0.0"}}\n')
TS_HEAD = "import { it, test, describe, expect } from 'vitest'\nimport { f, g, h } from '../src/a'\n\n"
BODY = "  const x = f(1)\n  const y = g(x)\n  const z = h(y)\n  expect(z).toBe(2)\n"
OPTS = "{\n    mode: 'fast',\n    retries: 3,\n    debug: false,\n}"
DESCRIBE = ("describe('S', () => {\n  it('a', () => {\n    const x = f(1)\n    const y = g(x)\n    const z = h(y)\n"
            "    expect(z).toBe(2)\n  })\n  it('keep', () => {\n    const x = f(1)\n    const y = g(x)\n"
            "    const z = h(y)\n    expect(z).toBe(2)\n  })\n})\n")


def legit(template):
    """a ts rename of test `a` to `b`: body kept, assert changed"""
    base = template.replace("NAME", "a").replace("BODY", BODY)
    return base, base.replace("'a'", "'b'").replace("toBe(2)", "toBe(3)")


# (shape, base file, head file, the one entry's severity)
TS = [
    ("async function callback", *legit("it('NAME', async function () {\nBODY})\n"), "confirm"),
    ("arrow with braces in default params", *legit("it('NAME', ({ a = {} } = {}) => {\nBODY})\n"), "confirm"),
    ("jest timeout as third argument", *legit("it('NAME', () => {\nBODY}, 5000)\n"), "confirm"),
    ("mocha .timeout chain", *legit("it('NAME', function () {\nBODY}).timeout(5000)\n"), "confirm"),
    ("multi-line options object, then callback", *legit("it('NAME', " + OPTS + ", () => {\nBODY})\n"), "confirm"),
    ("options object cast with as", *legit("it('NAME', { timeout: 1 } as any, () => {\nBODY})\n"), "confirm"),
    ("named callback has no body",
     "function helper() {\n" + BODY + "}\nit('a', helper)\n", "function helper() {\n" + BODY + "}\nit('z', helper)\n",
     "fail"),
    ("describe callback is never a body", DESCRIBE,
     DESCRIBE.replace("it('a', () => {\n    const x = f(1)\n    const y = g(x)\n    const z = h(y)\n    expect(z).toBe(2)",
                      "it('q', () => {\n    expect(1).toBe(1)"), "fail"),
    ("same object as options before and as a local inside",
     "it('a', " + OPTS + ", () => {\n  expect(f(1)).toBe(2)\n})\n",
     "it('z', " + OPTS + ", () => {\n  const o = " + OPTS.replace("\n", "\n  ") + "\n  expect(1).toBe(1)\n})\n", "fail"),
]


class R2RenameCorpus(unittest.TestCase):
    def test_each_ts_shape(self):
        for shape, before, after, want in TS:
            with self.subTest(shape), tempfile.TemporaryDirectory() as tmp:
                repo = Repo(os.path.join(tmp, "r"))
                base = repo.commit({VITEST[0]: VITEST[1], "src/a.ts": "export const f = (x: number) => x\n",
                                    "tests/a.test.ts": TS_HEAD + before}, "base")
                head = repo.commit({"tests/a.test.ts": TS_HEAD + after}, "head")
                res = r2(repo, base, head, adapter=None, stack="ts")
                got = [e["severity"] for e in json.loads(res.stdout)["entries"]]
                self.assertEqual(got, [want], json.loads(res.stdout)["entries"])


if __name__ == "__main__":
    unittest.main()
