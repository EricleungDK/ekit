#!/bin/bash
# fixture: lsx CLI; report 1 is real (--json prints null for an empty dir), report 2 is not (--hidden works);
# scenarios list-files (+ child json-output, non-empty dir only) do not cover either report
set -e
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n' >> .git/info/exclude  # sandbox HOME files: not the work, keep the finish gate quiet
cat > lsx.py <<'PY'
import json, os, sys
args = [a for a in sys.argv[1:] if not a.startswith("-")]
d = args[0] if args else "."
if not os.path.isdir(d):
    sys.exit(f"lsx: no such directory: {d}")
names = sorted(n for n in os.listdir(d) if "--hidden" in sys.argv or not n.startswith("."))
print(json.dumps(names or None) if "--json" in sys.argv else "\n".join(names))
PY
s() { mkdir -p ".ekit/scenarios/$1"; printf '%s\n' "$2" > ".ekit/scenarios/$1/SCENARIO.md"; printf '%s\n' "$3" > ".ekit/scenarios/$1/run.sh"; }
s list-files "- story: user lists a directory
- covers: lsx prints entries of a dir
- steps: create files a, b; run lsx .
- expected: a and b printed" 'touch a b; out=$(python3 "$EKIT_REPO/lsx.py" .); [[ $out == *a* && $out == *b* ]]'
s list-files/json-output "- story: user gets a machine-readable listing
- covers: lsx --json prints a JSON array of the entries
- steps: create files a, b; run lsx --json .
- expected: [\"a\", \"b\"]" 'touch a b; [[ $(python3 "$EKIT_REPO/lsx.py" --json .) == "[\"a\", \"b\"]" ]]'
git add -A; git commit -qm "lsx + scenarios"
