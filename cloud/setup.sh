#!/bin/bash
# Claude Code on the web: paste into the environment's setup script.
# Fetches the kit and installs it into every git repo found in the VM.
# EKIT_REF pins what is fetched (a release tag such as v0, or a commit): default main, the latest unreleased kit.
# EKIT_REPO_URL fetches a fork or a mirror.
KIT="$HOME/.ekit"
REF="${EKIT_REF:-main}"
URL="${EKIT_REPO_URL:-https://github.com/EricleungDK/ekit}"
if [[ ! -d $KIT/.git ]]; then git init -q "$KIT" && git -C "$KIT" remote add origin "$URL"; fi
git -C "$KIT" remote set-url origin "$URL"
if git -C "$KIT" fetch -q --depth 1 origin "$REF" && git -C "$KIT" checkout -q --detach FETCH_HEAD; then :
else echo "ekit: cannot fetch $REF from $URL; keeping the kit already in $KIT (if any)" >&2; fi
[[ -f $KIT/cloud/install.sh ]] || { echo "ekit: no kit in $KIT; nothing installed" >&2; exit 0; }
found=0
for g in $( { git -C "$PWD" rev-parse --show-toplevel 2>/dev/null; find "$HOME" /workspace /workspaces /repo -maxdepth 3 -name .git -type d 2>/dev/null | xargs -r -n1 dirname; } | sort -u); do
  [[ $g == "$KIT" ]] && continue
  bash "$KIT/cloud/install.sh" "$g" && found=1
done
(( found )) || echo "ekit: no repo found yet (pwd=$PWD); run: bash ~/.ekit/cloud/install.sh <repo>"
