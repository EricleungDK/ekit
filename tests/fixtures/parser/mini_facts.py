"""A stub parser command for an adapter file's [parser] table (#27): the facts of one `mini` file as JSON.

stdin: the file's text; the last argument: its path. It reads the file the way tests/fixtures/adapters/mini.toml does
(ekit's own scanner with that table), so an adapter that runs it is the parser-backed twin of mini.toml: the same R2
entries are expected of both. Options before the path, for the failure and safety tests:
  --emit FILE    print FILE's bytes instead of the facts (canned output: invalid JSON, a schema the core must refuse)
  --exit N       print the facts, then exit with status N
  --hang         sleep before printing anything (the core's timeout must stop it)
  --table FILE   read with this pattern adapter file in place of mini.toml (its twin for that file)
  --spawn FILE   start a background child that writes FILE after 2 s, and do not wait for it (the core must kill it)
  --record FILE  append one JSON line {cwd, cwd_files, env, argv, stdin} to FILE, then print the facts
Fact schema: docs/mech-review-ci.md#parser."""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MINI = os.path.join(ROOT, "tests", "fixtures", "adapters", "mini.toml")
sys.path.insert(0, ROOT)

from scripts.mech_review import adapter_file
from scripts.mech_review.scan import line_of


def facts(text, table=MINI):
    a = adapter_file.load(table)
    n_lines = text.count("\n") + 1
    err = a.parse_error(text)
    if err:
        return {"format": 1, "parse_error": {"line": err[0], "message": err[1]}, "tests": [], "asserts": [],
                "suppressions": [], "mutation_skips": []}
    _, _, _, _, scoped, _ = a._parse(text)
    ends = {}
    for name, call, _ in scoped:
        ends.setdefault(name, []).append(line_of(text, call.end - 1))
    calls = a.calls(text)
    tests = []
    for f in a.test_fns(text):
        tests.append({"name": f.name, "line": f.line, "end_line": ends[f.name].pop(0), "markers": list(f.markers),
                      "body": list(f.body) if f.body else None, "calls": sorted(calls.get(f.name, ()))})
    asserts = [{"line": x.line, "test": x.fn, "owner": x.owner, "kind": x.kind, "left": x.left, "right": x.right,
                "text": x.text} for x in a.assertions(text)]
    sups = [{"line": s.line, "end_line": min(s.end_line, n_lines), "kind": s.kind, "lints": s.lints,
             "reason": s.reason} for s in a.suppressions(text)]
    skips = [{"line": s, "end_line": e, "marker": m} for s, e, m in a.mutation_skips(text)]
    return {"format": 1, "parse_error": None, "tests": tests, "asserts": asserts, "suppressions": sups,
            "mutation_skips": skips}


def main(argv):
    text = sys.stdin.buffer.read().decode("utf-8", "surrogateescape")
    args, code, table = argv[:-1], 0, MINI
    while args:
        opt = args.pop(0)
        if opt == "--emit":
            with open(args.pop(0), "rb") as f:
                sys.stdout.buffer.write(f.read())
            return 0
        if opt == "--exit":
            code = int(args.pop(0))
        elif opt == "--spawn":
            subprocess.Popen([sys.executable, "-I", "-c", "import sys, time; time.sleep(2); open(sys.argv[1], 'w').close()",
                              args.pop(0)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif opt == "--table":
            table = args.pop(0)
        elif opt == "--hang":
            time.sleep(60)
        elif opt == "--record":
            with open(args.pop(0), "a") as f:
                f.write(json.dumps({"cwd": os.getcwd(), "cwd_files": sorted(os.listdir(".")), "env": dict(os.environ),
                                    "argv": argv, "stdin": text}) + "\n")
    print(json.dumps(facts(text, table)))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
