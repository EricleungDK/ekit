#!/bin/bash
# Structural test of the mech-review reusable workflow and ekit's self caller.
# Stdlib line-based parse (no PyYAML): top-level blocks, child keys, scalar values.
source "$(dirname "$0")/lib.sh"
python3 -I - "$ROOT" <<'PY'
import json
import os
import re
import sys
import tempfile

ROOT = sys.argv[1]
FAILS = 0


def check(name, cond, detail=""):
    global FAILS
    if cond:
        print(f"  ok   {name}")
    else:
        FAILS += 1
        print(f"  FAIL {name}")
        if detail:
            print(f"       {detail}")


def read(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read().splitlines()


def indent(line):
    return len(line) - len(line.lstrip(" "))


def meaningful(line):
    s = line.strip()
    return bool(s) and not s.startswith("#")


def block(lines, key, at=None):
    """Raw lines under the first mapping key `key` (optionally at indent `at`). None if absent."""
    if lines is None:
        return None
    for n, line in enumerate(lines):
        if meaningful(line) and line.strip().startswith(key + ":") and (at is None or indent(line) == at):
            base = indent(line)
            out = []
            for later in lines[n + 1:]:
                if meaningful(later) and indent(later) <= base:
                    break
                out.append(later)
            return out
    return None


def child_lines(blk):
    lines = [l for l in (blk or []) if meaningful(l)]
    if not lines:
        return []
    base = min(indent(l) for l in lines)
    return [l for l in lines if indent(l) == base]


def child_keys(blk):
    return {l.strip().split(":")[0] for l in child_lines(blk) if not l.strip().startswith("-")}


def value(blk, key):
    for l in child_lines(blk):
        if l.strip().startswith(key + ":"):
            return l.strip()[len(key) + 1:].strip().strip("'\"")
    return None


def text(lines):
    return "\n".join(lines or [])


# ---- reusable workflow ----
RW = ".github/workflows/mech-review.yml"
W = read(RW)
check("reusable: file exists", W is not None, RW)
W = W or []

on = block(W, "on", 0) or []
check("reusable: on is workflow_call only", child_keys(on) == {"workflow_call"}, str(child_keys(on)))
wc = block(on, "workflow_call") or []
inputs = block(wc, "inputs") or []
want_inputs = {"stack", "test-paths", "protected-paths", "agent-branch-prefix", "mutation-budget", "extra-apt-packages",
               "project-dir", "setup-command", "mutant-timeout", "rust-toolchain", "max-mutants"}
check("reusable: exactly the 11 inputs", child_keys(inputs) == want_inputs, str(sorted(child_keys(inputs))))
check("reusable: max-mutants defaults to 40 (#26)", value(block(inputs, "max-mutants") or [], "default") == "40",
      str(block(inputs, "max-mutants")))
check("reusable: stack defaults to auto", value(block(inputs, "stack") or [], "default") == "auto")
check("reusable: mutant-timeout defaults to empty (auto: no --timeout, baseline unlimited)",
      value(block(inputs, "mutant-timeout") or [], "default") == "", str(block(inputs, "mutant-timeout")))
check("reusable: rust-toolchain defaults to stable", value(block(inputs, "rust-toolchain") or [], "default") == "stable",
      str(block(inputs, "rust-toolchain")))

perm = block(W, "permissions", 0) or []
perm_map = {k: value(perm, k) for k in child_keys(perm)}
check("reusable: top permissions exactly contents read + pull-requests write",
      perm_map == {"contents": "read", "pull-requests": "write"}, str(perm_map))
check("reusable: no pull_request_target", "pull_request_target" not in text(W))

jobs = block(W, "jobs", 0) or []
job_perm_lines = [n for n, l in enumerate(W) if re.match(r"\s+permissions:", l)]
red_has_perm = any(l.strip() == "permissions:" for l in (block(jobs, "red-first") or []))
mut_job = block(jobs, "mutants") or []
mut_has_perm = any(l.strip() == "permissions:" for l in mut_job)
base_has_perm = any(l.strip() == "permissions:" for l in (block(jobs, "baseline") or []))
check("reusable: job-level permissions only on red-first, baseline and mutants (PR code jobs; guard, plan, report inherit top-level)",
      red_has_perm and mut_has_perm and base_has_perm and len(job_perm_lines) == 3, f"job-level permissions lines: {job_perm_lines}")
check("reusable: jobs are exactly stack + guard + red-first + report + plan + baseline + shards + mutants (#46, #17)",
      child_keys(jobs) == {"stack", "guard", "red-first", "report", "plan", "baseline", "shards", "mutants"},
      str(child_keys(jobs)))
guard = block(jobs, "guard") or []
red = block(jobs, "red-first") or []
report = block(jobs, "report") or []

needs = (value(report, "needs") or "").strip("[]")
check("reusable: report needs guard", "guard" in re.split(r"[\s,]+", needs), f"needs={needs!r}")
check("reusable: report needs red-first", "red-first" in re.split(r"[\s,]+", needs), f"needs={needs!r}")
check("reusable: report runs even if guard fails", "always()" in (value(report, "if") or ""),
      f"if={value(report, 'if')!r}")

gt = text(guard)
check("guard: checks out ekit at job.workflow_sha",
      re.search(r"ref:\s*\$\{\{\s*job\.workflow_sha\s*\}\}", gt) is not None)
check("guard: ekit repo from job.workflow_repository", "job.workflow_repository" in gt)
check("guard: no language toolchain (no setup-*, toolchain, cargo, rustup)",
      re.search(r"setup-|toolchain|cargo|rustup", gt) is None)
check("guard: runs mech-review.py r2", "mech-review.py" in gt and " r2" in gt)
check("guard: uploads the JSON artifact", "upload-artifact" in gt)
check("guard: artifact overwrites on re-run", re.search(r"overwrite:\s*true", gt) is not None)
check("report: downloads the JSON artifact", "download-artifact" in text(report))
check("report: posts via mech-comment.py", "mech-comment.py" in text(report))
check("report: downloads the guard, drift, red-first, baseline and mutants artifacts (#46, #56), and every stack's (#17)",
      text(report).count("download-artifact@v4") == 6 and "mech-review-red-json" in text(report)
      and "mech-review-baseline-json" in text(report) and "mech-review-drift-json" in text(report), text(report))
check("report: named envelopes, guard as r2 and red-first as red",
      "--envelope r2=" in text(report) and "--envelope red=" in text(report), text(report))

rt = text(red)
check("red-first: checks out ekit at job.workflow_sha",
      re.search(r"ref:\s*\$\{\{\s*job\.workflow_sha\s*\}\}", rt) is not None)
check("red-first: ekit repo from job.workflow_repository", "job.workflow_repository" in rt)
check("red-first: caller checkout with full history (base..head needs it)",
      re.search(r"fetch-depth:\s*0", rt) is not None)
check("red-first: runs mech-review.py red", "mech-review.py" in rt and " red" in rt)
check("red-first: head branch from github.head_ref", "github.head_ref" in rt)
check("red-first: agent prefix from the agent-branch-prefix input", "inputs.agent-branch-prefix" in rt)
check("red-first: one --agent-prefix per line of the input", 'args+=(--agent-prefix "$g")' in rt and '<<< "$AGENT_PREFIX"' in rt)
_pref = " ".join(block(inputs, "agent-branch-prefix") or [])
check("inputs: agent-branch-prefix defaults to the harness prefixes",
      all(p in _pref for p in ("agent/", "claude/", "codex/", "copilot/", "cursor/")), _pref)
check("red-first: toolchain set up for the rust stack", "rust-toolchain" in rt and "matrix.stack == 'rust'" in rt)
# the step is a list item: its lines run from "- name: Rust toolchain" to the next "- name:"
_i = next((n for n, l in enumerate(red) if l.strip() == "- name: Rust toolchain"), None)
tc = []
if _i is not None:
    for l in red[_i + 1:]:
        if l.strip().startswith("- name:"):
            break
        tc.append(l)
tc = [l.strip() for l in tc]
uses_line = next((l.split("uses:", 1)[1].split("#")[0].strip() for l in tc if l.startswith("uses:")), "")
check("red-first: rust-toolchain pinned to a full 40-hex commit SHA",
      re.fullmatch(r"dtolnay/rust-toolchain@[0-9a-f]{40}", uses_line) is not None, uses_line)
check("red-first: rust-toolchain passes toolchain from the rust-toolchain input (required when pinned by SHA)",
      any(l == "toolchain: ${{ inputs.rust-toolchain }}" for l in tc), str(tc))
check("red-first: honours extra-apt-packages", "inputs.extra-apt-packages" in rt and "apt-get" in rt)
check("red-first: uploads its JSON artifact", "mech-review-red-json" in rt and "upload-artifact" in rt)
red_perm = block(red, "permissions") or []
check("red-first: job-level permissions exactly contents read",
      {k: value(red_perm, k) for k in child_keys(red_perm)} == {"contents": "read"},
      str({k: value(red_perm, k) for k in child_keys(red_perm)}))
check("red-first: no pull_request_target", "pull_request_target" not in rt)
check("inputs: agent-branch-prefix is used now, not UNUSED",
      "UNUSED" not in " ".join(block(inputs, "agent-branch-prefix") or []), str(block(inputs, "agent-branch-prefix")))
check("inputs: extra-apt-packages is used now, not UNUSED",
      "UNUSED" not in " ".join(block(inputs, "extra-apt-packages") or []), str(block(inputs, "extra-apt-packages")))

# ---- R3 mutants: plan, shard matrix, merge ----
pl = block(jobs, "plan") or []
mu = block(jobs, "mutants") or []
pt = text(pl)
mt = text(mu)
check("plan: job present", bool(pl))
check("plan: runs mech-review.py plan", "mech-review.py" in pt and " plan" in pt, pt)
check("plan: caller checkout at PR head with full history",
      "github.event.pull_request.head.sha" in pt and re.search(r"fetch-depth:\s*0", pt) is not None)
check("plan: ekit checkout at job.workflow_sha", re.search(r"ref:\s*\$\{\{\s*job\.workflow_sha\s*\}\}", pt) is not None)
check("plan: exposes the run output only (#46: the shard count comes from baseline)",
      re.search(rf"^\s+run:\s*\$\{{\{{\s*steps\.\w+\.outputs\.run\s*\}}\}}", pt, re.M) is not None
      and "count:" not in pt and "shards:" not in pt, pt)
check("plan: no language toolchain", re.search(r"setup-|toolchain|cargo|rustup", pt) is None)
check("plan: no --shards (no mutant count in git)", "--shards" not in pt, pt)

bl = block(jobs, "baseline") or []
bt = text(bl)
check("baseline: job present", bool(bl))
check("baseline: needs stack and plan", (value(bl, "needs") or "").strip("[]") == "stack, plan", str(value(bl, "needs")))
check("baseline: runs only when the plan says so", "needs.plan.outputs.run == 'true'" in (value(bl, "if") or ""),
      str(value(bl, "if")))
check("baseline: job-level permissions exactly contents read (it runs PR code for rust)",
      {k: value(block(bl, "permissions") or [], k) for k in child_keys(block(bl, "permissions") or [])} == {"contents": "read"},
      str(block(bl, "permissions")))
check("baseline: caller checkout at PR head with full history",
      "github.event.pull_request.head.sha" in bt and re.search(r"fetch-depth:\s*0", bt) is not None)
check("baseline: ekit checkout at job.workflow_sha", re.search(r"ref:\s*\$\{\{\s*job\.workflow_sha\s*\}\}", bt) is not None)
check("baseline: runs mech-review.py baseline", "mech-review.py" in bt and " baseline" in bt, bt)
check("baseline: shard count from the shards setting (4)", "MUTATION_SHARDS" in bt or "--shards" in bt, bt)
check("baseline: budget from the mutation-budget input", "inputs.mutation-budget" in bt and "--mutation-budget" in bt, bt)
check("baseline: the cap from the max-mutants input, via env (#26)",
      "MAX_MUTANTS: ${{ inputs.max-mutants }}" in bt and '--max-mutants "$MAX_MUTANTS"' in bt, bt)
check("baseline: does not read mutant-timeout (a set value never caps the baseline)", "mutant-timeout" not in bt, bt)
check("baseline: outputs run, count, shards and timeout",
      all(re.search(rf"^\s+{k}:\s*\$\{{\{{\s*steps\.\w+\.outputs\.{k}\s*\}}\}}", bt, re.M)
          for k in ("run", "count", "shards", "timeout")), bt)
check("baseline: rust toolchain pinned to a full SHA, for the rust stack",
      "dtolnay/rust-toolchain@" in bt and "matrix.stack == 'rust'" in bt, bt)
check("baseline: cargo-mutants pinned to 27.1.0, install failure is not a stop", "cargo-mutants@27.1.0" in bt
      and "continue-on-error: true" in bt, bt)
check("baseline: uploads its JSON artifact", "mech-review-baseline-json" in bt and "upload-artifact" in bt, bt)
check("baseline: no pull_request_target", "pull_request_target" not in bt)

check("mutants: needs plan and baseline", {"plan", "baseline"} <= set(re.split(r"[\s,\[\]]+", (value(mu, "needs") or ""))),
      str(value(mu, "needs")))
check("mutants: runs only when the baseline says shards run (#46)", "needs.baseline.outputs.run == 'true'" in (value(mu, "if") or ""),
      str(value(mu, "if")))
strategy = block(mu, "strategy") or []
check("mutants: shard matrix from the shards job (several stacks), else the baseline's output (#17)",
      "include: ${{ fromJSON(needs.shards.outputs.include || needs.baseline.outputs.include) }}" in text(strategy), text(strategy))
check("mutants: fail-fast off (one shard's failure does not cancel the others)", value(strategy, "fail-fast") == "false",
      str(value(strategy, "fail-fast")))
mperm = block(mu, "permissions") or []
check("mutants: job-level permissions exactly contents read (runs PR code)",
      {k: value(mperm, k) for k in child_keys(mperm)} == {"contents": "read"}, str({k: value(mperm, k) for k in child_keys(mperm)}))
check("mutants: no pull_request_target", "pull_request_target" not in mt)
check("mutants: caller checkout at PR head with full history",
      "github.event.pull_request.head.sha" in mt and re.search(r"fetch-depth:\s*0", mt) is not None)
check("mutants: ekit checkout at job.workflow_sha", re.search(r"ref:\s*\$\{\{\s*job\.workflow_sha\s*\}\}", mt) is not None)


def step(lines, name):
    """Lines of the step `- name: <name>` (to the next `- name:`), stripped. [] if absent."""
    start = next((n for n, l in enumerate(lines) if l.strip() == f"- name: {name}" or l.strip().startswith(f"- name: {name} ")), None)
    if start is None:
        return []
    out = []
    for l in lines[start + 1:]:
        if l.strip().startswith("- name:"):
            break
        out.append(l.strip())
    return out

py_bl = text(step(bl, "Python toolchain"))
check("baseline: python venv with pytest and mutmut pinned, for the python stack (#64)",
      py_bl.startswith("if: matrix.stack == 'python'") and '"pytest==9.2.0" "mutmut==3.8.1"' in py_bl
      and 'echo "$RUNNER_TEMP/py-venv/bin" >> "$GITHUB_PATH"' in py_bl, py_bl)
bl_names = [l.strip()[len("- name: "):] for l in bl if l.strip().startswith("- name: ")]
check("baseline: the python venv after the checkouts, before the baseline runs (#64)",
      "Python toolchain" in bl_names and bl_names.index("Python toolchain") == 2
      and bl_names.index("Python toolchain") < bl_names.index("R3 baseline (once; shard count, derived timeout)"), str(bl_names))
RUST_OR_PY = "(matrix.stack == 'rust' || matrix.stack == 'python')"
check("baseline: extra apt packages and setup command run for rust and python (#64)",
      RUST_OR_PY in text(step(bl, "extra apt packages")) and RUST_OR_PY in text(step(bl, "setup command")),
      text(step(bl, "extra apt packages")) + " | " + text(step(bl, "setup command")))


tcs = step(mu, "Rust toolchain")
tc_uses = next((l.split("uses:", 1)[1].split("#")[0].strip() for l in tcs if l.startswith("uses:")), "")
check("mutants: rust-toolchain pinned to a full 40-hex commit SHA",
      re.fullmatch(r"dtolnay/rust-toolchain@[0-9a-f]{40}", tc_uses) is not None, tc_uses)
check("mutants: rust-toolchain passes toolchain from the rust-toolchain input",
      "toolchain: ${{ inputs.rust-toolchain }}" in tcs, str(tcs))

ins = step(mu, "install cargo-mutants (pinned)")
ins_uses = next((l.split("uses:", 1)[1].split("#")[0].strip() for l in ins if l.startswith("uses:")), "")
check("mutants: cargo-mutants installed by a SHA-pinned action",
      re.fullmatch(r"taiki-e/install-action@[0-9a-f]{40}", ins_uses) is not None, ins_uses)
check("mutants: cargo-mutants pinned to 27.1.0", any(l == "tool: cargo-mutants@27.1.0" for l in ins), str(ins))
check("mutants: install failure does not stop the run (engine reports n/a env)",
      "continue-on-error: true" in ins, str(ins))

run_step = step(mu, "R3 mutation on the diff (shard)")
rs = "\n".join(run_step)
check("mutants: runs mech-review.py mutants", "mech-review.py" in rs and " mutants" in rs, rs)
check("mutants: shard flag from the matrix and its stack's shard count (#17: the count rides in the matrix)",
      "SHARD: ${{ matrix.shard }}" in rs and "SHARD_COUNT: ${{ matrix.count }}" in rs, rs)
check("mutants: budget from the mutation-budget input", "inputs.mutation-budget" in mt and "--mutation-budget" in rs, rs)
check("mutants: mutant-timeout from the input, else the baseline's derived one (#46), via env, passed only when set",
      "MUTANT_TIMEOUT: ${{ inputs.mutant-timeout || matrix.timeout }}" in mt
      and '--mutant-timeout "$MUTANT_TIMEOUT"' in rs and 'if [ -n "$MUTANT_TIMEOUT" ]' in rs, rs)
check("mutants: the cap from the max-mutants input, via env (#26)",
      "MAX_MUTANTS: ${{ inputs.max-mutants }}" in rs and '--max-mutants "$MAX_MUTANTS"' in rs, rs)
check("mutants: rc above 1 is no result (crash surfaces at report)", "rc -gt 1" in rs or "-gt 1" in rs, rs)
up = step(mu, "upload mutants result")
check("mutants: uploads its JSON artifact per stack and shard", "mech-review-mutants${{ matrix.key }}-${{ matrix.shard }}" in "\n".join(up)
      and "upload-artifact" in mt and any(l == "if: always()" for l in up), str(up))

# ---- R0's runtime half (#21): red-first runs its run part, mutants shard 0 its R3 control, each skipped by a
# passed fingerprint the workflow cache remembers. A miss only re-runs the proof; the engine writes the pass file
# only on a pass and reads it only when it names the fingerprint it computed itself, so a hit never turns fail to pass
R0_DIR = '"$HOME/.cache/ekit-r0"'
_at = next(i for i, l in enumerate(red) if l.strip() == "- name: R1 red-first, R4 determinism")
red_run_at = next(i for i in range(_at, len(red)) if red[i].strip().startswith("STACK:"))  # the run step's STACK line


def stack_env(lines):
    """{STACK, PROJECT_DIR: expression} of a step's env lines."""
    return {l.split(":", 1)[0]: l.split(":", 1)[1].strip() for l in lines if l.startswith(("STACK:", "PROJECT_DIR:"))}

for job, lines, part, shard0 in (("red-first", red, "run", False), ("mutants", mu, "r3", True)):
    fp = step(lines, f"R0 runtime fingerprint ({part})")
    cache = step(lines, f"R0 runtime cache ({part})")
    names = [l.strip()[len("- name: "):] for l in lines if l.strip().startswith("- name: ")]
    run_name = "R1 red-first, R4 determinism" if job == "red-first" else "R3 mutation on the diff (shard)"
    run = text(step(lines, run_name))
    check(f"{job}: the R0 {part} fingerprint step prints the cache key (r0 --fingerprint {part}), never stops the job",
          "id: r0fp" in fp and f"--fingerprint {part}" in text(fp) and "|| exit 0" in text(fp)
          and 'key={key}' in text(fp), text(fp))
    check(f"{job}: the R0 {part} cache is actions/cache, keyed by the fingerprint step, at the dir the engine gets",
          "uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830 # v4.3.0" in cache and "key: ${{ steps.r0fp.outputs.key }}" in cache
          and "path: ~/.cache/ekit-r0" in cache and any(l.startswith("if:") and "steps.r0fp.outputs.key != ''" in l
                                                        for l in cache), str(cache))
    clear = step(lines, f"R0 runtime cache dir cleared ({part})")
    check(f"{job}: fingerprint, cleared dir, cache, then the run that passes --r0 (review B1: nothing a setup command "
          "or install script planted survives a miss)",
          f"R0 runtime cache dir cleared ({part})" in names
          and names.index(f"R0 runtime fingerprint ({part})") < names.index(f"R0 runtime cache dir cleared ({part})")
          == names.index(f"R0 runtime cache ({part})") - 1 < names.index(run_name)
          and 'rm -rf "$HOME/.cache/ekit-r0"' in text(clear)
          and (not shard0 or any(l == "if: matrix.shard == 0" for l in clear)), str(names) + text(clear))
    check(f"{job}: the run passes the cache dir as --r0" + (" on shard 0 only" if shard0 else ""),
          f"--r0 {R0_DIR}" in run and (not shard0 or 'if [ "$SHARD" = "0" ]' in run), run)
    # review S3: the fingerprint takes the stack and project dir from the same expressions as the run (#74 moves the
    # run to matrix legs: a fingerprint step left on needs.stack.* would key every leg's cache wrongly)
    check(f"{job}: the R0 {part} fingerprint reads STACK and PROJECT_DIR as the run step does",
          set(stack_env(fp)) == {"STACK", "PROJECT_DIR"} and stack_env(fp) == stack_env(step(lines, run_name)),
          f"{stack_env(fp)} vs {stack_env(step(lines, run_name))}")
    if shard0:
        check("mutants: the R0 r3 fingerprint and cache steps run on shard 0 only",
              all(any(l == "if: matrix.shard == 0" or (l.startswith("if:") and "matrix.shard == 0" in l) for l in st)
                  for st in (fp, cache)), str(fp) + str(cache))
        check("mutants: the r3 fingerprint probes the tool the shard runs (ts: the pinned Stryker)",
              '--mutants-cmd "$STRYKER_BIN"' in text(fp), text(fp))

# live: a run step moved to matrix legs while its fingerprint step is not fails that check
_moved = [l.split("STACK:")[0] + "STACK: ${{ matrix.moved }}" if i == red_run_at else l for i, l in enumerate(red)]
check("R0 fingerprint expressions check is live: a run step's STACK that moved alone is caught",
      _moved != red and stack_env(step(_moved, "R0 runtime fingerprint (run)"))
      != stack_env(step(_moved, "R1 red-first, R4 determinism")))

check("mutation-budget: used by the mutants job, not UNUSED",
      "UNUSED" not in " ".join(block(inputs, "mutation-budget") or []) and value(block(inputs, "mutation-budget") or [], "default") == "10",
      str(block(inputs, "mutation-budget")))

check("report: needs plan, baseline and mutants",
      {"plan", "baseline", "mutants"} <= set(re.split(r"[\s,\[\]]+", needs)), f"needs={needs!r}")
check("report: downloads the mutants shard artifacts (pattern)", "mech-review-mutants-*" in text(report), text(report))
check("report: merges the shards with the merge subcommand", "mech-review.py" in text(report) and " merge" in text(report), text(report))
check("report: mutants envelope only when the plan ran it, a crash is still reported",
      "mutants=" in text(report) and "PLAN_RESULT" in text(report) and "needs.plan.result" in text(report), text(report))

check("all third-party actions pinned to a full SHA (actions/* are GitHub's own, tag-pinned)",
      all(re.fullmatch(r"[0-9a-f]{40}", l.split("uses:", 1)[1].split("#")[0].strip().split("@", 1)[1])
          for l in W if l.strip().startswith("uses:") and not l.split("uses:", 1)[1].strip().startswith("actions/")),
      str([l for l in W if "uses:" in l]))

# ---- project-dir and setup-command: a crate in a subdirectory, a setup step (sysctl) before the tests ----
check("project-dir: default is the repo root", value(block(inputs, "project-dir") or [], "default") == ".",
      str(block(inputs, "project-dir")))
check("setup-command: default is empty", value(block(inputs, "setup-command") or [], "default") == "",
      str(block(inputs, "setup-command")))
docs_text = text(read("docs/mech-review-ci.md"))
check("docs: an Inputs row for every input", all(f"| `{k}` |" in docs_text for k in want_inputs),
      str(sorted(k for k in want_inputs if f"| `{k}` |" not in docs_text)))
check("project-dir and setup-command: never interpolated into a run: line",
      all(("inputs.setup-command" not in l or "if:" in l or "SETUP_COMMAND:" in l)
          and ("inputs.project-dir" not in l or "PROJECT_DIR:" in l) for l in W),
      str([l for l in W if "inputs.setup-command" in l or "inputs.project-dir" in l]))
# ---- stack: auto (the default) settled once, git only; later jobs read it through env or if:, never a run: line ----
st = block(jobs, "stack") or []
stt = text(st)
check("stack: runs mech-review.py resolve with the stack and project-dir inputs via env",
      "mech-review.py\" resolve" in stt and "STACK: ${{ inputs.stack }}" in stt
      and "PROJECT_DIR: ${{ inputs.project-dir }}" in stt and '--project-dir "$PROJECT_DIR"' in stt, stt)
check("stack: no language toolchain, no PR code (git only)", re.search(r"setup-|toolchain|cargo|rustup|\bnpm\b|\bpip\b", stt) is None, stt)
check("stack: caller checkout for every stack (a plan's target-os reaches explicit-stack callers, #58)",
      "inputs.stack == 'auto'" not in stt and "caller checkout (full history, PR head)" in stt, stt)
check("stack: exposes stack, project-dir, target-os, error and legs (#17) outputs",
      child_keys(block(st, "outputs")) == {"stack", "project-dir", "target-os", "error", "legs"}, str(block(st, "outputs")))
check("stack: target-os from resolve's target_os",
      "target-os: ${{ steps.resolve.outputs.target-os }}" in stt and '"target-os": r.get("target_os") or ""' in stt, stt)
RUNS_ON_OS = ("runs-on: ${{ fromJSON('{\"linux\":\"ubuntu-latest\",\"macos\":\"macos-latest\","
              "\"windows\":\"windows-latest\"}')[matrix.target-os] }}")
for job_name in ("red-first", "baseline", "mutants"):
    check(f"{job_name}: runs on the target OS (#58)", value(block(jobs, job_name) or [], "runs-on") == RUNS_ON_OS[len("runs-on: "):],
          str(value(block(jobs, job_name) or [], "runs-on")))
for job_name in ("stack", "guard", "plan", "report"):
    check(f"{job_name}: stays on ubuntu-latest (git only, #58)", value(block(jobs, job_name) or [], "runs-on") == "ubuntu-latest",
          str(value(block(jobs, job_name) or [], "runs-on")))
apt_ifs = [step(block(jobs, j) or [], "extra apt packages") for j in ("red-first", "baseline", "mutants")]
check("extra apt packages: Linux only (#58)", all(s and s[0].startswith("if: runner.os == 'Linux' && ") for s in apt_ifs),
      str([s[:1] for s in apt_ifs]))
g_names = [l.strip()[len("- name: "):] for l in (block(jobs, "guard") or []) if l.strip().startswith("- name: ")]
INSTALL = "install the declared parser (the base's adapter file, #27)"
check("guard: the drift step (D) right after the checkouts, then the parser install, before R2 guard (#56, #27)",
      g_names[2:6] == ["drift check (stack plan, D)", "upload drift result", INSTALL, "R2 guard"], str(g_names))
dt = text(step(block(jobs, "guard") or [], "drift check (stack plan, D)"))
check("guard: drift runs mech-review.py drift, no result stops the job",
      "mech-review.py\" drift" in dt and "[ -s mech-review-drift.json ] || rm -f mech-review-drift.json" in dt
      and 'exit "$(( rc > 0 ? rc : 2 ))"' in dt, dt)
check("report: the drift envelope only when its file is there (#56)",
      "if [ -f drift-result/mech-review-drift.json ]; then" in text(report)
      and "extra+=(--envelope drift=drift-result/mech-review-drift.json)" in text(report), text(report))
check("guard: R0's static half right after R2 guard, before the upload (#20)",
      g_names[5:8] == ["R2 guard", "R0 static half (adapter proof)", "upload result"], str(g_names))
r0t = text(step(block(jobs, "guard") or [], "R0 static half (adapter proof)"))
check("guard: R0 runs mech-review.py r0 on the settled stack and the test paths, git only",
      "mech-review.py\" r0 \"${args[@]}\" > mech-review-r0.json" in r0t and "STACK: ${{ matrix.stack }}" in r0t
      and "TEST_PATHS: ${{ inputs.test-paths }}" in r0t and "--test-cmd" not in r0t, r0t)
check("guard: an R0 usage or git error, or an empty result, leaves no result and stops the job",
      'if [ "$rc" -gt 1 ] || [ ! -s mech-review-r0.json ]; then' in r0t and "rm -f mech-review-r0.json" in r0t
      and 'exit "$(( rc > 0 ? rc : 2 ))"' in r0t, r0t)
gu = text(step(block(jobs, "guard") or [], "upload result"))
check("guard: the R0 result rides in the guard's artifact beside R2's, uploaded always",
      "if: always()" in gu and "name: mech-review-json" in gu and "mech-review.json" in gu and "mech-review-r0.json" in gu, gu)
check("report: always names the R0 result, so a missing one fails R0 with a CI entry (#20)",
      "--envelope r0=r2-result/mech-review-r0.json" in text(report), text(report))
check("stack: an error fails the job", "steps.resolve.outputs.error != ''" in stt and "exit 1" in stt, stt)
for step_name in ("R2 guard", "R0 static half (adapter proof)"):  # #17: the plan entry for the stack's own folder
    gs = text(step(block(jobs, "guard") or [], step_name))
    check(f"guard: {step_name} gets its leg's project-dir through env",
          "PROJECT_DIR: ${{ matrix.project-dir }}" in gs and '--project-dir "$PROJECT_DIR"' in gs, gs)


def stack_outputs(result):
    """run the stack job's output step (its python heredoc) on a resolve result: the outputs it writes."""
    import json
    import subprocess
    import tempfile
    import textwrap
    lines = st  # raw lines: the heredoc keeps its indentation
    start = next((i for i, l in enumerate(lines) if "<<'PY'" in l), None)
    if start is None:
        return None
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "PY")
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "stack.json"), "w") as f:
            json.dump(result, f)
        out = os.path.join(d, "out")
        r = subprocess.run([sys.executable, "-I", "-c", textwrap.dedent("\n".join(lines[start + 1:end])), out], cwd=d,
                           capture_output=True, text=True)
        if r.returncode:
            return r.stderr
        with open(out) as f:
            return dict(l.split("=", 1) for l in f.read().splitlines())


