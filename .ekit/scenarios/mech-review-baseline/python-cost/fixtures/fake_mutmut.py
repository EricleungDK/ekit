#!/usr/bin/env python3
"""Fake mutmut 3.8.1 and pytest 9.2.0 for one python repo (argv[0] replaced via MECH_TEST_STUB). Not a scenario.

With MECH_TEST_STUB every tool mech-review runs comes here, so this answers as each would:
  --version                        mutmut's version line
  run <names|pattern>              mutmut: (re)writes its copies under mutants/ (mutmut 3.8.1's layout: the
                                   trampolined module, `.meta`, `.spans`, mutmut-stats.json) for each `.py` under
                                   `src/`, one mutant per `+` in a function body (`+` -> `-`); a pattern that names no
                                   mutant (the listing step) fails as mutmut's assertion does; named mutants run:
                                   killed, or survived when FAKE_SURVIVE (a regex) matches the name
  results --all True               mutmut's result lines, from the `.meta` exit codes
  apply <name>                     writes that mutant into the source file
  -B -m pytest ... --junit-xml=F   the baseline's whole-suite run: writes F with the session `time` FAKE_SUITE_S
                                   (default 0.5); FAKE_JUNIT=notime leaves the time out, FAKE_JUNIT=none writes no
                                   file; exits FAKE_SUITE_RC (default 0); FAKE_SUITE_HANG=1 hangs first
  -B -m pytest ...                 any other suite run (the whole-suite retry): exits FAKE_RETRY_RC (default 0)
  anything else                    the real python3 (sys.executable)
FAKE_MUTMUT_BROKEN=1: `--version` fails (mutmut not runnable). FAKE_LIST_BROKEN=1: `run` crashes, writing nothing.
FAKE_ARGV=<file> logs each argv; FAKE_RAN=<file> logs each mutant run by name.
"""
import json
import os
import re
import sys
import time

args = sys.argv[1:]
if os.environ.get("FAKE_ARGV"):
    with open(os.environ["FAKE_ARGV"], "a") as f:
        f.write(" ".join(args) + "\n")

if args[:3] == ["-B", "-m", "pytest"]:
    junit = [a.split("=", 1)[1] for a in args if a.startswith("--junit-xml=")]
    if not junit:
        sys.exit(int(os.environ.get("FAKE_RETRY_RC", "0")))
    if os.environ.get("FAKE_SUITE_HANG"):
        time.sleep(600)
    rc = int(os.environ.get("FAKE_SUITE_RC", "0"))
    t = os.environ.get("FAKE_SUITE_S", "0.5")
    kind = os.environ.get("FAKE_JUNIT", "")
    if kind != "none":
        tattr = "" if kind == "notime" else f' time="{t}"'
        fails = "1" if rc else "0"
        with open(junit[-1], "w") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
                    f'<testsuite name="pytest" errors="0" failures="{fails}" skipped="0" tests="1"{tattr}'
                    ' timestamp="2026-11-22T00:00:00.000000+00:00" hostname="h">'
                    '<testcase classname="tests.test_core" name="test_all"' + tattr + ' />'
                    '</testsuite></testsuites>')
    print(("1 failed" if rc else "1 passed") + f" in {t}s")
    sys.exit(rc)

if args[:1] == ["--version"]:
    if os.environ.get("FAKE_MUTMUT_BROKEN"):
        print("ModuleNotFoundError: No module named 'mutmut'", file=sys.stderr)
        sys.exit(1)
    print("mutmut, version 3.8.1")
    sys.exit(0)
if args[:1] == ["run"] and os.environ.get("FAKE_LIST_BROKEN"):
    print("Traceback (most recent call last):\n  ...\nKeyError: 'calc'", file=sys.stderr)
    sys.exit(1)
if args[:1] not in (["run"], ["results"], ["apply"]):
    os.execv(sys.executable, [sys.executable] + args)

STATUS = {None: "not checked", 0: "survived", 1: "killed", 33: "no tests"}


def sources():
    """The `.py` files under src/, narrowed to `only_mutate` when pyproject.toml's [tool.mutmut] sets it."""
    out = []
    for d, _, fs in os.walk("src"):
        out += [os.path.join(d, f) for f in sorted(fs) if f.endswith(".py")]
    try:
        m = re.search(r"^only_mutate\s*=\s*(\[.*?\])", open("pyproject.toml").read(), re.M | re.S)
    except OSError:
        m = None
    if m:
        only = set(json.loads(m.group(1)))
        out = [p for p in out if p in only]
    return sorted(out)


def module(path):
    m = path[len("src/"):-len(".py")].replace("/", ".")
    return m[: -len(".__init__")] if m.endswith(".__init__") else m


