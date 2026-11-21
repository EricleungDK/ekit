"""R3's runner over its budget: the run is stopped and reads "timeout", on an OS with process groups and on one
without (Windows has no os.killpg and no signal.SIGKILL)."""
import contextlib
import os
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock

import _kit  # noqa: F401 - the import puts the repo root on sys.path
from scripts.mech_review import mutants

SLEEPER = [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"]


@contextlib.contextmanager
def without(module, *names):
    """`module` as an OS without these names has it."""
    saved = {n: getattr(module, n) for n in names if hasattr(module, n)}
    for n in saved:
        delattr(module, n)
    try:
        yield
    finally:
        for n, v in saved.items():
            setattr(module, n, v)


class OverBudget(unittest.TestCase):
    def run_it(self):
        with tempfile.TemporaryDirectory() as cwd:
            t0 = time.time()
            rc, _ = mutants.default_runner()(SLEEPER, cwd, 1)
            return rc, time.time() - t0

    def test_a_run_over_its_budget_is_stopped_and_reads_timeout(self):
        with mock.patch.object(mutants, "KILL_GRACE", 1):
            rc, took = self.run_it()
        self.assertEqual(rc, "timeout")
        self.assertLess(took, 30)

    def test_without_process_groups_the_run_is_still_stopped(self):
        with without(os, "killpg"), without(signal, "SIGKILL"), mock.patch.object(mutants, "KILL_GRACE", 1):
            rc, took = self.run_it()
        self.assertEqual(rc, "timeout")
        self.assertLess(took, 30)


if __name__ == "__main__":
    unittest.main()
