#!/bin/bash
# fixture: a new notes CLI with three saved user stories (docs/stories.md) and no code yet
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n' >> .git/info/exclude  # sandbox HOME files: not the work, keep the finish gate quiet
cat > README.md <<'MD'
# notes

A command-line notebook: one file, `notes.py`, run as `python3 notes.py <command>`. Notes are kept in `notes.db.json`
in the current directory. Not written yet.
MD
mkdir -p docs
cat > docs/stories.md <<'MD'
# User stories

## add-note
As a user I can add a note and see it in my list.
Acceptance: `python3 notes.py add "buy milk"`, then `python3 notes.py list` prints `buy milk`.

## share-note
As a user I can share a note by email.
Acceptance: `python3 notes.py share 1 --to friend@example.com` sends note 1 to that address.

## export-notes
As a user I can export my notes to a CSV file.
Acceptance: after adding two notes, `python3 notes.py export out.csv` writes `out.csv` with one row per note.
MD
git add -A; git commit -qm "notes: readme and user stories"
