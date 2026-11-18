# mech-review-doctor/sandbox/tests-links: a tracked link under tests/ that mutmut's copy cannot follow is a prompt, named entry; a link to an existing file outside the repo is fine

- story: As a Python repo owner with a stray symlink in `tests/` (back up to the repo, or dangling), doctor answers in seconds and names the link instead of hanging or crashing; a link to a real file elsewhere on my machine does not fail me.
- covers: issue #7 criterion 5d (a tracked link under `tests/` to a parent dir (`tests/up -> ..`, `tests/sub/root -> ../..`) or dangling: a prompt sandbox-copy entry naming the link, no hang, no traceback; a link under `tests/` to an existing file outside the repo (`/etc/hosts`) does not cause a failure); 5e (writes nothing, no extra worktree); misuse/failure
- steps:
  1. Parent's venv install. For each link, a fresh root repo with the caller doctor asks for and one tracked link under `tests/`; the suite passes in the checkout. `doctor --repo` under a 90 s limit, timed.
  2. Links: `tests/up -> ..`, `tests/sub/root -> ../..`, `tests/gone -> nowhere/data.txt` (dangling).
  3. Links that must pass: `tests/hosts -> /etc/hosts`, `tests/ext -> <dir outside the repo>` holding a file.
- expected: step 2 each exit 1 within 30 s, tests `pass`, sandbox `fail`, one `env` entry whose problem says the sandbox copy fails and names the link (`tests/up`, `tests/sub/root`, `tests/gone`). Step 3 exit 0, sandbox `pass`, summary `ok <head>`. Every run: no traceback, git state unchanged, one worktree, temp dir empty.
