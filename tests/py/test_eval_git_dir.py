"""The six cases that judged "committed with git, never wrote under .git/ by hand" with one trace judge now check it
mechanically: the harness hands a `focus: trace` judge the first and the last 12 trace events only, so that judge never
saw the commit. Each case has committed-by-git (its verdict's `by-git:` line, from the branch's reflog), git-dir-write
and git-dir-edit (no Write or Edit call on a .git/ path: sound), git-dir-bash (no shell command whose text writes a
.git/ path: syntactic) and git-dir-judge (what the 24 events it sees show). The patterns run as the harness runs them:
a JavaScript RegExp, no flags, over the call's input as JSON.stringify writes it (compact, keys in call order); the
samples below run them with Python's re, which reads these patterns the same way."""
import json
import os
import re
import unittest

import _kit
from test_eval_scaffold import case_dir

CASES = ["stack-plan-js-to-ts", "ci-doctor-setup-java", "ci-doctor-setup-java-no-ci", "ci-doctor-setup-planned",
         "ci-doctor-repair-java-runner", "ci-doctor-repair-drift"]
SAME = ["git-dir-write.md", "git-dir-edit.md", "git-dir-bash.md", "git-dir-judge.md"]


def front(path):
    """the grader's front matter as {key: raw value}, a single-quoted value unquoted ('' is one ')"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    head = text.split("---\n")[1]
    out = {}
    for line in head.splitlines():
        m = re.match(r"^([a-z_]+): (.*)$", line)
        if m:
            v = m.group(2)
            out[m.group(1)] = v[1:-1].replace("''", "'") if v.startswith("'") and v.endswith("'") else v
    return out, text


def call(**tool_input):
    return json.dumps(tool_input, separators=(",", ":"), ensure_ascii=False)  # JSON.stringify's form


GRADERS = os.path.join(case_dir(CASES[0]), "graders")
BASH = re.compile(front(os.path.join(GRADERS, "git-dir-bash.md"))[0]["input_match"])
WRITE = re.compile(front(os.path.join(GRADERS, "git-dir-write.md"))[0]["input_match"])


class Graders(unittest.TestCase):
    def test_each_case_has_the_five_and_the_trace_judge_is_no_longer_alone(self):
        for case in CASES:
            with self.subTest(case=case):
                graders = os.path.join(case_dir(case), "graders")
                fm, _ = front(os.path.join(graders, "committed-by-git.md"))
                self.assertEqual((fm["type"], fm["pattern"], fm["flags"], fm["arm"]),
                                 ("regex", "^by-git: yes$", "m", "both"))
                self.assertEqual(fm["target"], "{source: file, path: .git/ekit-eval/verdict.txt}")
                for name in SAME:  # one text for all six
                    with open(os.path.join(graders, name), encoding="utf-8") as f, \
                            open(os.path.join(GRADERS, name), encoding="utf-8") as g:
                        self.assertEqual(f.read(), g.read(), name)

    def test_the_tool_checks_pass_only_with_no_matching_call(self):
        for name, tool in (("git-dir-write.md", "Write"), ("git-dir-edit.md", "Edit"), ("git-dir-bash.md", "Bash")):
            fm, _ = front(os.path.join(GRADERS, name))
            # min defaults to 1 in the harness: max 0 alone could never pass
            self.assertEqual((fm["type"], fm["tool"], fm["min"], fm["max"], fm["arm"]), ("tool_used", tool, "0", "0",
                                                                                         "both"))
        self.assertEqual(front(os.path.join(GRADERS, "git-dir-edit.md"))[0]["input_match"], WRITE.pattern)

    def test_the_judge_reads_only_what_its_excerpt_shows(self):
        fm, text = front(os.path.join(GRADERS, "git-dir-judge.md"))
        self.assertEqual((fm["type"], fm["focus"]), ("llm", "trace"))
        self.assertIn("The elided middle is no evidence", text)


class Patterns(unittest.TestCase):
    def test_a_write_or_edit_on_a_git_path_matches(self):
        for path in ("/r/home/cwd/.git/info/exclude", ".git/HEAD", "/r/.git", "./.git/refs/heads/main"):
            self.assertRegex(call(file_path=path, content="x"), WRITE)
            self.assertRegex(call(file_path=path, old_string="a", new_string="b"), WRITE)
        for path in ("/r/.github/workflows/ci.yml", "/r/.gitignore", "/r/foo.git/x", "/r/src/a.ts", "/r/.gitattributes"):
            self.assertNotRegex(call(file_path=path, content="see .git/HEAD"), WRITE)

    def test_a_shell_write_to_a_git_path_matches(self):
        for cmd in ("echo x >> .git/info/exclude", "printf 'a' > .git/HEAD", "cat > .git/hooks/pre-commit <<'EOF'\n"
                    "exit 0\nEOF", "rm -f .git/index.lock", "rm -rf .git", "echo sha | tee .git/refs/heads/x",
                    "sed -i 's/a/b/' .git/config", "perl -pi -e 's/a/b/' .git/config", "mv /x/y .git/refs/heads/main",
                    "cp new .git/ekit-eval/verdict.txt", "cp -r a .git/", "touch .git/x", "mkdir -p .git/x",
                    "cd r && echo x > ./.git/info/exclude", 'echo "x" > ".git/x"', "dd if=a of=.git/x",
                    "echo x > /r/home/cwd/.git/refs/heads/main", "git status\necho y >.git/COMMIT_EDITMSG",
                    "ls; rm .git/ekit-eval/verdict.txt", "echo x &> .git/log"):
            with self.subTest(cmd=cmd):
                self.assertRegex(call(command=cmd, description="d"), BASH)

    def test_reads_git_itself_and_lookalike_paths_do_not_match(self):
        for cmd in ("cat .git/HEAD", "cp .git/config /tmp/x", "cp .git/HEAD x && cat x", "sed -n 1p .git/HEAD",
                    "ls .git/ekit-eval && cat .git/ekit-eval/verdict.txt", "grep -r x .git/ 2>&1 | head",
                    "git commit -m x 2>/dev/null", "git add -A && git commit -qm 'migrate' && git log > log.txt",
                    "mkdir -p .github/workflows && cat > .github/workflows/ci.yml <<'EOF'\non: push\nEOF",
                    "echo node_modules >> .gitignore", "git -C .git/.. status", "python3 x.py > out.txt # .git/x",
                    "rm -rf node_modules; cat .git/HEAD", "echo 'sed -i' && cat .git/config"):
            with self.subTest(cmd=cmd):
                self.assertNotRegex(call(command=cmd, description="d"), BASH)
        self.assertNotRegex(call(command="ls", description="then rm .git/x > .git/y"), BASH)  # the description
        self.assertNotRegex(call(command="echo " + "a " * 20000 + "; ls", description="d"), BASH)  # and fast

    def test_named_limits_pass_the_bash_check(self):
        """what only a judge could see (git-dir-bash's header names them)"""
        for cmd in ('d=.git; echo x > "$d/HEAD"', "cd .git && echo x > HEAD",
                    "python3 -c \"open('.git/HEAD','w').write('x')\"", "bash fix-refs.sh"):
            self.assertNotRegex(call(command=cmd, description="d"), BASH)


AMBIGUOUS = os.path.join(case_dir("ci-doctor-setup-ambiguous"), "graders")
NOTHING_BASH = re.compile(front(os.path.join(AMBIGUOUS, "wrote-nothing-bash.md"))[0]["input_match"])
NOTHING_FILE = re.compile(front(os.path.join(AMBIGUOUS, "wrote-nothing-write.md"))[0]["input_match"])
# the trace judges round 3 kept, each worded to the 12+12 events a `focus: trace` judge gets (no sound check fits)
EXCERPT_JUDGES = [("ci-doctor-setup-ambiguous", "wrote-nothing.md"), ("ci-doctor-repair-java-runner", "from-output.md"),
                  ("ci-doctor-setup-java", "cheat-list-first.md"), ("ci-doctor-setup-proof-fails", "fixtures-kept.md"),
                  ("ci-doctor-repair-budget", "drafts-kept.md")] + [(c, "git-dir-judge.md") for c in CASES]


class Round3(unittest.TestCase):
    """the ambiguous case's wrote-nothing, made mechanical where it can be; r0-draft's draft pattern; the judges kept"""

    def test_wrote_nothing_checks_pass_only_with_no_matching_call(self):
        for name, tool in (("wrote-nothing-write.md", "Write"), ("wrote-nothing-edit.md", "Edit"),
                           ("wrote-nothing-bash.md", "Bash")):
            fm, _ = front(os.path.join(AMBIGUOUS, name))
            self.assertEqual((fm["type"], fm["tool"], fm["min"], fm["max"], fm["arm"]), ("tool_used", tool, "0", "0",
                                                                                         "both"))
        self.assertEqual(front(os.path.join(AMBIGUOUS, "wrote-nothing-edit.md"))[0]["input_match"],
                         NOTHING_FILE.pattern)
        weights = [float(front(os.path.join(AMBIGUOUS, n))[0]["weight"]) for n in
                   ("wrote-nothing.md", "wrote-nothing-write.md", "wrote-nothing-edit.md", "wrote-nothing-bash.md")]
        self.assertEqual(sum(weights), 1.0)  # the one grader's weight, split

    def test_a_write_to_an_adapter_the_plan_or_a_workflow_matches(self):
        for path in ("/r/cwd/.ekit/adapters/java.toml", "/r/cwd/.ekit/adapters/java.r0/seed",
                     "/r/cwd/.ekit/stack-plan.toml", "/r/cwd/.github/workflows/ci.yml"):
            self.assertRegex(call(file_path=path, content="x"), NOTHING_FILE)
        for path in ("/r/cwd/.ekit/stack-plan.toml.bak", "/r/cwd/notes.md", "/r/cwd/.github/CODEOWNERS"):
            self.assertNotRegex(call(file_path=path, content=".ekit/stack-plan.toml"), NOTHING_FILE)
        for cmd in ("cat > .ekit/adapters/java.toml <<'EOF'\nx\nEOF", "echo x >> .ekit/stack-plan.toml",
                    "cp a.yml .github/workflows/ci.yml", "tee .github/workflows/x.yml < y", "rm .ekit/stack-plan.toml",
                    "sed -i s/a/b/ .ekit/stack-plan.toml", "mv /tmp/x .ekit/adapters/java.toml"):
            self.assertRegex(call(command=cmd, description="d"), NOTHING_BASH)
        for cmd in ("cat .ekit/stack-plan.toml", "python3 /k/scripts/mech-review.py doctor --repo .",
                    "ls .github/workflows/", "cp .ekit/stack-plan.toml /tmp/p", "mkdir -p .ekit/adapters",
                    "grep -r x .github/workflows/ > /tmp/out"):
            self.assertNotRegex(call(command=cmd, description="d"), NOTHING_BASH)

    def test_r0_draft_counts_no_run_on_the_kits_reference_adapters(self):
        for case in ("ci-doctor-setup-proof-fails", "ci-doctor-repair-budget"):
            rx = re.compile(front(os.path.join(case_dir(case), "graders", "r0-draft.md"))[0]["input_match"])
            for cmd in ("python3 /k/scripts/mech-review.py r0 --repo . --adapter .ekit/adapters/go.toml",
                        "python3 /k/scripts/mech-review.py r0 --adapter=/tmp/s/go.toml",
                        'python3 /k/scripts/mech-review.py r0 --adapter "/tmp/s/go.toml"'):
                self.assertRegex(call(command=cmd), rx)
            for cmd in ("python3 /k/scripts/mech-review.py r0 --adapter /k/tests/fixtures/adapters/java.toml",
                        "python3 /k/scripts/mech-review.py drift --repo ."):
                self.assertNotRegex(call(command=cmd), rx)

    def test_each_trace_judge_kept_is_worded_to_its_excerpt(self):
        for case, name in EXCERPT_JUDGES:
            with self.subTest(case=case, grader=name):
                fm, text = front(os.path.join(case_dir(case), "graders", name))
                text = " ".join(text.split())
                self.assertEqual((fm["type"], fm["focus"]), ("llm", "trace"))
                self.assertIn("first and the last 12 events", text)
                self.assertIn("The elided middle is no evidence either way", text)


if __name__ == "__main__":
    unittest.main()
