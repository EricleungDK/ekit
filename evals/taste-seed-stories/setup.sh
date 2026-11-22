#!/bin/bash
# fixture: a new todo CLI with saved user stories (docs/stories.md, an issues export) and no code yet
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n' >> .git/info/exclude  # sandbox HOME files: not the work, keep the finish gate quiet
cat > README.md <<'MD'
# todo

A command-line todo list: one file, `todo.py`, run as `python3 todo.py <command>`. Tasks are kept in `tasks.json` in
the current directory. Not written yet.
MD
mkdir -p docs
cat > docs/stories.md <<'MD'
# User stories

## add-task
As a user I can add a task from the command line.
Acceptance: `python3 todo.py add "buy milk"` exits 0 and prints `added: buy milk`.

## list-tasks
As a user I can list my open tasks, oldest first.
Acceptance: after adding `buy milk` then `call mum`, `python3 todo.py list` prints `1. buy milk` and `2. call mum`, in that order.
MD
cat > docs/issues-export.md <<'MD'
# Issues (exported from the tracker)

## #3 finish-task
As a user I can mark a task done, so it leaves the open list.
Acceptance: after adding `buy milk`, `python3 todo.py done 1` exits 0, and `python3 todo.py list` no longer prints `buy milk`.
MD
git add -A; git commit -qm "todo: readme and user stories"
