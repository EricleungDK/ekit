"""mistake-to-check: the shipped skill routes the #74-#77 run's mistakes, and the checks it routes to bite."""
import json
import os
import re
import subprocess
import sys

HERE = os.getcwd()
KIT = os.path.join(HERE, "kit")
ENV = dict(os.environ, EKIT_STATE=os.path.join(HERE, "state"), GIT_CONFIG_GLOBAL=os.devnull,
           GIT_CONFIG_SYSTEM=os.devnull, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def fail(msg):
    sys.exit(f"ASSERT FAILED: {msg}")


def run(args, cwd=None):
    return subprocess.run(args, capture_output=True, text=True, env=ENV, cwd=cwd, timeout=300)


def sh(args, cwd=None):
    r = run(args, cwd)
    if r.returncode:
        fail(f"{args}: exit {r.returncode}\n{r.stdout}{r.stderr}")
    return r.stdout.strip()


def section(text, heading):
    m = re.search(r"^(#{2,3}) " + re.escape(heading) + r".*$", text, re.M)
    if not m:
        fail(f"SKILL.md has no heading {heading!r}")
    rest = text[m.end():]
    end = re.search(r"^#{2,%d} " % len(m.group(1)), rest, re.M)
    return rest[: end.start()] if end else rest


sh(["git", "clone", "-q", os.environ["EKIT_REPO"], KIT])
skill_path = os.path.join(KIT, "skills", "mistake-to-check", "SKILL.md")
if not os.path.isfile(skill_path):
    fail("the kit ships no skills/mistake-to-check/SKILL.md")
skill = open(skill_path, encoding="utf-8").read()
front = skill.split("---")[1]
if not re.search(r"(?m)^name: mistake-to-check$", front):
    fail("frontmatter name is not mistake-to-check")
if "an agent mistake should become a check" not in front:
    fail("the description does not trigger on an agent mistake that should become a check")
plugin = json.load(open(os.path.join(KIT, ".claude-plugin", "plugin.json"), encoding="utf-8"))
if "./skills/mistake-to-check" not in plugin["skills"]:
    fail("plugin.json does not ship the skill")

# step 2: this run's five mistakes, each with its result
examples = section(skill, "Worked examples")
print("worked examples:" + examples)
for mistake, result in (("RecursionError", "`No check`: an instance"), ("verified one commit", "Process:"),
                        ("layering test's list", "Made impossible:"), ("changelog", "Diff: the co-change rule"),
                        ("macOS", "Environment: no rule")):
    if not re.search(r"(?m)^\| [^|\n]*" + re.escape(mistake) + r"[^|\n]* \| " + re.escape(result), examples):
        fail(f"no worked example row for {mistake!r} with result {result!r}")
flat = " ".join(skill.split())
if flat.index("First make the mistake impossible") > flat.index("| The mistake is about |"):
    fail("routing comes before 'make it impossible'")
finish = open(os.path.join(KIT, "skills", "finish", "SKILL.md"), encoding="utf-8").read()
if "<one line per rule added, promoted or removed in the run, as mistake-to-check wrote it>" not in finish:
    fail("the finish report has no rule lines")

# step 3: the co-change template, filled as written, in a sample repo with an incident
diff = section(skill, "The diff: a co-change rule")
template = re.search(r"```toml\n(.*?)```", diff, re.S)
if not template:
    fail("no co-change template (```toml block)")
template = template.group(1)
command = re.search(r"`(<py> -I <kit>/scripts/mech-review\.py r0 [^`]*)`", diff)
if not command:
    fail("no r0 command line to prove the rule")
command = command.group(1)
print("template:\n" + template + "r0: " + command)

R = os.path.join(HERE, "sample")
os.makedirs(os.path.join(R, "src"))
sh(["git", "init", "-q", "-b", "main", R])


def put(files, msg):
    for name, text in files.items():
        path = os.path.join(R, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    sh(["git", "-C", R, "add", "-A"])
    sh(["git", "-C", R, "commit", "-qm", msg])
    return sh(["git", "-C", R, "rev-parse", "HEAD"])


base = put({"src/app.py": "X = 1\n", "CHANGELOG.md": "# log\n"}, "base")
incident = put({"src/app.py": "X = 2\n"}, "change X, changelog forgotten")


def fill(values):
    text = template
    for placeholder, value in values.items():
        text = text.replace(f'"{placeholder}"', json.dumps(value))
    left = re.findall(r"<[^>\n]*>", text)
    if left:
        fail(f"placeholders the scenario does not know: {left}")
    return "format = 1\n\n" + text


VALUES = {"<what must change together>": "behaviour-docs", "<glob of the path that changed>": "src/**",
          "<glob of a path that should have changed with it>": "CHANGELOG.md",
          "<the rule, as the agent docs state it>": "a behaviour change updates the changelog",
          "<the commit sha, or #N of the PR, that made the mistake>": incident,
          "<a path the incident changed>": "src/app.py", "<a path require matches>": "CHANGELOG.md"}
rule_commit = put({".ekit/co-change.toml": fill(VALUES)}, "co-change rule behaviour-docs")


def r0(head, base_ref):
    argv = command.replace("<py>", sys.executable).replace("<kit>", KIT).replace("<base>", base_ref) \
        .replace("<stack>", "python").replace("HEAD", head).split()
    r = run(argv, cwd=R)
    if "Traceback" in r.stderr:
        fail("r0 traceback:\n" + r.stderr)
    return r, json.loads(r.stdout) if r.stdout else None


MR = os.path.join(KIT, "scripts", "mech-review.py")


def r2(base_ref, head):
    r = run([sys.executable, "-I", MR, "r2", "--repo", R, "--base", base_ref, "--head", head, "--stack", "python",
             "--test-paths", "tests/**"])
    if "Traceback" in r.stderr or not r.stdout:
        fail(f"r2: exit {r.returncode}\n{r.stderr}")
    return r, json.loads(r.stdout)


r, env = r0(rule_commit, incident)
cases = [(c["case"], c["status"]) for c in env["checks"]["R0"].get("co-change", [])]
print(f"r0: exit {r.returncode}, co-change cases {cases}")
if cases != [("behaviour-docs:flagged", "pass"), ("behaviour-docs:control", "pass")]:
    fail(f"the filled template does not prove itself: {cases}\n{r.stdout}")
r, env = r2(incident, rule_commit)
on_rule = [e for e in env["entries"] if e["file"] == ".ekit/co-change.toml"]
if on_rule:
    fail(f"r2 guards the new rule: {on_rule}")

# step 4: the next PR repeats the mistake; a PR that updates the changelog too does not
again = put({"src/app.py": "X = 3\n"}, "change X again, changelog forgotten again")
r, env = r2(rule_commit, again)
got = [(e["severity"], e["class"]) for e in env["entries"] if "behaviour-docs" in e["problem"]]
print(f"repeat: exit {r.returncode}, entries {got}")
if r.returncode != 0 or got != [("confirm", "agent-fixable")]:
    fail(f"the repeat: want exit 0 and one confirm entry, got exit {r.returncode}: {env['entries']}")
sh(["git", "-C", R, "reset", "-q", "--hard", rule_commit])
good = put({"src/app.py": "X = 3\n", "CHANGELOG.md": "# log\n- X is 3\n"}, "change X, with its changelog")
r, env = r2(rule_commit, good)
if [e for e in env["entries"] if "behaviour-docs" in e["problem"]]:
    fail(f"a PR that updates the changelog is flagged: {env['entries']}")

# step 5: misuse: a control case that leaves out the required path fails R0, named
bad = put({".ekit/co-change.toml": fill(dict(VALUES, **{"<a path require matches>": "README.md"}))}, "bad control")
r, env = r0(bad, good)
named = [e["problem"] for e in env["entries"] if e["check"] == "R0" and "behaviour-docs" in e["problem"]]
print(f"bad control: {named}")
if not named or "control" not in named[0]:
    fail(f"r0 does not fail the misfilled rule's control case: {env['entries']}")

# step 6: the gate route: a result for another commit is refused
VC = os.path.join(KIT, "scripts", "verified-commit.py")
for head, want in ((incident, 1), (bad, 0)):
    path = os.path.join(HERE, f"result-{want}.json")
    with open(path, "w") as f:
        json.dump({"head": head, "summary": "pass"}, f)
    r = run([sys.executable, "-I", VC, path, R])
    print(f"verified-commit (result head {head[:12]}): exit {r.returncode} {r.stdout.strip()} {r.stderr.strip()}")
    if r.returncode != want:
        fail(f"verified-commit: want exit {want}, got {r.returncode}")
    if want == 1 and not (incident in r.stdout + r.stderr and bad in r.stdout + r.stderr):
        fail("verified-commit's refusal does not name both commits")
print("OK")