one = stack_outputs({"stack": "python", "project_dir": "api", "error": None, "target_os": "macos"})
ONE_LEG = [{"key": "", "label": "", "name": "python", "stack": "python", "project-dir": "api", "target-os": "macos",
            "drift": True}]
check("stack: one stack gives its outputs as before, and one leg with no key or label (names unchanged)",
      isinstance(one, dict) and {k: v for k, v in one.items() if k != "legs"}
      == {"stack": "python", "project-dir": "api", "error": "", "target-os": "macos"}
      and json.loads(one.get("legs", "null")) == ONE_LEG, str(one))
several = stack_outputs({"stack": None, "project_dir": ".", "error": None, "target_os": None, "stacks": [
    {"name": "api", "stack": "python", "project_dir": "api", "adapter": "python", "target_os": "linux"},
    {"name": "web", "stack": "ts", "project_dir": "web", "adapter": "ts", "target_os": "windows"}]})
check("stack: several stacks from the plan (#17) give one leg each: key and label by stack, drift on the first only",
      isinstance(several, dict) and {k: v for k, v in several.items() if k != "legs"}
      == {"stack": "", "project-dir": ".", "target-os": "", "error": ""}
      and json.loads(several.get("legs", "null")) == [
          {"key": "-0-api", "label": " [api]", "name": "api", "stack": "python", "project-dir": "api",
           "target-os": "linux", "drift": True},
          {"key": "-1-web", "label": " [web]", "name": "web", "stack": "ts", "project-dir": "web",
           "target-os": "windows", "drift": False}], str(several))
