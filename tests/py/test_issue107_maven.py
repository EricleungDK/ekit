"""#107 B3: a no-report R3 run gets the CI entry (class env) only from Maven's own goal-failure line (`[ERROR] Failed to
execute goal … Could not resolve / transfer`); a test that prints those words anywhere else keeps the R3 entry
(agent-fixable). R3 is `fail` either way. `mutants` through cli.main in this process, the declared tool a stub that
prints STUB_OUT and writes no report (test_adapter_mutation_cli's fixture)."""
import unittest
from unittest import mock

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import report
from test_adapter_mutation_cli import ELEMENTS, Case, adapter_text

GOAL_RESOLVE = ("[ERROR] Failed to execute goal on project calc: Could not resolve dependencies for project "
                "com.x:calc:jar:1.0: The following artifacts could not be resolved: junit:junit:jar:4.13 (absent): "
                "Could not transfer artifact junit:junit:jar:4.13 from/to central (https://repo.maven.apache.org/"
                "maven2): repo.maven.apache.org: Unknown host repo.maven.apache.org -> [Help 1]")
GOAL_TRANSFER = ("[ERROR] Failed to execute goal org.pitest:pitest-maven:1.17.4:mutationCoverage (default-cli) on "
                 "project calc: Execution default-cli of goal org.pitest:pitest-maven:1.17.4:mutationCoverage failed: "
                 "Plugin org.pitest:pitest-maven:1.17.4 or one of its dependencies could not be resolved: "
                 "Could not transfer artifact org.pitest:pitest:jar:1.17.4 from/to central: Connection reset "
                 "-> [Help 1]")
GOAL_TESTS = ("[ERROR] Failed to execute goal org.apache.maven.plugins:maven-surefire-plugin:3.2.5:test (default-test) "
              "on project calc: There are test failures.")
TRAILER = ("[ERROR] \n[ERROR] To see the full stack trace of the errors, re-run Maven with the -e switch.\n"
           "[ERROR] -> [Help 1]\n")
FAILURE = "[INFO] " + "-" * 72 + "\n[INFO] BUILD FAILURE\n[INFO] " + "-" * 72 + "\n[INFO] Total time:  2.1 s\n"
SUCCESS = "[INFO] " + "-" * 72 + "\n[INFO] BUILD SUCCESS\n[INFO] " + "-" * 72 + "\n"
TEST_PRINTS = "[INFO] Running com.x.CalcTest\n"  # what a test's own output sits after in a Maven run


