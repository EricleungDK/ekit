#!/usr/bin/env python3
"""Write a cargo-mutants `--list --json` listing for src/lib.rs: gen_list.py <groups> > list.json. Not a scenario.

Group i is function f<i> on line i+1 with six mutants, named as cargo-mutants 27.1.0 names them:
  col 5  FnValue        replace f<i> -> bool with true    (return)
  col 7  BinaryOperator replace > with == in f<i>         (branch condition)
  col 9  BinaryOperator replace + with - in f<i>          (arithmetic)
  col 11 MatchArm       delete match arm in f<i>          (rest)
  col 13 UnaryOperator  delete ! in f<i>                  (branch condition)
  col 15 MatchArmGuard  replace match guard with true in f<i>  (branch condition)
"""
import json
import sys

KINDS = [
    (5, "FnValue", "replace f{i} -> bool with true", "true"),
    (7, "BinaryOperator", "replace > with == in f{i}", "=="),
    (9, "BinaryOperator", "replace + with - in f{i}", "-"),
    (11, "MatchArm", "delete match arm in f{i}", ""),
    (13, "UnaryOperator", "delete ! in f{i}", ""),
    (15, "MatchArmGuard", "replace match guard with true in f{i}", "true"),
]
out = []
for i in range(int(sys.argv[1])):
    line = i + 1
    for col, genre, text, repl in KINDS:
        out.append({
            "diff": "",
            "file": "src/lib.rs",
            "function": {"function_name": f"f{i}", "return_type": "-> bool",
                         "span": {"start": {"line": line, "column": 1}, "end": {"line": line, "column": 60}}},
            "genre": genre,
            "name": f"src/lib.rs:{line}:{col}: " + text.format(i=i),
            "package": "x",
            "replacement": repl,
            "span": {"start": {"line": line, "column": col}, "end": {"line": line, "column": col + 1}},
        })
json.dump(out, sys.stdout, indent=2)
