#!/bin/bash
# fixture: calc.py + cli.py with a test file each, a suite command and a lint command named in AGENTS.md.
# The task touches both files: two units, each with its own verify command, plus the suite for the whole job.
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n' >> .git/info/exclude  # sandbox HOME files: not the work, keep the finish gate quiet
mkdir tests
cat > calc.py <<'PY'
def div(a, b):
    return a / b
PY
cat > cli.py <<'PY'
import sys
from calc import div

if __name__ == "__main__":
    print(div(float(sys.argv[1]), float(sys.argv[2])))
PY
cat > tests/test_calc.py <<'PY'
import unittest
from calc import div


class TestDiv(unittest.TestCase):
    def test_divides(self):
        self.assertEqual(div(6, 3), 2)
PY
cat > tests/test_cli.py <<'PY'
import subprocess
import sys
import unittest


class TestCli(unittest.TestCase):
    def test_prints_the_quotient(self):
        out = subprocess.run([sys.executable, "cli.py", "6", "3"], capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "2.0")
PY
cat > AGENTS.md <<'MD'
# Agents

- Lint: `python3 -m compileall -q calc.py cli.py`
- One test file: `python3 -m unittest tests.test_calc` (or `tests.test_cli`)
- Full suite: `python3 -m unittest discover -s tests -t .`
- Commits: conventional, no attribution trailer.
MD
git add -A; git commit -qm "calc + cli"
