#!/bin/bash
# Structural test of the mech-review reusable workflow and ekit's self caller.
# Stdlib line-based parse (no PyYAML): top-level blocks, child keys, scalar values.
source "$(dirname "$0")/lib.sh"
python3 -I - "$ROOT" <<'PY'
import os
import re
import sys

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
check("reusable: jobs are exactly stack + guard + red-first + report + plan + baseline + mutants (#46)",
      child_keys(jobs) == {"stack", "guard", "red-first", "report", "plan", "baseline", "mutants"}, str(child_keys(jobs)))
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
check("report: downloads the guard, drift, red-first, baseline and mutants artifacts (#46, #56)",
      text(report).count("download-artifact@v4") == 5 and "mech-review-red-json" in text(report)
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
check("red-first: toolchain set up for the rust stack", "rust-toolchain" in rt and "needs.stack.outputs.stack == 'rust'" in rt)
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
      "dtolnay/rust-toolchain@" in bt and "needs.stack.outputs.stack == 'rust'" in bt, bt)
check("baseline: cargo-mutants pinned to 27.1.0, install failure is not a stop", "cargo-mutants@27.1.0" in bt
      and "continue-on-error: true" in bt, bt)
check("baseline: uploads its JSON artifact", "mech-review-baseline-json" in bt and "upload-artifact" in bt, bt)
check("baseline: no pull_request_target", "pull_request_target" not in bt)

check("mutants: needs plan and baseline", {"plan", "baseline"} <= set(re.split(r"[\s,\[\]]+", (value(mu, "needs") or ""))),
      str(value(mu, "needs")))
check("mutants: runs only when the baseline says shards run (#46)", "needs.baseline.outputs.run == 'true'" in (value(mu, "if") or ""),
      str(value(mu, "if")))
strategy = block(mu, "strategy") or []
check("mutants: shard matrix from the baseline output", "fromJSON(needs.baseline.outputs.shards)" in text(strategy), text(strategy))
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
      py_bl.startswith("if: needs.stack.outputs.stack == 'python'") and '"pytest==9.2.0" "mutmut==3.8.1"' in py_bl
      and 'echo "$RUNNER_TEMP/py-venv/bin" >> "$GITHUB_PATH"' in py_bl, py_bl)
bl_names = [l.strip()[len("- name: "):] for l in bl if l.strip().startswith("- name: ")]
check("baseline: the python venv after the checkouts, before the baseline runs (#64)",
      "Python toolchain" in bl_names and bl_names.index("Python toolchain") == 2
      and bl_names.index("Python toolchain") < bl_names.index("R3 baseline (once; shard count, derived timeout)"), str(bl_names))
RUST_OR_PY = "(needs.stack.outputs.stack == 'rust' || needs.stack.outputs.stack == 'python')"
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
check("mutants: shard flag from the matrix and the baseline's shard count",
      "matrix.shard" in rs and "needs.baseline.outputs.count" in rs, rs)
check("mutants: budget from the mutation-budget input", "inputs.mutation-budget" in mt and "--mutation-budget" in rs, rs)
check("mutants: mutant-timeout from the input, else the baseline's derived one (#46), via env, passed only when set",
      "MUTANT_TIMEOUT: ${{ inputs.mutant-timeout || needs.baseline.outputs.timeout }}" in mt
      and '--mutant-timeout "$MUTANT_TIMEOUT"' in rs and 'if [ -n "$MUTANT_TIMEOUT" ]' in rs, rs)
check("mutants: the cap from the max-mutants input, via env (#26)",
      "MAX_MUTANTS: ${{ inputs.max-mutants }}" in rs and '--max-mutants "$MAX_MUTANTS"' in rs, rs)
check("mutants: rc above 1 is no result (crash surfaces at report)", "rc -gt 1" in rs or "-gt 1" in rs, rs)
up = step(mu, "upload mutants result")
check("mutants: uploads its JSON artifact per shard", "mech-review-mutants-${{ matrix.shard }}" in "\n".join(up)
      and "upload-artifact" in mt and any(l == "if: always()" for l in up), str(up))

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
check("stack: exposes stack, project-dir, target-os and error outputs",
      child_keys(block(st, "outputs")) == {"stack", "project-dir", "target-os", "error"}, str(block(st, "outputs")))
check("stack: target-os from resolve's target_os",
      "target-os: ${{ steps.resolve.outputs.target-os }}" in stt and '"target-os": r.get("target_os") or ""' in stt, stt)
RUNS_ON_OS = ("runs-on: ${{ fromJSON('{\"linux\":\"ubuntu-latest\",\"macos\":\"macos-latest\","
              "\"windows\":\"windows-latest\"}')[needs.stack.outputs.target-os] }}")
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
check("guard: the drift step (D) right after the checkouts, before R2 guard (#56)",
      g_names[2:5] == ["drift check (stack plan, D)", "upload drift result", "R2 guard"], str(g_names))
dt = text(step(block(jobs, "guard") or [], "drift check (stack plan, D)"))
check("guard: drift runs mech-review.py drift, no result stops the job",
      "mech-review.py\" drift" in dt and "[ -s mech-review-drift.json ] || rm -f mech-review-drift.json" in dt
      and 'exit "$(( rc > 0 ? rc : 2 ))"' in dt, dt)
