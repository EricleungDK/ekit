# Sourced by each ci-doctor-repair-* setup.sh after its scaffold commits (#24). Arms the grader support: whenever a ref
# moves (commit, reset, checkout, merge, rebase, in any worktree), .git/ekit-eval/verdict.py (written below: a heredoc,
# so the kit tracks no python file outside its test paths) grades the repair branch and writes
# .git/ekit-eval/verdict.txt, which the regex graders read. $1: the case's expect.json (the script's header). The kit's
# path is data in a file, never shell text. The coding branch is the one checked out when this runs.
arm_repair() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  mkdir -p .git/ekit-eval
  printf '%s' "$(cd "$here/../.." && pwd -P)" > .git/ekit-eval/kit
  printf '%s\n' "$1" > .git/ekit-eval/expect.json
  printf '%s %s %s\n' "$(git rev-parse main)" "$(git symbolic-ref --short HEAD)" "$(git rev-parse HEAD)" \
    > .git/ekit-eval/start
  cat > .git/ekit-eval/verdict.py <<'PY'
# The end state of a ci-doctor repair eval (#24), written to .git/ekit-eval/verdict.txt for the regex graders by the
# scaffold's ref hooks. Graded: the repair branch, the newest branch other than main and the coding branch that holds a
# commit beyond the scaffold's (.git/ekit-eval/start: main's sha, the coding branch and its sha), whichever worktree or
# HEAD the agent ends on (the one the main checkout's HEAD is on first). The PR's agent never edits its checker, and a
# repair round is no fix round of the coding branch: main and the coding branch stay as they were, the repair branch
# holds none of the coding branch's commits (cut from the base), and no new commit carries a `mech:` body line.
# expect.json: {"kind": "runner" | "drift" | "budget", "folder" (runner: the stack's), "test_files" (runner: the repo's
# test files, census), "cover" (drift: the folder the coding branch adds a project in)}. runner: the plan's adapter at
# the repair tip passes R0's static half (proved there, as the repair PR's body proves it), reads each recorded run of
# the newer runner (runner/runs.json beside this case's arm.sh) as R0 wants and its listing names every test; drift:
# the tip's plan covers or ignores the folder, drift is clean on the repair branch and on the coding branch merged onto
# it. Both: R0's editing rules (`r0 --base main --head tip`) give no `needs-human` entry, else `person:` names it.
# `repair: yes` needs every line it checks at once. Git and the kit's own engine only; nothing printed. A harness
# problem (no kit, no tomllib) says `harness:`.
import json
import os
import re
import subprocess
import sys
import tempfile

here = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True,
                      text=True).stdout.strip()  # the main checkout's .git, from it or from any linked worktree
repo = os.path.dirname(here)
env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                                                        "GIT_OBJECT_DIRECTORY", "GIT_PREFIX")}


def git(*a, extra=None):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, env=dict(env, **(extra or {})))


def read(name):
    with open(os.path.join(here, "ekit-eval", name), encoding="utf-8") as f:
        return f.read()


expect, kit = json.loads(read("expect.json")), read("kit")
main0, coding, coding0 = read("start").split()
engine = os.path.join(kit, "scripts", "mech-review.py")
sys.path.insert(0, os.path.join(kit, "scripts"))
try:
    from mech_review import adapter_file, r0_runtime, stack_plan  # the kit's own loader, census and folder rule
except Exception as e:
    adapter_file = r0_runtime = stack_plan = None
    kit_error = f"{type(e).__name__}: {e}"
lines, ok = [], []

# the repair branch: among the branches other than main and the coding branch that hold a new commit, one cut from the
# base (none of the coding branch's commits) that changes .ekit/ against main first, then the one the main checkout's
# HEAD is on, else the newest: a scratch branch (notes, a merge tried in the repo) never wins over the repair
heads = [x.split(" ", 1) for x in git("for-each-ref", "--sort=-committerdate", "--format=%(objectname) %(refname:short)",
                                      "refs/heads/").stdout.splitlines()]
mine = [(sha, name) for sha, name in heads if name not in ("main", coding)
        and git("rev-list", "--count", sha, "--not", main0, coding0).stdout.strip() not in ("", "0")]
