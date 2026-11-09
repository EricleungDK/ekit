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


if __name__ == "__main__":
    unittest.main()
