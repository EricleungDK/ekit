#!/bin/bash
# Run all tests/*.test.sh; exit 1 if any fail.
cd "$(dirname "$0")" || exit 1
rc=0
for f in *.test.sh; do
  echo "$f"
  bash "$f" || rc=1
done
case "$(uname -s)" in  # Windows: ekit in the real shells there (tests/windows-smoke.py)
  MINGW*|MSYS*) echo "windows-smoke.py"; "$(command -v python3 || command -v python)" windows-smoke.py || rc=1 ;;
esac
[[ $rc == 0 ]] && echo "ALL PASS" || echo "FAILURES"
exit $rc