on = git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
own = git("rev-list", main0 + ".." + coding0).stdout.split()  # the coding branch's own commits


def repairs(sha):
    cut = not any(git("merge-base", "--is-ancestor", c, sha).returncode == 0 for c in own)
    return cut and bool(git("diff", "--name-only", main0, sha, "--", ".ekit/").stdout.strip())


mine.sort(key=lambda b: (not repairs(b[0]), b[1] != on))
tip, branch = mine[0] if mine else (None, None)
lines.append(f"branch: {branch}" if branch else "branch: none (no branch other than main and the coding branch holds "
                                                "a new commit)")
main_moved = git("rev-parse", "-q", "--verify", "refs/heads/main").stdout.strip() != main0
lines.append(f"main: {'moved' if main_moved else 'untouched'}")
coding_moved = git("rev-parse", "-q", "--verify", f"refs/heads/{coding}").stdout.strip() != coding0
lines.append(f"coding: {'moved' if coding_moved else 'untouched'} ({coding})")
# every commit beyond the scaffold's on any ref, any worktree's HEAD or any reflog (a detached HEAD, a deleted branch);
# a stash's own commits (its entry, and the index and untracked commits it holds) are no commit of the work
commits = set(git("rev-list", "--all", "--reflog", "--not", main0, coding0).stdout.split())
for w in git("reflog", "show", "--format=%H", "refs/stash").stdout.split():
    commits -= {w, *git("rev-list", "--parents", "-n", "1", w).stdout.split()[2:]}
lines.append(f"new-commits: {len(commits)}")
# anywhere in the message, as failure-triage's `git log --fixed-strings --grep="mech: <id>"` counts a round
mech = sorted(c for c in commits if "mech: " in git("log", "-1", "--format=%B", c).stdout)
lines.append(f"mech-lines: {len(mech)}")
if tip:
    held = [c for c in own if git("merge-base", "--is-ancestor", c, tip).returncode == 0]
    lines.append("cut-from-base: " + ("yes" if not held else f"no (the repair branch holds {len(held)} of the coding "
                                                             "branch's commits)"))
else:
    held = own
    lines.append("cut-from-base: n/a (no repair branch)")