none = stack_outputs({"stack": None, "project_dir": ".", "error": "stack auto: no project found", "target_os": None})
check("stack: no stack gives no leg and the error", isinstance(none, dict) and none.get("legs") == "[]"
      and none.get("error") == "stack auto: no project found", str(none))
check("stack: inputs.stack and inputs.project-dir are read in the stack job only",
      "inputs.stack" not in text(W[W.index("  guard:"):]) and "inputs.project-dir" not in text(W[W.index("  guard:"):]))
for job_name in ("guard", "red-first", "plan", "baseline", "mutants", "report"):
    check(f"{job_name}: needs stack", "stack" in re.split(r"[\s,\[\]]+", value(block(jobs, job_name) or [], "needs") or ""),
          str(value(block(jobs, job_name) or [], "needs")))
check("stack outputs: only in env values or if: conditions, never interpolated into a run: line",
      all(re.match(r"\s*(-\s+)?(if:|[A-Z_]+:|\w[\w-]*: \$\{\{ steps\.resolve)", l) or l.strip() == RUNS_ON_OS
          or l.strip() == "include: ${{ fromJSON(needs.stack.outputs.legs) }}"  # the legs matrix (#17)
          for l in W if "needs.stack.outputs" in l
          or "steps.resolve.outputs" in l),
      str([l for l in W if "needs.stack.outputs" in l or "steps.resolve.outputs" in l]))