check("report: the drift envelope only when its file is there (#56)",
      "if [ -f drift-result/mech-review-drift.json ]; then" in text(report)
      and "extra+=(--envelope drift=drift-result/mech-review-drift.json)" in text(report), text(report))
check("guard: R0's static half right after R2 guard, before the upload (#20)",
      g_names[4:7] == ["R2 guard", "R0 static half (adapter proof)", "upload result"], str(g_names))
r0t = text(step(block(jobs, "guard") or [], "R0 static half (adapter proof)"))
check("guard: R0 runs mech-review.py r0 on the settled stack and the test paths, git only",
      "mech-review.py\" r0 \"${args[@]}\" > mech-review-r0.json" in r0t and "STACK: ${{ needs.stack.outputs.stack }}" in r0t
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
    check(f"guard: {step_name} gets the stack job's project-dir through env",
          "PROJECT_DIR: ${{ needs.stack.outputs.project-dir }}" in gs and '--project-dir "$PROJECT_DIR"' in gs, gs)


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
check("stack: one stack gives its outputs as before",
      one == {"stack": "python", "project-dir": "api", "error": "", "target-os": "macos"}, str(one))
several = stack_outputs({"stack": None, "project_dir": ".", "error": None, "target_os": None, "stacks": [
    {"name": "api", "stack": "python", "project_dir": "api", "adapter": "python", "target_os": "linux"},
    {"name": "web", "stack": "ts", "project_dir": "web", "adapter": "ts", "target_os": "linux"}]})
check("stack: several stacks from the plan (#17) stop the job, named, never run as no stack",
      several == {"stack": "", "project-dir": ".", "target-os": "",
                  "error": "stack auto: the stack plan has several stacks to run (api: python in api, web: ts in web); "
                           "this workflow runs one stack: set the stack and project-dir inputs to the one to check"},
      str(several))
check("stack: inputs.stack and inputs.project-dir are read in the stack job only",
      "inputs.stack" not in text(W[W.index("  guard:"):]) and "inputs.project-dir" not in text(W[W.index("  guard:"):]))
for job_name in ("guard", "red-first", "plan", "baseline", "mutants", "report"):
    check(f"{job_name}: needs stack", "stack" in re.split(r"[\s,\[\]]+", value(block(jobs, job_name) or [], "needs") or ""),
          str(value(block(jobs, job_name) or [], "needs")))
check("stack outputs: only in env values or if: conditions, never interpolated into a run: line",
      all(re.match(r"\s*(-\s+)?(if:|[A-Z_]+:|\w[\w-]*: \$\{\{ steps\.resolve)", l) or l.strip() == RUNS_ON_OS
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
          '--project-dir "$PROJECT_DIR"' in text(run_st) and "PROJECT_DIR: ${{ needs.stack.outputs.project-dir }}" in text(run_st),
          str(run_st))
    sc = step(jl, "setup command")
    check(f"{job_name}: setup-command step runs only when set", "if: inputs.setup-command != ''" in sc, str(sc))
    check(f"{job_name}: setup-command passed through env, run with bash, not interpolated",
          "SETUP_COMMAND: ${{ inputs.setup-command }}" in sc and "shell: bash" in sc
          and 'run: bash -c "$SETUP_COMMAND"' in sc and not any("${{" in l for l in sc if l.startswith("run:")), str(sc))
    order = [n for n in names if n in ("extra apt packages", "setup command", run_name)]
    check(f"{job_name}: setup-command after extra apt packages, before the tests",
          order == ["extra apt packages", "setup command", run_name], str(names))

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
    "with": {"ref", "repository", "toolchain", "name"},                    # action inputs (checkout, toolchain, artifacts)
    "outputs": {"stack", "project-dir", "error", "target-os", "run", "count", "shards", "timeout"},  # job outputs
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
# allowed on purpose: the #17 follow-up's matrix include and timeout-minutes (and && in an if:, a glob in quotes)
fine = ["      - name: ok", "        if: ${{ a && !b }}", "        timeout-minutes: 30", "        strategy:", "          matrix:",
        "            include: ${{ fromJSON(needs.shards.outputs.include || needs.baseline.outputs.include) }}",
        "        with:", "          path: 'tests/**'"]
check("workflow values check allows a fromJSON matrix include, timeout-minutes, && and a quoted glob",
      interpolations(W[:at] + fine + W[at:]) == [], str(interpolations(W[:at] + fine + W[at:])))

# ---- an adapter's parser command (#27) never reaches a run: script; it runs as argv inside the engine ----
# The workflow reads no repo adapter file yet (#17 wires them in, with the guard's install step for the parser): until
# then no expression that names a parser may appear in the workflow except as an env value.
parser_lines = [l for l in W if "${{" in l and "parser" in l.lower()]
check("parser: the command or install step is never interpolated into a run: line (only env values)",
      all(re.match(r"\s*[A-Z_]+: \$\{\{", l) for l in parser_lines), str(parser_lines))

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

print("")
sys.exit(1 if FAILS else 0)
PY