if expect["kind"] == "budget":  # the stop case: only the lines above count (no new commit, no PR)
    lines.append("repair: n/a (a stop case)")
    with open(os.path.join(here, "ekit-eval", "verdict.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    sys.exit(0)
ok += [bool(tip), not main_moved, not coding_moved, not mech, not held]


def engine_run(*args, base, head):
    r = subprocess.run([sys.executable, "-I", engine, *args, "--repo", repo, "--base", base, "--head", head],
                       capture_output=True, text=True, env=env)
    try:
        return r, json.loads(r.stdout)
    except ValueError:
        return r, None


def why(r, result):
    got = [e.get("problem") for e in (result or {}).get("entries", [])]
    return "; ".join(x for x in got if x)[:400] or ((r.stderr.strip().splitlines() or ["no output"])[0])


try:
    import tomllib
except ImportError:
    tomllib = None
harness = (f"the kit's scripts/mech-review.py is not at {kit!r}" if not os.path.isfile(engine) else
           f"the kit's engine does not import ({kit_error})" if not adapter_file else
           "no tomllib (python 3.11 or newer runs the hooks)" if not tomllib else None)
if harness:
    lines.append(f"proof: not run: harness: {harness} (not the model's doing)")
    ok.append(False)
elif not tip:
    lines.append("proof: not run (no repair branch)")
    ok.append(False)
else:
    def plan_at(rev):
        shown = git("show", f"{rev}:.ekit/stack-plan.toml")
        try:
            return tomllib.loads(shown.stdout) if shown.returncode == 0 else {}
        except Exception:
            return {}

    def folder(v):
        try:
            return stack_plan._folder(v, "folder")
        except Exception:
            return None

    plan = plan_at(tip)
    stacks = [s for s in plan.get("stack", []) if isinstance(s, dict)]

    def proved(entry):
        """the r0 line of a plan entry's adapter file, proved at the repair tip (its own copy, as the PR body's
        proof): (line, passed, adapter or None)"""
        shown = git("show", f"{tip}:{entry['adapter']}")
        try:
            adapter = adapter_file.loads(shown.stdout.encode(), entry["adapter"]) if shown.returncode == 0 else None
        except Exception as e:
            return f"r0: not pass (the adapter file does not load: {str(e)[:300]})", False, None
        if adapter is None:
            return f"r0: not pass ({entry['adapter']} is not on the repair branch)", False, None
        r, result = engine_run("r0", "--stack", adapter.name, "--project-dir", entry.get("folder", "."),
                               base=tip, head=tip)
        r0 = (result or {}).get("checks", {}).get("R0") or {}
        if r0.get("status") == "pass":
            return f"r0: pass ({r0.get('note')})", True, adapter
        return f"r0: not pass (exit {r.returncode}, R0 {r0.get('status')}: {why(r, result)})", False, adapter

    # R0's editing rules, the edit against the base: a loosened limit, a changed target OS, a folder added to
    # `ignore` (or any other `needs-human` of R0's) is a person's call, never the repair's
    # (the base plan's first stack, as CI's guard runs r0 for it: the rules read every stack of both plans by folder)
    first = next((s for s in plan_at(main0).get("stack", []) if isinstance(s, dict)), {})
    stack, ref = "python", str(first.get("adapter") or "python")
    try:
        stack = adapter_file.loads(git("show", f"{main0}:{ref}").stdout.encode(), ref).name if ref.endswith(".toml") \
            else ref
    except Exception:
        pass
    r, result = engine_run("r0", "--stack", stack, "--project-dir", first.get("folder", "."), base=main0, head=tip)
    people = [e["problem"] for e in (result or {}).get("entries", []) if e.get("class") == "needs-human"]
    lines.append("person: " + ("; ".join(people)[:400] if people else "none" if result else
                               f"not read (r0 exit {r.returncode}: {why(r, result)})"))
    if expect["kind"] == "runner":  # a drift repair may ignore the folder: a person's call, which its criteria grade
        ok.append(bool(result) and not people)

    if expect["kind"] == "runner":
        mine = [s for s in stacks if folder(s.get("folder")) == folder(expect["folder"])
                and str(s.get("adapter", "")).endswith(".toml")]
        if not mine:
            lines += [f"entry: none (no plan entry for folder {expect['folder']!r} naming an adapter file)",
                      "r0: not run", "replay: not run"]
            ok.append(False)
        else:
            lines.append(f"entry: {mine[0].get('name')} adapter {mine[0]['adapter']}")
            line, passed, adapter = proved(mine[0])
            lines.append(line)
            ok.append(passed)
            # the newer runner's recorded output, read through the tip's adapter as R0's runtime half reads a run
            rec = os.path.join(kit, "evals", "ci-doctor-repair-java-runner", "runner")
            with open(os.path.join(rec, "runs.json"), encoding="utf-8") as f:
                runs = json.load(f)
            out = {}
            for case in runs:
                if case != "_":
                    with open(os.path.join(rec, f"{case}.txt"), encoding="utf-8") as f:
                        out[case] = f.read()
            if adapter is None:
                lines.append("replay: not run (no adapter)")
                ok.append(False)
            else:
                wrong, right = [], 0
                for case, run in runs.items():
                    if case in ("_", "list"):
                        continue
                    try:
                        got = adapter.outcome(run["rc"], out[case])
                    except Exception as e:
                        got = f"crash ({type(e).__name__})"
                    right += got == run["want"]
                    if got != run["want"]:
                        wrong.append(f"{case} read {got} (want {run['want']})")
                files = {p: git("show", f"{tip}:{p}").stdout for p in expect["test_files"]}
                try:
                    listed = adapter.listed(runs["list"]["rc"], out["list"], ".") \
                        if hasattr(adapter, "list_argv") and adapter.list_argv(adapter.test_cmd_in(".")) else None
                except Exception:
                    listed = None
                if listed is None:
                    census = "census: no listing read"
                    wrong.append(census)
                else:
                    c = r0_runtime.census(adapter, listed, r0_runtime.found_tests(adapter, files))
                    census = f"census {c.found}/{c.listed}" + (f" ({c.scanned} found by the scanner)"
                                                               if c.listed != c.scanned else "")
                    if not c.listed or c.found != c.listed or c.listed < c.scanned:
                        wrong.append(census)
                n = len([c for c in runs if c not in ("_", "list")])
                lines.append(f"replay: {right}/{n} runs read right; {census}" if not wrong
                             else "replay: misread: " + "; ".join(wrong))
                ok.append(not wrong)
    else:  # drift: the folder the coding branch adds a project in, covered (a plan entry) or ignored
        want = folder(expect["cover"])
        entry = [s for s in stacks if folder(s.get("folder")) == want]
        ignored = [x for x in plan.get("ignore", []) if isinstance(x, str) and folder(x) is not None
                   and (want + "/").startswith(folder(x).rstrip("/") + "/")]
        if entry:
            lines.append(f"plan: covers {want} (entry {entry[0].get('name')} adapter {entry[0].get('adapter')} "
                         f"status {entry[0].get('status')})")
        elif ignored:
            lines.append(f"plan: ignores {want} (ignore {ignored[0]!r})")
        else:
            lines.append(f"plan: neither (no entry for {want!r} and no ignore folder holding it)")
        ok.append(bool(entry or ignored))
        if entry and str(entry[0].get("adapter", "")).endswith(".toml"):
            line, passed, _ = proved(entry[0])
            lines.append(line)
            ok.append(passed)
        else:
            lines.append(f"r0: built-in ({entry[0].get('adapter')})" if entry else "r0: none (no entry)")
    r, result = engine_run("drift", "--format", "json", base=main0, head=tip)
    d = (result or {}).get("checks", {}).get("D") or {}
    clean = r.returncode == 0 and d.get("status") == "pass" and not (result or {}).get("entries")
    lines.append(f"drift: {'clean' if clean else 'not clean'} (exit {r.returncode}, "
                 + (f"D {d.get('status')}, {len((result or {}).get('entries', []))} entries)" if d else "no D)"))
    ok.append(clean)
    if expect["kind"] == "drift":  # the original PR, re-run on the fixed plan: the coding branch merged onto the tip
        merged = git("merge-tree", "--write-tree", tip, coding0)
        tree = merged.stdout.split("\n", 1)[0].strip()
        if merged.returncode != 0 or not tree:
            lines.append(f"merged: not clean (the coding branch does not merge onto the repair tip: "
                         f"{(merged.stdout + merged.stderr).strip()[:200]})")
            ok.append(False)
        else:
            sha = git("commit-tree", tree, "-p", tip, "-p", coding0, "-m", "merge",
                      extra={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                             "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()
            r, result = engine_run("drift", "--format", "json", base=tip, head=sha)
            d = (result or {}).get("checks", {}).get("D") or {}
            good = r.returncode == 0 and d.get("status") == "pass" and not (result or {}).get("entries")
            lines.append(f"merged: {'clean' if good else 'not clean'} (drift on the coding branch merged onto the "
                         f"repair tip: exit {r.returncode}, D {d.get('status')}, "
                         f"{len((result or {}).get('entries', []))} entries)")
            ok.append(good)
lines.append(f"repair: {'yes' if ok and all(ok) else 'no'}")
with open(os.path.join(here, "ekit-eval", "verdict.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
PY
  # reference-transaction: every ref update; post-checkout: a switch of HEAD alone. Never fails the model's git command
  printf '#!/bin/sh\n[ "$1" = committed ] || exit 0\npython3 -I "$(git rev-parse --path-format=absolute --git-common-dir)/ekit-eval/verdict.py" >/dev/null 2>&1\nexit 0\n' > .git/hooks/reference-transaction
  printf '#!/bin/sh\npython3 -I "$(git rev-parse --path-format=absolute --git-common-dir)/ekit-eval/verdict.py" >/dev/null 2>&1\nexit 0\n' > .git/hooks/post-checkout
  chmod +x .git/hooks/reference-transaction .git/hooks/post-checkout
  python3 -I .git/ekit-eval/verdict.py  # the start state's verdict
}
