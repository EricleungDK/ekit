"""The one-test pattern for vitest and jest (`-t`): both runners match it against the test's full name, its describe
names and its own joined with a space (vitest 2.1.9 and 3.2.7, jest 29.7.0: `-t '^Calc > adds$'` selects nothing,
`-t '^Calc adds$'` selects the one test). The built-in ts adapter and ts.toml give the same argv; regex characters in a
name stay literal, so the pattern still selects exactly that test."""
import os
import unittest

import _kit
from scripts.mech_review import adapter_file, stack

TS_FILE = os.path.join(_kit.ROOT, "scripts", "mech_review", "adapters", "ts.toml")
ADAPTERS = {"built-in": stack.TsAdapter(), "ts.toml": adapter_file.load(TS_FILE)}


class SpaceJoined(unittest.TestCase):
    def pattern(self, adapter, cmd, name):
        return ADAPTERS[adapter].test_argv(cmd, "tests/calc.test.ts", name)[-1]

    def test_vitest_joins_describe_and_test_with_a_space(self):
        for a in ADAPTERS:
            with self.subTest(adapter=a):
                self.assertEqual(self.pattern(a, "node_modules/.bin/vitest run", "Calc > inner > deep"),
                                 "^Calc inner deep$")

    def test_jest_joins_with_a_space(self):
        for a in ADAPTERS:
            with self.subTest(adapter=a):
                self.assertEqual(self.pattern(a, "node_modules/.bin/jest", "Calc > inner > deep"), "^Calc inner deep$")

    def test_regex_characters_stay_literal(self):
        for a in ADAPTERS:
            with self.subTest(adapter=a):
                self.assertEqual(self.pattern(a, "node_modules/.bin/vitest run", "Calc > adds (1) [x]"),
                                 "^Calc adds \\(1\\) \\[x\\]$")


if __name__ == "__main__":
    unittest.main()
