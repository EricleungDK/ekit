#!/bin/bash
# The suites run on any host with bash, git and python3 (#46): no tool stock macOS or Git for Windows lacks.
source "$(dirname "$0")/lib.sh"

# sha1: stdin to hex digest, as sha1sum's first field (FIPS 180 test vectors)
eq "$(printf abc | sha1)" "a9993e364706816aba3e25717850c26c9cd0d89d" "sha1: abc"
eq "$(printf '' | sha1)" "da39a3ee5e6b4b0d3255bfef95601890afd80709" "sha1: empty input"
eq "$(printf 'R2tests/a.rsb' | sha1 | cut -c1-8)" "$(python3 -c 'import hashlib; print(hashlib.sha1(b"R2tests/a.rsb").hexdigest()[:8])')" "sha1: bytes as given, no newline added"

# no suite calls sha1sum or timeout: absent on stock macOS
cmd_at() { cd "$ROOT/tests" && grep -nE "(^|[|;&(]|\\\$\\() *$1" lib.sh *.test.sh | grep -v '^helpers.test.sh:'; }
eq "$(cmd_at 'sha1sum')" "" "no suite runs sha1sum"
eq "$(cmd_at 'timeout +[0-9]')" "" "no suite runs timeout"

# LF checkouts whatever core.autocrlf says
eq "$(git -C "$ROOT" check-attr text eol -- tests/lib.sh | tr '\n' ' ')" "tests/lib.sh: text: auto tests/lib.sh: eol: lf " ".gitattributes: text=auto eol=lf"

# every PR adds a CHANGELOG line under `## Unreleased`: a local merge keeps both sides, no conflict
eq "$(git -C "$ROOT" check-attr merge -- CHANGELOG.md)" "CHANGELOG.md: merge: union" ".gitattributes: CHANGELOG.md merge=union"
done_tests
