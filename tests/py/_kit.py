"""Shared setup for the python tests: the kit's scripts on sys.path, and hyphenated scripts loaded as modules."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def load(name):
    """scripts/<name>.py as a module (finish-gate, failure-match: not importable by name)."""
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(SCRIPTS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