check("report: no stack posts the stack job's error as the reason",
      "STACK_ERROR: ${{ needs.stack.outputs.error }}" in text(report) and '--reason "${STACK_ERROR:-' in text(report),
      text(report))
check("report: mutants merge only when a stack was settled", "needs.stack.result == 'success'" in text(report), text(report))
for job_name, run_name in (("red-first", "R1 red-first, R4 determinism"), ("mutants", "R3 mutation on the diff (shard)")):
    jl = block(jobs, job_name) or []
    names = [l.strip()[len("- name: "):] for l in jl if l.strip().startswith("- name: ")]
    run_st = step(jl, run_name)
    check(f"{job_name}: passes --project-dir from the input via env",
          '--project-dir "$PROJECT_DIR"' in text(run_st) and "PROJECT_DIR: ${{ matrix.project-dir }}" in text(run_st),
          str(run_st))
    sc = step(jl, "setup command")
    check(f"{job_name}: setup-command step runs only when set", "if: inputs.setup-command != ''" in sc, str(sc))
    check(f"{job_name}: setup-command passed through env, run with bash, not interpolated",
          "SETUP_COMMAND: ${{ inputs.setup-command }}" in sc and "shell: bash" in sc
          and 'run: bash -c "$SETUP_COMMAND"' in sc and not any("${{" in l for l in sc if l.startswith("run:")), str(sc))
    order = [n for n in names if n in ("extra apt packages", "setup command", run_name)]
    check(f"{job_name}: setup-command after extra apt packages, before the tests",
          order == ["extra apt packages", "setup command", run_name], str(names))

# ---- #17: one set of checks per stack (a matrix over the stack job's legs), one report ----


def heredoc(lines, from_line=None, nth=0):
    """the python of a run: heredoc (<<'PY' ... PY) in lines, dedented: the nth one after the line holding from_line."""
    import textwrap
    start = 0 if from_line is None else next((i for i, l in enumerate(lines) if from_line in l), None)
    if start is None:
        return None
    marks = [i for i in range(start, len(lines)) if "<<'PY'" in lines[i]]
    if len(marks) <= nth:
        return None
    a = marks[nth]
    b = next(i for i in range(a + 1, len(lines)) if lines[i].strip() == "PY")
    return textwrap.dedent("\n".join(lines[a + 1:b]))


def run_py(code, cwd, env, *argv):
    import subprocess
    return subprocess.run([sys.executable, "-I", "-c", code or "raise SystemExit('no heredoc')", *argv], cwd=cwd,
                          env=dict(os.environ, **env), capture_output=True, text=True)


def outputs(path):
    with open(path) as f:
        return dict(l.split("=", 1) for l in f.read().splitlines())


LEG_API = {"key": "-0-api", "label": " [api]", "name": "api", "stack": "python", "project-dir": "api",
           "target-os": "linux", "drift": True}
LEG_WEB = {"key": "-1-web", "label": " [web]", "name": "web", "stack": "ts", "project-dir": "web",
           "target-os": "windows", "drift": False}
OLD_NAMES = {"guard": "mech-review guard (R2)", "red-first": "mech-review red-first (R1, R4)",
             "baseline": "mech-review baseline (R3, once)", "mutants": "mech-review mutants (R3 shard ${{ matrix.shard }})"}
for job_name, old in OLD_NAMES.items():
    jl = block(jobs, job_name) or []
    check(f"{job_name}: one leg per stack, its name the old one plus the leg's label (empty for one stack, #17)",
          value(jl, "name") == old + "${{ matrix.label }}", str(value(jl, "name")))
    stg = block(jl, "strategy") or []
    check(f"{job_name}: fail-fast off (one stack's crash never cancels another's)", value(stg, "fail-fast") == "false",
          text(stg))
for job_name, source in (("guard", "needs.stack.outputs.legs"), ("red-first", "needs.stack.outputs.legs"),
                         ("baseline", "needs.plan.outputs.legs")):
    stg = text(block(block(jobs, job_name) or [], "strategy") or [])
    check(f"{job_name}: the matrix is the legs ({source})", f"include: ${{{{ fromJSON({source}) }}}}" in stg, stg)
for job_name, art in (("guard", "mech-review-json"), ("red-first", "mech-review-red-json"),
                      ("baseline", "mech-review-baseline-json")):
    jt = text(block(jobs, job_name) or [])
    check(f"{job_name}: its artifact is named per stack (the leg's key, empty for one stack)",
          f"name: {art}${{{{ matrix.key }}}}" in jt, jt)
gj = block(jobs, "guard") or []
check("guard: the drift check (the repo's) runs in the first leg only, its artifact name unchanged",
      step(gj, "drift check (stack plan, D)")[1:2] == ["if: matrix.drift"]
      and "if: always() && matrix.drift" in step(gj, "upload drift result")
      and "name: mech-review-drift-json" in step(gj, "upload drift result"), str(step(gj, "upload drift result")))
