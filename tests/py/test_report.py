import json
import os
import tempfile
import unittest
from unittest import mock

import _kit
from scripts.mech_review import report


class TestVersion(unittest.TestCase):
    def test_the_version_is_the_plugin_manifests(self):
        # a file in a temp dir, not a NamedTemporaryFile: Windows will not open that one a second time
        with tempfile.TemporaryDirectory() as tmp, open(os.path.join(tmp, "plugin.json"), "w") as f:
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
            with tempfile.TemporaryDirectory() as tmp, open(os.path.join(tmp, "plugin.json"), "w") as f:
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


    def test_the_drift_check_is_named_only_when_the_envelope_holds_it(self):
        checks = self.checks(R2="pass")
        self.assertEqual(report.summarize("abc", checks, []), "pass abc (0 fail, 0 confirm; ran: R2; skipped: R1 R3 R4)")
        with_d = dict(checks, D={"status": "pass", "note": ""})
        self.assertEqual(report.summarize("abc", with_d, []), "pass abc (0 fail, 0 confirm; ran: R2 D; skipped: R1 R3 R4)")

    def test_a_failed_drift_check_fails_the_summary_and_keeps_all_pass_away(self):
        every = {c: {"status": "pass", "note": ""} for c in report.CHECKS}
        self.assertEqual(report.summarize("abc", every, []), "all pass abc")
        self.assertEqual(report.summarize("abc", dict(every, D={"status": "pass", "note": ""}), []), "all pass abc")
        self.assertEqual(report.summarize("abc", dict(every, D={"status": "fail", "note": ""}), []),
                         "fail abc (0 fail, 0 confirm; ran: R1 R2 R3 R4 D)")


if __name__ == "__main__":
    unittest.main()
