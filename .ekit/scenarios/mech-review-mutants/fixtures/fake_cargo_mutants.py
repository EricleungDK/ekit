#!/usr/bin/env python3
"""Fake cargo-mutants 27.1.0 (argv[0] replaced via MECH_TEST_STUB). Not a scenario.

Answers the way the real tool does, from a listing file (same JSON as `cargo mutants --list --json`):
  mutants --version
  mutants --list --json [...]        prints FAKE_LIST (FAKE_SHUFFLE=<seed> shuffles it; FAKE_LIST_RC=<rc> fails it)
  mutants ... --output DIR [...]     runs the mutants named by `--re` (any match), else `--shard k/n` round-robin,
                                     else all; writes DIR/mutants.out/{mutants.json,outcomes.json,*.txt}
Env:
  FAKE_MISS=<regex>     mutant names that survive (MissedMutant); the rest are caught
  FAKE_EXTRA=<regex>    also run listed mutants matching it (what an `examine_re` in .cargo/mutants.toml does)
  FAKE_HANG_AFTER=<n>   write the first n outcomes (end_time null), then hang until killed
  FAKE_RAN=<file>       append each mutant name actually run, one per line
  FAKE_ARGV=<file>      append the argv, one line per call
  FAKE_BL_BUILD / FAKE_BL_TEST   baseline seconds written into outcomes.json (default 1 / 1)
A run with `--build-timeout 0` is the baseline-only run: Baseline Success, its one mutant a Timeout, exit 3.
"""
import json
import os
import random
import re
import sys
import time

args = sys.argv[1:]
if args[:2] == ["mutants", "--version"]:
    print("cargo-mutants 27.1.0")
    sys.exit(0)


def opt(name):
    vals = []
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            vals.append(args[i + 1])
        elif a.startswith(name + "="):
            vals.append(a.split("=", 1)[1])
    return vals


if os.environ.get("FAKE_ARGV"):
    with open(os.environ["FAKE_ARGV"], "a") as f:
        f.write(" ".join(args) + "\n")

with open(os.environ["FAKE_LIST"]) as f:
    listing = json.load(f)
if os.environ.get("FAKE_SHUFFLE"):
    random.Random(os.environ["FAKE_SHUFFLE"]).shuffle(listing)

if "--list" in args:
    rc = int(os.environ.get("FAKE_LIST_RC", "0") or 0)
    if rc:
        print("error: failed to parse Cargo.toml", file=sys.stderr)
        sys.exit(rc)
    print(json.dumps(listing, indent=2))
    sys.exit(0)

res = opt("--re")
shard = opt("--shard")
if res:
    sel = [m for m in listing if any(re.search(r, m["name"]) for r in res)]
elif shard:
    k, n = (int(x) for x in shard[-1].split("/"))
    sel = listing[k::n]
else:
    sel = list(listing)
extra = os.environ.get("FAKE_EXTRA")
if extra:
    sel += [m for m in listing if re.search(extra, m["name"]) and m not in sel]

out = opt("--output") or opt("-o")
mdir = os.path.join(out[-1] if out else ".", "mutants.out")
os.makedirs(os.path.join(mdir, "log"), exist_ok=True)
miss = os.environ.get("FAKE_MISS")
skip_baseline = "skip" in opt("--baseline")
baseline_only = "0" in opt("--build-timeout")


def phase(p, d, st="Success"):
    return {"phase": p, "duration": d, "process_status": st, "argv": ["cargo", "test"]}


def mutant(m):
    return {k: m[k] for k in ("name", "package", "file", "function", "span", "replacement", "genre") if k in m}


outcomes = []
if not skip_baseline:
    outcomes.append({"scenario": "Baseline", "summary": "Success", "log_path": "log/baseline.log", "diff_path": None,
                     "phase_results": [phase("Build", float(os.environ.get("FAKE_BL_BUILD", "1"))),
                                       phase("Test", float(os.environ.get("FAKE_BL_TEST", "1")))]})
with open(os.path.join(mdir, "log", "baseline.log"), "w") as f:
    f.write("fake baseline ok\n")
if baseline_only:
    sel = sel[:1]
with open(os.path.join(mdir, "mutants.json"), "w") as f:
    json.dump(sel, f)
hang = os.environ.get("FAKE_HANG_AFTER")
run = sel[: int(hang)] if hang else sel
lists = {"caught": [], "missed": [], "timeout": [], "unviable": []}
for m in run:
    if baseline_only:
        summary, phases, key = "Timeout", [phase("Build", 0.001, "Timeout")], "timeout"
    elif miss and re.search(miss, m["name"]):
        summary, phases, key = "MissedMutant", [phase("Build", 0.5), phase("Test", 0.5)], "missed"
    else:
        summary, phases, key = "CaughtMutant", [phase("Build", 0.5), phase("Test", 0.5, {"Failure": 101})], "caught"
    outcomes.append({"scenario": {"Mutant": mutant(m)}, "summary": summary, "log_path": "log/x.log",
                     "diff_path": "diff/x.diff", "phase_results": phases})
    lists[key].append(m["name"])
    if os.environ.get("FAKE_RAN"):
        with open(os.environ["FAKE_RAN"], "a") as f:
            f.write(m["name"] + "\n")
doc = {"outcomes": outcomes, "total_mutants": len(sel), "missed": len(lists["missed"]), "caught": len(lists["caught"]),
       "timeout": len(lists["timeout"]), "unviable": 0, "success": 0, "start_time": "2026-11-19T00:00:00Z",
       "end_time": None if hang else "2026-11-19T00:00:05Z", "cargo_mutants_version": "27.1.0"}
with open(os.path.join(mdir, "outcomes.json"), "w") as f:
    json.dump(doc, f)
for k, v in lists.items():
    with open(os.path.join(mdir, k + ".txt"), "w") as f:
        f.write("".join(n + "\n" for n in v))
if hang:
    time.sleep(600)
if baseline_only:
    sys.exit(3)
sys.exit(2 if lists["missed"] else 0)