def functions(text):
    """(name, params, body lines) of each top-level `def` with an indented body."""
    return [(m.group(1), m.group(2), m.group(3).rstrip("\n").split("\n"))
            for m in re.finditer(r"^def (\w+)\((.*)\):\n((?:    .*\n?)+)", text, re.M)]


def mutants_of(body):
    out = []
    for i, line in enumerate(body):
        for j, ch in enumerate(line):
            if ch == "+":
                out.append(body[:i] + [line[:j] + "-" + line[j + 1:]] + body[i + 1:])
    return out


def write_copies():
    for src in sources():
        text = open(src).read()
        mod = module(src)
        lines = ["", "", "from mutmut.mutation.trampoline import wrap_in_trampoline as _mutmut_mutated, MutantDict"]
        spans, meta = {}, {}
        for name, params, body in functions(text):
            x = f"x_{name}"
            lines += [f"mutants_{x}__mutmut: MutantDict = {{}}  # type: ignore",
                      f"@_mutmut_mutated(mutants_{x}__mutmut)", f"def {name}({params}):"] + body
            variants = [("_mutmut_orig", f"{x}__mutmut_orig", body)]
            variants += [(None, f"{x}__mutmut_{k}", b) for k, b in enumerate(mutants_of(body), 1)]
            for _, fn, b in variants:
                start = len(lines) + 1
                lines += [f"def {fn}({params}):"] + b
                spans[fn] = [start, len(lines)]
            lines.append("")
            for key, fn, _ in variants:
                lines.append(f"mutants_{x}__mutmut['{key or fn}'] = {fn} # type: ignore # mutmut generated")
                if key is None:
                    meta[f"{mod}.{fn}"] = None
        dst = os.path.join("mutants", src)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w") as f:
            f.write("\n".join(lines) + "\n")
        with open(dst + ".spans", "w") as f:
            json.dump({"version": 1, "spans": spans}, f)
        if not os.path.exists(dst + ".meta"):
            with open(dst + ".meta", "w") as f:
                json.dump({"exit_code_by_key": meta, "hash_by_function_name": {}, "type_check_error_by_key": {},
                           "durations_by_key": {}, "estimated_durations_by_key": {}}, f, indent=4)
    fns = {}
    for src in sources():
        for name, _, _ in functions(open(src).read()):
            fns[f"{module(src)}.x_{name}"] = ["tests/test_core.py::test_all"]
    with open("mutants/mutmut-stats.json", "w") as f:
        json.dump({"tests_by_mangled_function_name": fns, "duration_by_test": {"tests/test_core.py::test_all": 0.001},
                   "stats_time": 0.1, "function_hashes": {}, "function_dependencies": {}}, f, indent=4)


def metas():
    for src in sources():
        p = os.path.join("mutants", src) + ".meta"
        if os.path.exists(p):
            yield p, json.load(open(p))


if args[0] == "run":
    write_copies()
    names = args[1:]
    known = {k for _, m in metas() for k in m["exit_code_by_key"]}
    picked = [n for n in names if n in known]
    if names and not picked:
        print("AssertionError: Filtered for specific mutants, but nothing matches\n\nFilter: " + repr(tuple(names)),
              file=sys.stderr)
        sys.exit(1)
    surv = os.environ.get("FAKE_SURVIVE")
    for p, m in metas():
        for k in m["exit_code_by_key"]:
            if not names or k in picked:
                m["exit_code_by_key"][k] = 0 if surv and re.search(surv, k) else 1
                if os.environ.get("FAKE_RAN"):
                    with open(os.environ["FAKE_RAN"], "a") as f:
                        f.write(k + "\n")
        with open(p, "w") as f:
            json.dump(m, f, indent=4)
    print("Running mutation testing")
    sys.exit(0)

if args[0] == "results":
    for _, m in metas():
        for k, v in m["exit_code_by_key"].items():
            print(f"    {k}: {STATUS.get(v, 'suspicious')}")
    sys.exit(0)

if args[0] == "apply":
    name = args[1]
    mod, fn = name.rsplit(".", 1)
    for src in sources():
        if module(src) != mod:
            continue
        func = fn.split("__mutmut_")[0][2:]
        k = int(fn.rsplit("_", 1)[1])
        text = open(src).read()
        for fname, params, body in functions(text):
            if fname == func:
                new = mutants_of(body)[k - 1]
                text = text.replace(f"def {fname}({params}):\n" + "\n".join(body),
                                    f"def {fname}({params}):\n" + "\n".join(new), 1)
        with open(src, "w") as f:
            f.write(text)
    sys.exit(0)