check("no ${{ }} inside any run: line (matrix and stack values reach run: only through env)",
      not any(l.strip().startswith("run:") and "${{" in l and not re.fullmatch(r"run: \$\{\{ steps\.\w+\.outputs\.run \}\}", l.strip())
              for l in W), str([l for l in W if "run:" in l and "${{" in l]))
check("matrix values only in env, if:, name:, runs-on: and with: values, never a run: body",
      all(re.match(r"\s*(-\s+)?(if:|[A-Z_]+:|name:|runs-on:|include:)", l) for l in W if "matrix." in l and "${{" in l
          or l.strip().startswith("if:") and "matrix." in l), str([l for l in W if "matrix." in l]))

with tempfile.TemporaryDirectory() as d:  # the plan job: one plan per leg
    stub = os.path.join(d, "ekit", "scripts")
    os.makedirs(stub)
    os.makedirs(os.path.join(d, "caller"))
    with open(os.path.join(stub, "mech-review.py"), "w") as f:
        # each stack is planned in its own folder (its adapter file is found by it); a stack `mini` fails, as an
        # engine error (exit 2) would
        f.write("import json, sys\na = sys.argv\nstack, folder = a[a.index('--stack') + 1], a[a.index('--project-dir') + 1]\n"
                "if stack == 'mini':\n    sys.exit(2)\nprint(json.dumps({'run': stack == 'python' and folder == 'api'}))\n")
    out = os.path.join(d, "out")
    plan_py = heredoc(block(jobs, "plan") or [], "R3 plan")
    plan_env = {"GITHUB_WORKSPACE": d, "BASE_SHA": "b", "HEAD_SHA": "h", "TEST_PATHS": "tests/**\n"}
    r = run_py(plan_py, d, dict(plan_env, LEGS=json.dumps([LEG_API, LEG_WEB])), out)
    got = outputs(out) if r.returncode == 0 else r.stderr
    check("plan: one plan per stack in its project dir; run when any runs, the baseline's legs are those whose R3 runs (#17)",
          isinstance(got, dict) and got.get("run") == "true" and json.loads(got.get("legs", "null")) == [LEG_API]
          and json.loads(got.get("runs", "null")) == {"-0-api": True, "-1-web": False}, str(got))
    LEG_MINI = dict(LEG_WEB, key="-1-lib", name="lib", stack="mini", **{"project-dir": "lib"})
    r = run_py(plan_py, d, dict(plan_env, LEGS=json.dumps([LEG_API, LEG_MINI])), out + "2")
    got = outputs(out + "2") if r.returncode == 0 else r.stderr
    check("plan: a stack whose plan fails reads unknown (its R3 a CI entry); the other stacks keep theirs (review 1)",
          isinstance(got, dict) and got.get("run") == "true" and json.loads(got.get("legs", "null")) == [LEG_API]
          and json.loads(got.get("runs", "null")) == {"-0-api": True, "-1-lib": None}
          and "::error::" in r.stdout, str((got, r.stdout)))
    r = run_py(plan_py, d, dict(plan_env, LEGS=json.dumps([dict(LEG_MINI, key="", label="")])), out + "3")
    check("plan: no stack planned at all fails the job, as a failed plan did for one stack", r.returncode != 0,
          str((r.returncode, r.stdout)))
pl_out = child_keys(block(block(jobs, "plan") or [], "outputs"))
check("plan: outputs run, legs and runs", pl_out == {"run", "legs", "runs"}, str(pl_out))

with tempfile.TemporaryDirectory() as d:  # the baseline step's outputs: one stack's mutants matrix
    with open(os.path.join(d, "mech-review-baseline.json"), "w") as f:
        json.dump({"run": True, "count": 2, "timeout": 30}, f)
    out = os.path.join(d, "out")
    one_leg = dict(LEG_API, key="", label="")
    r = run_py(heredoc(bl, "R3 baseline (once"), d, {"LEG": json.dumps(one_leg)}, out)
    got = outputs(out) if r.returncode == 0 else r.stderr
    check("baseline: outputs as before, and include: the leg with each shard, its count and timeout",
          isinstance(got, dict) and {k: got[k] for k in ("run", "count", "shards", "timeout")}
          == {"run": "true", "count": "2", "shards": "[0, 1]", "timeout": "30"}
          and json.loads(got["include"]) == [dict(one_leg, shard=0, count=2, timeout="30"),
                                             dict(one_leg, shard=1, count=2, timeout="30")], str(got))
check("baseline: the leg reaches the step through env", "LEG: ${{ toJSON(matrix) }}" in bt, bt)

sh = block(jobs, "shards", 2) or []  # at the jobs' indent: baseline has a shards output
sht = text(sh)
check("shards: several stacks only, after every baseline leg, even when one failed",
      value(sh, "if") == "${{ !cancelled() && needs.stack.result == 'success' && needs.stack.outputs.stack == '' "
                         "&& needs.plan.outputs.run == 'true' }}" and value(sh, "needs") == "[stack, plan, baseline]",
      str((value(sh, "if"), value(sh, "needs"))))
check("shards: git and JSON only, on ubuntu, no checkout of PR code",
      value(sh, "runs-on") == "ubuntu-latest" and "actions/checkout" not in sht and "mech-review.py" not in sht, sht)
check("shards: reads every baseline leg's artifact", 'pattern: "mech-review-baseline-json-*"' in sht, sht)
with tempfile.TemporaryDirectory() as d:
    for leg, b in ((LEG_API, {"head": "h", "run": True, "count": 2, "timeout": 12.5}),
                   (LEG_WEB, {"head": "h", "run": True, "count": 1, "timeout": None}),
                   (dict(LEG_WEB, key="-2-old"), {"head": "old", "run": True, "count": 3, "timeout": None}),
                   (dict(LEG_WEB, key="-3-cli"), {"head": "h", "run": True, "count": True, "timeout": None})):
        os.makedirs(os.path.join(d, "baseline-result", f"mech-review-baseline-json{leg['key']}"))
        with open(os.path.join(d, "baseline-result", f"mech-review-baseline-json{leg['key']}",
                               "mech-review-baseline.json"), "w") as f:
            json.dump(b, f)
    out = os.path.join(d, "out")
    legs = [LEG_API, LEG_WEB, dict(LEG_WEB, key="-2-old"), dict(LEG_WEB, key="-3-cli"), dict(LEG_WEB, key="-4-gone")]
    r = run_py(heredoc(sh), d, {"LEGS": json.dumps(legs), "HEAD_SHA": "h"}, out)
    got = outputs(out) if r.returncode == 0 else r.stderr
    check("shards: each stack's shards from its own baseline; an old, malformed or missing one runs none",
          isinstance(got, dict) and got.get("run") == "true" and json.loads(got.get("include", "null")) == [
              dict(LEG_API, shard=0, count=2, timeout="12.5"), dict(LEG_API, shard=1, count=2, timeout="12.5"),
              dict(LEG_WEB, shard=0, count=1, timeout="")], str(got))
    r = run_py(heredoc(sh), d, {"LEGS": json.dumps([dict(LEG_WEB, key="-4-gone")]), "HEAD_SHA": "h"}, out + "2")
    got = outputs(out + "2") if r.returncode == 0 else r.stderr
    check("shards: no shard to run reads run false", got == {"run": "false", "include": "[]"}, str(got))
check("mutants: several stacks from the shards job, one stack from the baseline, never both",
      value(mu, "if") == "${{ !cancelled() && ((needs.shards.result == 'success' && needs.shards.outputs.run == 'true') "
                         "|| (needs.shards.result == 'skipped' && needs.baseline.result == 'success' "
                         "&& needs.baseline.outputs.run == 'true')) }}"
      and value(mu, "needs") == "[stack, plan, baseline, shards]", str(value(mu, "if")))
check("report: needs the shards job", "shards" in re.split(r"[\s,\[\]]+", needs), needs)

rp = text(report)
check("report: several stacks fetch every artifact, one stack's fetches are skipped then",
      'pattern: "mech-review-*"' in rp and rp.count("if: needs.stack.outputs.stack != ''") == 4, rp)
check("report: several stacks post one comment with --stacks, the drift result the repo's",
      'if [ -z "$STACK" ]; then' in rp and "--stacks stacks.json" in rp
      and "STACK: ${{ needs.stack.outputs.stack }}" in rp, rp)
