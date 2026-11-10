import json
import os
import tempfile
import unittest
from unittest import mock

import _kit
from scripts.mech_review import report


class TestVersion(unittest.TestCase):
    def test_the_version_is_the_plugin_manifests(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump({"name": "ekit", "version": "9.8.7"}, f)
            f.flush()
            with mock.patch.object(report, "PLUGIN", f.name):
                self.assertEqual(report.ekit_version(), "9.8.7")

    def test_the_manifest_path_is_the_plugins_beside_scripts(self):
        self.assertEqual(report.PLUGIN, os.path.join(_kit.ROOT, ".claude-plugin", "plugin.json"))

    def test_no_manifest_beside_the_scripts_is_unknown_not_a_crash(self):
        with mock.patch.object(report, "PLUGIN", os.path.join(tempfile.gettempdir(), "ekit-no-such", "plugin.json")):
            self.assertEqual(report.ekit_version(), "unknown")

    def test_a_manifest_that_is_not_json_or_has_no_version_is_unknown(self):
        for text in ("{", "{}"):
            with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
                f.write(text)
                f.flush()
                with mock.patch.object(report, "PLUGIN", f.name):
                    self.assertEqual(report.ekit_version(), "unknown", text)


class TestSummary(unittest.TestCase):
    def checks(self, **status):
        return {c: {"status": status.get(c, "skipped"), "note": ""} for c in report.CHECKS}

    def test_the_checks_that_ran_are_listed_with_single_spaces(self):
        self.assertEqual(report.summarize("abc", self.checks(R1="pass", R2="pass", R4="pass"), [{"severity": "confirm"}]),
                         "pass abc (0 fail, 1 confirm; ran: R1 R2 R4; skipped: R3)")

    def test_no_check_ran_reads_none(self):
        self.assertEqual(report.summarize("abc", self.checks(R3="n/a"), [{"severity": "fail"}]),
                         "fail abc (1 fail, 0 confirm; ran: none; skipped: R1 R2 R4; n/a: R3)")


if __name__ == "__main__":
    unittest.main()
