"""Shared setup for the python tests: the repo root on sys.path, so the kit imports as `scripts.<module>`.

That name is the one mutmut derives from the file path (scripts/mech_review/waiver.py -> scripts.mech_review.waiver),
which is what lets R3 tie a mutant to the tests that reach it. Hyphenated scripts are loaded under the same scheme."""
import collections
import contextlib
import importlib.util
import io
import os
import sys

# The repos these tests build are throwaway: no user or system git config reaches them (signing, hooks, templates).
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_SYSTEM"] = os.devnull

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _alias_engine():
    """The scripts import the engine as `mech_review` (their own dir is on sys.path). Point that name at the
    `scripts.mech_review` modules, so a script under test and the tests share one copy of each module."""
    import pkgutil

    import scripts.mech_review as pkg
    sys.modules.setdefault("mech_review", pkg)
    for m in pkgutil.iter_modules(pkg.__path__):
        sys.modules.setdefault(f"mech_review.{m.name}", importlib.import_module(f"scripts.mech_review.{m.name}"))


Result = collections.namedtuple("Result", "returncode stdout stderr")


def run_cli(argv, main=None):
    """`main(argv)` in this process (default: the engine's cli.main, what scripts/mech-review.py runs), stdout and stderr
    captured. A SystemExit (argparse's usage error, sys.exit) is read as the exit code, as the shell would see it; any
    other exception fails the test. In-process is what lets R3's mutmut credit the test (#35): a subprocess hides it."""
    if main is None:
        from scripts.mech_review import cli
        main = cli.main
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(list(argv))
        except SystemExit as e:
            rc = e.code
            if rc is not None and not isinstance(rc, int):
                print(rc, file=sys.stderr)
                rc = 1
    return Result(0 if rc is None else rc, out.getvalue(), err.getvalue())


def load(name):
    """scripts/<name>.py as the module `scripts.<name>` (finish-gate, failure-match: not importable by name)."""
    _alias_engine()
    spec = importlib.util.spec_from_file_location(f"scripts.{name}", os.path.join(SCRIPTS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
