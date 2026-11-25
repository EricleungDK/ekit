#!/bin/bash
# fixture: an empty repo. The prompt carries the five mistakes and their evidence; the run is a dry run (no edit).
set -e
git init -q .
printf '.gitconfig\n.config/\n.npm/\n' >> "$(git rev-parse --git-dir)/info/exclude"  # sandbox HOME files: not the work