with tempfile.TemporaryDirectory() as d:  # the report's per-stack merge, on the real engine
    os.symlink(ROOT, os.path.join(d, "ekit"))
    R = os.path.join(d, "stacks-result")
    head, base = "a" * 40, "b" * 40
    env_r3 = {"ekit": "0", "base": base, "head": head, "entries": [], "summary": "",
              "checks": {"R3": {"status": "pass", "note": "1/1 tested", "tested": 1, "total": 1}},
              "shard": {"k": 0, "n": 1, "max_mutants": 40},
              "stack": {"stack": "python", "project_dir": "api"}}  # merge counts only its stack's results (#62)
    baseline = {"ekit": "0", "base": base, "head": head, "entries": [], "summary": "", "run": True, "count": 1,
                "mutants": 1, "timeout": None, "checks": {"R3": {"status": "pass", "note": ""}}}
    for rel, obj in ((f"mech-review-baseline-json-0-api/mech-review-baseline.json", baseline),
                     (f"mech-review-mutants-0-api-0/mech-review-mutants.json", env_r3)):
        os.makedirs(os.path.dirname(os.path.join(R, rel)), exist_ok=True)
        with open(os.path.join(R, rel), "w") as f:
            json.dump(obj, f)
    r = run_py(heredoc(report, "merge each stack's mutants"), d,
               {"LEGS": json.dumps([LEG_API, LEG_WEB]), "RUNS": json.dumps({"-0-api": True, "-1-web": False}),
                "PLAN_RESULT": "success", "BASE_SHA": base, "HEAD_SHA": head})
    try:
        with open(os.path.join(d, "stacks.json")) as f:
            got = json.load(f)
        with open(os.path.join(d, "mutants-merged-0-api.json")) as f:
            merged_r3 = json.load(f)["checks"]["R3"]
    except (OSError, ValueError) as e:
        got, merged_r3 = f"{e}: {r.stderr}", None
    S = "stacks-result"
    check("report: each stack's results by its key, R3 merged where the plan ran it (#17)",
          got == [{"name": "api", "stack": "python", "project_dir": "api", "envelopes": {
                       "r2": f"{S}/mech-review-json-0-api/mech-review.json",
                       "r0": f"{S}/mech-review-json-0-api/mech-review-r0.json",
                       "red": f"{S}/mech-review-red-json-0-api/mech-review-red.json",
                       "mutants": "mutants-merged-0-api.json"}},
                  {"name": "web", "stack": "ts", "project_dir": "web", "envelopes": {
                       "r2": f"{S}/mech-review-json-1-web/mech-review.json",
                       "r0": f"{S}/mech-review-json-1-web/mech-review-r0.json",
                       "red": f"{S}/mech-review-red-json-1-web/mech-review-red.json"}}]
          and (merged_r3 or {}).get("status") == "pass" and (merged_r3 or {}).get("tested") == 1, str((got, merged_r3)))
    r = run_py(heredoc(report, "merge each stack's mutants"), d,
               {"LEGS": json.dumps([LEG_WEB]), "RUNS": "", "PLAN_RESULT": "failure", "BASE_SHA": base, "HEAD_SHA": head})
    try:
        with open(os.path.join(d, "mutants-merged-1-web.json")) as f:
            web_r3 = json.load(f)
    except (OSError, ValueError) as e:
        web_r3 = f"{e}: {r.stderr}"
    check("report: a plan job with no answer still merges R3, a missing baseline fails it with a CI entry",
          isinstance(web_r3, dict) and web_r3["checks"]["R3"]["status"] == "fail"
          and [e["problem"] for e in web_r3["entries"]]
          == ["baseline job produced no result: no JSON from the baseline job (see its log)"], str(web_r3))
    for runs, why in (("{not json", "the plan job's answers do not read (see its log)"),
                      (json.dumps({"-1-web": None}), "the plan job could not plan this stack (see its log)"),
                      (json.dumps({"-0-api": True}), "the plan job gave no answer for this stack (see its log)")):
        if os.path.exists(os.path.join(d, "mutants-merged-1-web.json")):
            os.remove(os.path.join(d, "mutants-merged-1-web.json"))
        r = run_py(heredoc(report, "merge each stack's mutants"), d,
                   {"LEGS": json.dumps([LEG_WEB]), "RUNS": runs, "PLAN_RESULT": "success", "BASE_SHA": base,
                    "HEAD_SHA": head})
        try:
            with open(os.path.join(d, "mutants-merged-1-web.json")) as f:
                web_r3 = json.load(f)
        except (OSError, ValueError) as e:
            web_r3 = f"{e}: {r.stderr}"
        check(f"report: a plan answer that is not true or false fails that stack's R3, named (review 1: {runs})",
              isinstance(web_r3, dict) and web_r3["checks"]["R3"]["status"] == "fail"
              and [e["problem"] for e in web_r3["entries"]] == [f"baseline job produced no result: {why}"], str(web_r3))


# ---- #18 trust: an adapter file's commands ([commands], [run]) run only through the subcommands that run tests (red,
# all, mutants, baseline), and those run only in red-first, baseline and mutants (their contents: read token is checked
# above). Workflow values (inputs, an adapter's, any job's or step's output) reach a shell only through env ----
RUNS_PR_CODE = ("red-first", "baseline", "mutants")
for job_name in sorted(child_keys(jobs)):
    subs = re.findall(r'mech-review\.py"?\s+(\w+)', text(block(jobs, job_name) or []))
    if job_name not in RUNS_PR_CODE:
        check(f"{job_name}: runs no subcommand that runs an adapter's commands (red, all, mutants, baseline)",
              not {"red", "all", "mutants", "baseline"} & set(subs), str(subs))

# An allowlist over EVERY line that holds `${{`, fail closed: such a line passes only as a plain `key: value` line (an
# optional `- `, a bare unquoted key, a value that is no flow mapping or sequence), outside any block scalar (a run: |
# body, or any other `|` / `>` value), with a key its parent allows. The keys are the non-shell ones the workflows use
# today (derived from the files; a new one is added here on purpose). Any other form, a quoted key, a flow mapping, a
# `run:` that is not a job output, is a fail: so no YAML spelling gets a value into a shell without env.
WF_KEY = re.compile(r"^( *)(- +)?([A-Za-z_][A-Za-z0-9_-]*):(?: (.*))?$")
WF_BLOCK = re.compile(r"^[|>][-+0-9]*\s*(#.*)?$")
WF_ENV = re.compile(r"^[A-Z_][A-Z0-9_]*$")
WF_ALLOWED = {
    "env": WF_ENV,                                                          # an env var: the only way into a shell
    # action inputs (checkout, toolchain, artifacts); key: actions/cache's key, the R0 fingerprint step's output (#21),
    # read by the cache action only, never a shell
    "with": {"ref", "repository", "toolchain", "name", "key"},
    "outputs": {"stack", "project-dir", "error", "target-os", "run", "count", "shards", "timeout",  # job outputs
                "legs",     # #17: the stack job's one leg per stack, and the plan job's legs whose R3 runs: matrix input
                "runs",     # #17: the plan job's answer per stack (key -> true, false or null), read by the report
                "include"},  # #17: the baseline's (one stack) and the shards job's (several) mutants matrix
    "matrix": {"shard", "include"},  # include: only a whole `${{ fromJSON(...) }}` (WF_INCLUDE; #17's multi-stack legs)
    "concurrency": {"group"},
    None: {"if", "runs-on", "name", "timeout-minutes"},  # job and step keys; timeout-minutes: #17's follow-up job limits
}
WF_INCLUDE = re.compile(r"^\$\{\{ fromJSON\([^{}]*\) \}\}$")  # a matrix include that is one fromJSON(...), nothing else
# YAML anchors (&a), aliases (*a) and merge keys (<<:) are refused anywhere outside comments, quoted strings and block
# scalars: an anchored env value (`X: &a ${{ inputs.x }}`) aliased into `run: *a` would reach a shell with no `${{`
WF_ANCHOR = re.compile(r"(^|[\s\[{,:])[&*][A-Za-z0-9_]")
WF_QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")


def interpolations(lines):
    """[(line no, why, line)] for each `${{` line the allowlist above refuses."""
    out, stack, block_at = [], [], None
    for n, line in enumerate(lines, 1):
        ind, s = indent(line), line.strip()
        if block_at is not None:
            if not s or ind > block_at:
                if "${{" in line:
                    out.append((n, "inside a block scalar", s))
                continue
            block_at = None
        if not s or s.startswith("#"):
            continue
        bare = WF_QUOTED.sub("''", line).split(" #", 1)[0]
        if WF_ANCHOR.search(bare) or re.match(r"\s*(- +)?<<\s*:", bare):
            out.append((n, "a YAML anchor, alias or merge key", s))
            continue
        m = WF_KEY.match(line)
        if not m:
            if "${{" in line:
                out.append((n, "not a plain key: value line", s))
            continue
        col, key, val = len(m.group(1)) + len(m.group(2) or ""), m.group(3), m.group(4) or ""
        while stack and stack[-1][0] >= col:
            stack.pop()
        parent = stack[-1][1] if stack else None
        stack.append((col, key))
        if WF_BLOCK.match(val):
            block_at = col
        if "${{" not in line:
            continue
        rule = WF_ALLOWED.get(parent, WF_ALLOWED[None])
        ok = rule.match(key) is not None if hasattr(rule, "match") else key in rule
        if parent == "matrix" and key == "include" and not WF_INCLUDE.match(val.strip()):
            ok = False
        if val.lstrip().startswith(("{", "[")):
            ok = False
        if not ok:
            out.append((n, f"`{key}` under `{parent}`", s))
    return out


# every workflow file: mech-review.yml runs PR code (red-first, baseline, mutants); mech-waive.yml runs none (its only
# checkout is the ekit engine) but holds the same rule; the self callers, tests.yml and release.yml hold no `${{` line
for wf in sorted(os.listdir(os.path.join(ROOT, ".github", "workflows"))):
    if wf.endswith((".yml", ".yaml")):
        got = interpolations(read(f".github/workflows/{wf}"))
        check(f"{wf}: every ${{{{ }}}} line is an allowed non-shell key (values reach a shell only through env)",
              got == [], str(got))
# live: each escaping form is caught, one at a time, spliced into red-first's steps
red_line = next(l for l in W if 'mech-review.py" red' in l)
at = W.index("  red-first:")
at = next(k for k in range(at, len(W)) if W[k] == "    steps:") + 1
BAD = {
    "an input appended in the red command's run block": ("replace", red_line + ' --test-command "${{ inputs.test-command }}"'),
    "an undeclared input inside the red command": ("replace", red_line.replace("red", "red --stack ${{ inputs.stack-def }}", 1)),
    "a one-line run:": ("insert", ["      - name: x", "        run: echo ${{ inputs.adapter }}"]),
    "a run: after two spaces": ("insert", ["      -  run: echo ${{ inputs.setup-command }}"]),
    "a flow-mapping step": ("insert", ['      - {name: y, run: "echo ${{ inputs.setup-command }}"}']),
    "a quoted run key": ("insert", ['      - "run": echo ${{ inputs.setup-command }}']),
    "a flow-mapping env": ("insert", ["      - name: z", "        env: {X: ${{ inputs.setup-command }}}", "        run: echo"]),
    "a script input": ("insert", ["      - uses: actions/github-script@v7", "        with:",
                                  "          script: console.log('${{ inputs.setup-command }}')"]),
    "a folded run block": ("insert", ["      - name: f", "        run: >", "          echo ${{ inputs.adapter }}"]),
    "a merge key": ("insert", ["      - name: m", "        <<: {run: echo}"]),
    "an alias in a list": ("insert", ["      - *step"]),
    "a matrix include that is not one fromJSON": ("insert", ["      - name: i", "        strategy:", "          matrix:",
                                                             "            include: ${{ inputs.legs }}"]),
}
for name, (how, bad) in BAD.items():
    mutated = [bad if l == red_line else l for l in W] if how == "replace" else W[:at] + bad + W[at:]
    check(f"workflow values check is live: {name} is caught", len(interpolations(mutated)) == 1,
          str(interpolations(mutated)))