class MavenResolution(Case):
    def entries(self, out):
        self.pr()
        r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"STUB_OUT": out, "STUB_RC": "1"})
        self.assertEqual((r.returncode, env["checks"]["R3"]["status"]), (1, "fail"), r.stderr)
        return [(e["check"], e["class"], e["severity"]) for e in env["entries"]]

    def test_mavens_goal_failure_line_gives_the_ci_entry(self):
        for out in (
                f"[INFO] Scanning for projects...\n{FAILURE}{GOAL_RESOLVE}\n{TRAILER}",
                f"{FAILURE}{GOAL_TRANSFER}\n{TRAILER}",
                f"{GOAL_RESOLVE}\n{TRAILER}",  # -q: no INFO lines, no BUILD FAILURE banner
                f"{FAILURE}{GOAL_RESOLVE}\n{TRAILER}{GOAL_TESTS}\n{TRAILER}",  # --fail-at-end: every goal Maven failed
                f"{FAILURE}{GOAL_RESOLVE}",  # the last line, no newline
                # the resolve text continued on the [ERROR] lines after the goal line (Maven 3.9's cause list)
                f"{FAILURE}[ERROR] Failed to execute goal on project calc: Could not resolve dependencies for project "
                "com.x:calc:jar:1.0\n[ERROR] dependency: junit:junit:jar:4.13 (test)\n"
                "[ERROR] \tCould not transfer artifact junit:junit:jar:4.13 from/to central\n" + TRAILER,
                # Maven 3.9: the phrase on the goal line, the cause list after it without one (review N3)
                f"{FAILURE}[ERROR] Failed to execute goal on project calc: Could not resolve dependencies for project "
                "com.x:calc:jar:1.0\n[ERROR] dependency: junit:junit:jar:4.13 (test)\n"
                "[ERROR] \tjunit:junit:jar:4.13 was not found in https://repo.maven.apache.org/maven2\n" + TRAILER,
                f"{FAILURE}[ERROR] Failed to execute goal on project calc: dependencies failed\n"
                "[ERROR] \trepo.maven.apache.org: Unknown host repo.maven.apache.org\n" + TRAILER,
                # colour: Maven without -B
                "[INFO] \x1b[1;31mBUILD FAILURE\x1b[m\n[\x1b[1;31mERROR\x1b[m] \x1b[1;31mFailed to execute goal on "
                "project calc: "
                "Could not resolve dependencies for project com.x:calc:jar:1.0\x1b[m\n"):
            for text in (out, out.replace("\n", "\r\n")):  # and CRLF
                with self.subTest(out=text):
                    self.assertEqual(self.entries(text), [("CI", "env", "fail")])

    def test_the_maven_words_printed_elsewhere_keep_the_r3_entry(self):
        forged = f"{GOAL_RESOLVE}\n"  # a test that prints Maven's whole goal-failure line
        for out in (
                # the pre-#107 inputs: the words, not on Maven's goal-failure line
                "[INFO] Scanning\n[ERROR] Failed: Could not resolve dependencies for project x\n",
                "[ERROR] Could not transfer artifact org.pitest:pitest:jar:1.17.4 from/to central\n",
                "[ERROR] ... Unknown host repo.maven.apache.org\n",
                # a test's output, then Maven's own goal line on another cause
                f"{TEST_PRINTS}[ERROR] Could not resolve host db.internal\n{FAILURE}{GOAL_TESTS}\n{TRAILER}",
                f"{TEST_PRINTS}{forged}{FAILURE}{GOAL_TESTS}\n{TRAILER}",
                f"{TEST_PRINTS}{FAILURE}{forged}{FAILURE}{GOAL_TESTS}\n{TRAILER}",  # a forged banner too
                f"{TEST_PRINTS}{FAILURE}{forged}{TRAILER}{SUCCESS}",  # the build passed: Maven failed no goal
                f"{TEST_PRINTS}{forged}{FAILURE}[ERROR] The build could not read 1 project\n",  # Maven failed no goal
                f"{TEST_PRINTS}{forged}{GOAL_TESTS}\n{TRAILER}",  # -q: Maven's goal line is the last one
                # the words after Maven's goal block ended, or mid-line, or indented
                f"{FAILURE}{GOAL_TESTS}\n[ERROR] -> [Help 1]\n[ERROR] Could not resolve dependencies\n",
                f"{FAILURE}{GOAL_TESTS}\n[ERROR] \n[ERROR] Could not resolve dependencies\n",
                f"{FAILURE}{GOAL_TESTS}\n[INFO] note\n[ERROR] \tCould not resolve dependencies\n",
                f"{FAILURE}test said: {GOAL_RESOLVE}\n",
                f"{FAILURE}  {GOAL_RESOLVE}\n",
                f"{FAILURE}[ERROR] Failed to execute goals on project calc: Could not resolve dependencies\n",
                ""):
            for text in (out, out.replace("\n", "\r\n")):  # and CRLF
                with self.subTest(out=text):
                    self.assertEqual(self.entries(text), [("R3", "agent-fixable", "fail")])


class OnePass(Case):
    """#107 review F2: the goal-failure lines are read in one pass: each output line is looked at for the phrases once,
    however many goal-failure lines follow each other (a tool that is not Maven, or -q, can print thousands)."""

    def test_each_line_is_read_once(self):
        n = 2000  # under one environment string's limit: the stub prints STUB_OUT
        out = "[INFO] BUILD FAILURE\n" + "[ERROR] Failed to execute goal x: boom\n" * n
        self.pr()
        with mock.patch.object(report, "_phrase", wraps=report._phrase) as phrase:
            r, env = self.cli("mutants", self.adapter(adapter_text(ELEMENTS)), env={"STUB_OUT": out, "STUB_RC": "1"})
        self.assertEqual([e["check"] for e in env["entries"]], ["R3"], r.stderr)
        self.assertLessEqual(phrase.call_count, n + 2)

    def test_a_long_output_is_read_in_linear_time(self):
        lines = ["[INFO] BUILD FAILURE"] + ["[ERROR] Failed to execute goal x: boom"] * 40000
        with mock.patch.object(report, "_phrase", wraps=report._phrase) as phrase:
            self.assertTrue(report.resolution_failed("\n".join(lines + ["[ERROR] Could not resolve x"])))
        self.assertLessEqual(phrase.call_count, len(lines) + 1)


if __name__ == "__main__":
    unittest.main()
