# mech-review-doctor/sandbox/docs-link: a tracked docs/ link that does not resolve in a fresh checkout keeps docs/ out of R3's copy; doctor names the file and the link

- story: As a Python repo owner whose tests read `docs/usage.md` while `docs/html -> ../_build/html` points at a gitignored build dir, doctor tells me both the file the sandbox is missing and the link that causes it, and how to fix it, even when my own checkout has `_build/html` built.
- covers: issue #7 criterion 5c (tests read `docs/usage.md`, `docs/` holds a tracked link `docs/html -> ../_build/html`, `_build/` gitignored: doctor fails, the entry names `docs/usage.md` and `docs/html`, hint to track the target or remove the link); criterion 5 (an `env` entry naming the missing files, not `ok`); 5e (writes nothing, no extra worktree, ignored files untouched); misuse/failure
- steps:
  1. Parent's venv install. Repo at the root, the caller doctor asks for, a test reading `docs/usage.md`, `.gitignore` with `_build/`, tracked link `docs/html -> ../_build/html`. The suite passes in the checkout. `doctor --repo` under a 90 s limit.
  2. Build the target in the checkout (`_build/html/index.html`, ignored). `doctor --repo` again.
  3. Control: the same repo without the link. `doctor --repo`.
- expected: steps 1 and 2 exit 1, tests `pass`, sandbox `fail`, one `env` entry whose problem names `docs/usage.md` and `docs/html` and whose hint says to track the target or remove the link; summary `fail <head> (1 problems)`. Step 3 exit 0, sandbox `pass`. Every run: no traceback, git state (ignored files included) unchanged, one worktree, temp dir empty.