# an anchored env value aliased into run: (the run: line holds no ${{): the anchor and the alias are each named, by line
anchored = interpolations(W[:at] + ["      - name: a", "        env:", "          SETUP_COMMAND: &cmd ${{ inputs.setup-command }}",
                                    "        run: *cmd"] + W[at:])
check("workflow values check is live: an anchored env value aliased into run: is caught, both lines named",
      [r[1:] for r in anchored] == [("a YAML anchor, alias or merge key", "SETUP_COMMAND: &cmd ${{ inputs.setup-command }}"),
                                    ("a YAML anchor, alias or merge key", "run: *cmd")]
      and anchored[1][0] == anchored[0][0] + 1, str(anchored))
alias_only = interpolations(W[:at] + ["      - name: a", "        run: *cmd"] + W[at:])
check("workflow values check names an alias with no ${{ on its line", [r[1:] for r in alias_only] == [
    ("a YAML anchor, alias or merge key", "run: *cmd")], str(alias_only))
# #17 review 1: a ${{ }} inside a run: body's heredoc (the shards job's python) is caught as inside a block scalar
_sh_at = next(n for n, l in enumerate(W) if l.strip() == "import json" and n > W.index("  shards:"))
_probe = interpolations(W[:_sh_at] + [W[_sh_at].replace("import json", 'print("${{ needs.plan.outputs.legs }}")')]
                        + W[_sh_at:])
check("workflow values check is live: a ${{ }} in the shards job's python heredoc is caught",
      [r[1:] for r in _probe] == [("inside a block scalar", 'print("${{ needs.plan.outputs.legs }}")')], str(_probe))
# allowed on purpose: the #17 follow-up's matrix include and timeout-minutes (and && in an if:, a glob in quotes)
fine = ["      - name: ok", "        if: ${{ a && !b }}", "        timeout-minutes: 30", "        strategy:", "          matrix:",
        "            include: ${{ fromJSON(needs.shards.outputs.include || needs.baseline.outputs.include) }}",
        "        with:", "          path: 'tests/**'"]
check("workflow values check allows a fromJSON matrix include, timeout-minutes, && and a quoted glob",
      interpolations(W[:at] + fine + W[at:]) == [], str(interpolations(W[:at] + fine + W[at:])))

# ---- an adapter's parser command (#27) never reaches a run: script; it runs as argv inside the engine ----
# The parser's install step (#27 follow-up): `parser-install` prints the base adapter file's install argvs, and a step
# in each job whose engine call reads source with the adapter (guard: R2, R0; red-first: R1 and R4 name the changed
# tests) runs them as argv. plan, baseline and mutants read no source with it (changed paths, the tool's report).
# No expression that names a parser may appear in the workflow except as an env value.
# In red-first it runs before R0's runtime cache steps (#21): PR code can steer that install, and the cache dir is
# cleared after it, so nothing the install plants there survives to read as a pass.
for job_name, before in (("guard", "R2 guard"), ("red-first", "R0 runtime fingerprint (run)")):
    jl = block(jobs, job_name) or []
    names = [l.strip()[len("- name: "):] for l in jl if l.strip().startswith("- name: ")]
    check(f"{job_name}: the parser install step right before {before} (#27)",
          INSTALL in names and names.index(INSTALL) + 1 == names.index(before), str(names))
    ist = step(jl, INSTALL)
    check(f"{job_name}: the parser install step takes base, stack and project-dir through env only, no head",
          "BASE_SHA: ${{ github.event.pull_request.base.sha }}" in ist and "STACK: ${{ matrix.stack }}" in ist
          and "PROJECT_DIR: ${{ matrix.project-dir }}" in ist and "HEAD" not in text(ist), str(ist))
    check(f"{job_name}: a failed parser install is not a stop (the engine reports it)", "continue-on-error: true" in ist,
          str(ist))
check("parser install: one step text in guard and red-first",
      step(block(jobs, "guard") or [], INSTALL) == step(block(jobs, "red-first") or [], INSTALL) != [], "")
for job_name in ("stack", "plan", "baseline", "mutants", "report"):
    check(f"{job_name}: no parser install step (it reads no source with the adapter)",
          INSTALL not in text(block(jobs, job_name, 2) or []), job_name)
_ins = text(step(block(jobs, "guard") or [], INSTALL))
check("parser install: argv only, no shell string (no bash -c, eval, shell=True, os.system)",
      not re.search(r"bash -c|\beval\b|shell=True|os\.system|os\.popen", _ins)
      and "subprocess.run(argv, env=env, cwd=cwd)" in _ins,
      _ins)
parser_lines = [l for l in W if "${{" in l and "parser" in l.lower()]
check("parser: the command or install step is never interpolated into a run: line (only env values)",
      all(re.match(r"\s*[A-Z_]+: \$\{\{", l) for l in parser_lines), str(parser_lines))

install_py = heredoc(block(jobs, "guard") or [], INSTALL)
RECORD = "import json, os, sys\nwith open(os.environ['STEP_LOG'], 'a') as f:\n    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"


def install_run(d, printed=None, rc=0, extra_env=None, caller=None):
    """run the install step's python in d (its workspace), with a stub engine printing `printed` and exiting rc (None:
    the real engine), caller(dir) building the caller checkout: (exit code, stdout, GITHUB_ENV lines, the stub engine's
    argv, the steps' logged argvs)."""
    import shutil
    import subprocess
    ws = os.path.join(d, "ws")
    for sub in ("ws", "tmp"):
        shutil.rmtree(os.path.join(d, sub), ignore_errors=True)
    os.makedirs(os.path.join(ws, "caller"), exist_ok=True)
    os.makedirs(os.path.join(d, "tmp"))
    extra_env = dict(extra_env or {}, **(caller(os.path.join(ws, "caller")) if caller else {}))
    if printed is None:
        os.symlink(ROOT, os.path.join(ws, "ekit"))
    else:
        os.makedirs(os.path.join(ws, "ekit", "scripts"))
        with open(os.path.join(ws, "ekit", "scripts", "mech-review.py"), "w") as f:
            f.write(RECORD.replace("STEP_LOG", "ENGINE_LOG") + f"print({json.dumps(json.dumps(printed))})\nsys.exit({rc})\n")
    for name in ("env", "engine.log", "steps.log"):
        open(os.path.join(d, name), "w").close()
    env = {"GITHUB_WORKSPACE": ws, "RUNNER_TEMP": os.path.join(d, "tmp"), "GITHUB_ENV": os.path.join(d, "env"),
           "BASE_SHA": "b" * 40, "STACK": "mini", "PROJECT_DIR": ".", "ENGINE_LOG": os.path.join(d, "engine.log"),
           "STEP_LOG": os.path.join(d, "steps.log"), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
           **extra_env}
    r = run_py(install_py, d, env)
    got = []
    for name in ("env", "engine.log", "steps.log"):
        with open(os.path.join(d, name)) as f:
            got.append(f.read().splitlines())
    return (r.returncode, r.stdout + r.stderr, got[0], [json.loads(l) for l in got[1]], [json.loads(l) for l in got[2]])


