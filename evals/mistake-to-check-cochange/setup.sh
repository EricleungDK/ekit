#!/bin/bash
# fixture: a python package whose AGENTS.md says a change under app/ updates CHANGELOG.md. Two PRs broke it: #12 (the
# incident the prompt names) and #15 (the second example). The run should end with a co-change rule for it, proved.
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n__pycache__/\n' >> .git/info/exclude  # sandbox HOME files: not the work
mkdir -p app tests
printf '[project]\nname = "core"\nversion = "1.0.0"\n' > pyproject.toml
printf 'def retries():\n    return 1\n' > app/core.py
printf 'import unittest\nfrom app.core import retries\n\n\nclass T(unittest.TestCase):\n    def test_retries(self):\n        self.assertGreaterEqual(retries(), 1)\n' > tests/test_core.py
printf '# Changelog\n\n## Unreleased\n' > CHANGELOG.md
cat > AGENTS.md <<'MD'
# Agents

- Tests: `python3 -m unittest discover -s tests`
- A behaviour change under `app/` updates `CHANGELOG.md` (`## Unreleased`).
MD
git add -A; git commit -qm "core 1.0"
printf 'def retries():\n    return 3\n' > app/core.py
git commit -qam "core: three retries (#12)"
printf '# Changelog\n\n## Unreleased\n\n- docs typo\n' > CHANGELOG.md
git commit -qam "changelog: typo (#13)"
printf 'def retries():\n    return 3\n\n\ndef timeout():\n    return 30\n' > app/core.py
git commit -qam "core: a timeout (#15)"
