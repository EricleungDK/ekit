"""Shared setup for the python tests: the repo root on sys.path, so the kit imports as `scripts.<module>`.

That name is the one mutmut derives from the file path (scripts/mech_review/waiver.py -> scripts.mech_review.waiver),
which is what lets R3 tie a mutant to the tests that reach it. Hyphenated scripts are loaded under the same scheme."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def load(name):
    """scripts/<name>.py as the module `scripts.<name>` (finish-gate, failure-match: not importable by name)."""
    spec = importlib.util.spec_from_file_location(f"scripts.{name}", os.path.join(SCRIPTS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