with tempfile.TemporaryDirectory() as d:
    d = os.path.realpath(d)
    home = os.path.join(d, "tmp", "ekit-parsers")
    rec = os.path.join(d, "record.py")
    with open(rec, "w") as f:
        f.write(RECORD + "if sys.argv[1:2] == ['make']:\n    os.makedirs(os.path.dirname(sys.argv[2]), exist_ok=True)\n"
                         "    open(sys.argv[2], 'w').close()\n    os.chmod(sys.argv[2], 0o755)\n"
                         "if sys.argv[1:2] == ['home']:\n    assert os.environ['EKIT_PARSER_HOME'] == sys.argv[2]\n"
                         "if sys.argv[1:2] == ['cwd']:\n    here = os.path.realpath(os.getcwd())\n"
                         "    assert os.listdir(here) == [] and os.path.dirname(here) == sys.argv[2], here\n"
                         "sys.exit(int(sys.argv[2]) if sys.argv[1:2] == ['exit'] else 0)\n")
    prog = os.path.join(home, "pip", "p", "1", "bin", "p")
    rc, out, genv, engine, ran = install_run(d, {"stack": "mini", "adapter": "a.toml", "program": prog, "steps": [
        [sys.executable, rec, "home", home], [sys.executable, rec, "cwd", os.path.join(d, "tmp")],
        [sys.executable, rec, "; touch pwned", "$(touch pwned)", "`id`"],
        [sys.executable, rec, "make", prog]]})
    check("parser install: the printed argvs run in order, as argv (shell words stay literal), in a fresh empty dir "
          "under the runner's temp dir (not the checkout), EKIT_PARSER_HOME set for them and, through GITHUB_ENV, for "
          "the later steps",
          rc == 0 and genv == [f"EKIT_PARSER_HOME={home}"] and ran == [["home", home], ["cwd", os.path.join(d, "tmp")],
          ["; touch pwned", "$(touch pwned)", "`id`"], ["make", prog]] and not os.path.exists(os.path.join(d, "pwned"))
          and os.access(prog, os.X_OK), str((rc, out, genv, ran)))
    check("parser install: the engine is asked about the base only, with the home under the runner's temp dir",
          engine == [["parser-install", "--repo", f"{d}/ws/caller", "--base", "b" * 40, "--stack", "mini",
                      "--project-dir", ".", "--home", home]], str(engine))
    rc, out, genv, _, ran = install_run(d, {"steps": [], "program": None})
    check("parser install: nothing to install (a built-in, a pattern file) runs nothing and passes",
          rc == 0 and ran == [] and genv == [f"EKIT_PARSER_HOME={home}"], str((rc, out, ran)))
    rc, out, genv, _, ran = install_run(d, {"steps": [[sys.executable, rec, "exit", "3"], [sys.executable, rec, "after"]],
                                            "program": prog})
    check("parser install: a failed step stops the install, fails the step (continue-on-error) and names it",
          rc == 1 and ran == [["exit", "3"]] and "::error::parser install step failed (3)" in out
          and "not installed by the declared package" in out and genv == [f"EKIT_PARSER_HOME={home}"], str((rc, out, ran)))
    rc, out, _, _, ran = install_run(d, {"steps": [[os.path.join(d, "no-such-installer"), "x"]], "program": prog})
    check("parser install: an installer missing on the runner fails the step, named", rc == 1
          and "::error::parser install step failed (cannot run: " in out, out)
    rc, out, _, _, ran = install_run(d, {"steps": [[sys.executable, rec, "ok"]], "program": prog})
    check("parser install: steps that leave no program fail the step", rc == 1 and ran == [["ok"]]
          and f"::error::the install steps left no program at {prog}" in out, out)
    for printed, rc_engine, why in (({"steps": [[sys.executable, rec, "x"]]}, 2, "exit 2"), ({"steps": "rm -rf /"}, 0,
                                    "steps: want a list of argv lists"), ({"steps": [[]]}, 0, "steps: want a list of"),
                                    ([], 0, "list indices")):
        rc, out, _, _, ran = install_run(d, printed, rc_engine)
        check(f"parser install: an engine error or output that is not argv lists runs nothing and fails the step ({why})",
              rc == 1 and ran == [] and "::error::mech-review parser-install: " in out and why in out, out)

    # the real engine on a fixture repo: the base's [parser] installs, the PR's changed one never does
    import subprocess
    PARSER = ('format = 1\nname = "mini"\nextensions = [".mini"]\n\n[parser]\ncommand = "mini-facts"\n'
              'installer = "pip"\npackage = "mini-facts"\nversion = "{v}"\n')
    fake = os.path.join(d, "bin")
    os.makedirs(fake)
    with open(os.path.join(fake, "python3"), "w") as f:  # `python3 -m venv P`: a venv whose pip writes the program
        f.write(f"#!{sys.executable} -I\nimport os, sys\nassert sys.argv[1:3] == ['-m', 'venv'], sys.argv\n"
                "os.makedirs(sys.argv[3] + '/bin')\nwith open(sys.argv[3] + '/bin/python', 'w') as f:\n"
                f"    f.write('#!{sys.executable} -I\\nimport os, sys\\nd = os.path.dirname(os.path.dirname(sys.argv[0]))\\n"
                "open(d + \"/pip.log\", \"w\").write(\" \".join(sys.argv[1:]))\\n"
                "open(d + \"/bin/mini-facts\", \"w\").close()\\nos.chmod(d + \"/bin/mini-facts\", 0o755)\\n')\n"
                "os.chmod(sys.argv[3] + '/bin/python', 0o755)\n")
    os.chmod(os.path.join(fake, "python3"), 0o755)

    def fixture(repo):
        """a base with the parser-backed mini.toml at 1.0.0 and a head (checked out) that bumps it to 6.6.6."""
        def git(*a):
            return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", "-c",
                                   "commit.gpgsign=false", *a], check=True, capture_output=True, text=True,
                                  env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)).stdout
        git("init", "-q", "-b", "main")
        os.makedirs(os.path.join(repo, ".ekit", "adapters"))
        shas = []
        for v in ("1.0.0", "6.6.6"):
            with open(os.path.join(repo, ".ekit", "adapters", "mini.toml"), "w") as f:
                f.write(PARSER.format(v=v))
            git("add", "-A")
            git("commit", "-q", "-m", v)
            shas.append(git("rev-parse", "HEAD").strip())
        return {"BASE_SHA": shas[0]}

    rc, out, genv, _, _ = install_run(d, None, extra_env={"PATH": fake + os.pathsep + os.environ["PATH"]}, caller=fixture)
    prefix = os.path.join(home, "pip", "mini-facts")
    try:
        with open(os.path.join(prefix, "1.0.0", "pip.log")) as f:
            pip_log = f.read()
    except OSError as e:
        pip_log = str(e)
    check("parser install: on the real engine, the base's [parser] installs (the PR's changed version never does)",
          rc == 0 and pip_log == "-m pip install mini-facts==1.0.0" and genv == [f"EKIT_PARSER_HOME={home}"]
          and os.access(os.path.join(prefix, "1.0.0", "bin", "mini-facts"), os.X_OK)
          and sorted(os.listdir(prefix)) == ["1.0.0"], str((rc, out, pip_log)))
    rc, out, _, _, _ = install_run(d, None, extra_env={"STACK": "python"}, caller=fixture)
    check("parser install: on the real engine, a built-in stack installs nothing", rc == 0 and not os.path.exists(home)
          and "install:" not in out, str((rc, out)))

# ---- ekit's own caller ----
SW = ".github/workflows/mech-review-self.yml"
S = read(SW)
check("self: file exists", S is not None, SW)
S = S or []
son = block(S, "on", 0) or []
check("self: on pull_request", "pull_request" in child_keys(son), str(child_keys(son)))
check("self: no pull_request_target", "pull_request_target" not in child_keys(son))
sperm = block(S, "permissions", 0) or []
sperm_map = {k: value(sperm, k) for k in child_keys(sperm)}
check("self: permissions exactly contents read + pull-requests write",
      sperm_map == {"contents": "read", "pull-requests": "write"}, str(sperm_map))
sjobs = block(S, "jobs", 0) or []
local = [k for k in child_keys(sjobs) if value(block(sjobs, k) or [], "uses") == "./.github/workflows/mech-review.yml"]
check("self: exactly one job calls the local reusable workflow", len(local) == 1, str(local))
if local:
    w = block(block(sjobs, local[0]) or [], "with") or []
    # ekit's own code is python: on the rust stack no file of it was production code, so R1 and R3 never ran
    check("self: stack python (the kit's own language)", value(w, "stack") == "python", str(value(w, "stack")))
    # the scenarios' fixtures are test support, not production code (#26: a fake tool there took R3's 40 slots)
    tp = [l.strip() for l in (block(w, "test-paths") or []) if l.strip()]
    check("self: test-paths tests/** and .ekit/scenarios/**",
          value(w, "test-paths") == "|" and tp == ["tests/**", ".ekit/scenarios/**"], str((value(w, "test-paths"), tp)))
    check("self: protected-paths .github/**", value(w, "protected-paths") == ".github/**",
          str(value(w, "protected-paths")))

# ---- #46 docs: the baseline runs once; a set mutant-timeout does not cap it ----
check("workflow text: a set mutant-timeout no longer caps the baseline", "also caps the baseline" not in text(W),
      [l for l in W if "caps the baseline" in l])
check("docs: the baseline job is named in the jobs list", "`baseline`" in docs_text, "")
check("docs: a set mutant-timeout does not cap the baseline", "also caps the baseline" not in docs_text, "")

# ---- #53: the R2 guard passes the issues the PR body closes as --linked-issue ----
import subprocess
import textwrap
wf = "\n".join(W)
gi = wf.index("      - name: R2 guard")
gj = wf.index("        run: |\n", gi) + len("        run: |\n")
step = textwrap.dedent(wf[gj:wf.index("\n      - name: ", gj)])
genv = wf[gi:gj]
check("guard: PR_BODY comes through env, never into run:", "PR_BODY: ${{ github.event.pull_request.body }}" in genv
      and "github.event.pull_request.body" not in step, genv)
check("guard: no new permission (the body is in the event payload)", "issues:" not in text(W)[:text(W).index("jobs:")], "")
with tempfile.TemporaryDirectory() as ws:
    os.makedirs(os.path.join(ws, "ekit", "scripts"))
    with open(os.path.join(ws, "ekit", "scripts", "mech-review.py"), "w") as f:  # stub engine: prints its linked issues
        f.write("import sys\na = sys.argv[1:]\nprint(' '.join(a[i + 1] for i, x in enumerate(a) if x == '--linked-issue'))\n")
    def linked(body):
        env = dict(os.environ, GITHUB_WORKSPACE=ws, BASE_SHA="b", HEAD_SHA="h", STACK="python", PROJECT_DIR=".",
                   TEST_PATHS="tests/**", PROTECTED_PATHS=".github/**", REPO="o/r", PR_BODY=body)
        subprocess.run(["bash", "-c", step], cwd=ws, env=env, capture_output=True, text=True)
        out = os.path.join(ws, "mech-review.json")
        return open(out).read().strip() if os.path.exists(out) else None
    for body, want in (("Closes #53", "53"), ("Fixes #53\nresolves: #61\nCLOSED #53", "53 61"),
                       ("closes o/r#7, fixes https://github.com/o/r/issues/8", "7 8"),
                       ("closes x/y#9, fixes https://github.com/x/y/issues/10", ""),
                       ("See #53; disclose #6; closes #0", ""), ("", ""), ("Closes #5 $(echo pwned) `echo pwned`", "5"),
                       # GitHub reads no closing keyword in code or a comment: an example in the body links nothing
                       ("Closes #1\n`Fixes #53` / `resolves: #61`\n```\ncloses #7\n```\n~~~\nfixes #8\n~~~\n<!-- closes #9 -->",
                        "1"), ("``closes #3`` and `` fixes #4 ``", "")):
        got = linked(body)
        check(f"guard: body {body!r} links {want or 'nothing'}", got == want, repr(got))

print("")
sys.exit(1 if FAILS else 0)
PY
