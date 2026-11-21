#!/bin/bash
# fixture: a one-file repo; the prompt carries the run's state (rounds used, CI result). Nothing to build.
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n__pycache__/\n' >> .git/info/exclude  # sandbox HOME files: not the work, keep the finish gate quiet
printf 'def slug(s):\n    return s.strip().lower().replace(" ", "-")\n' > slug.py
git add -A; git commit -qm "slug"
