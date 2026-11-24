# mech-review-doctor/sandbox: with real pytest and mutmut, doctor's trial also runs the tests in R3's mutmut sandbox copy

- story: As a Python repo owner I install pytest and mutmut as CI does and run `doctor`: tests that read a tracked top-level `docs/` file and load a tracked `scripts/x.py` by path pass in the sandbox and doctor says `ok`; when my plain tests fail there is no sandbox verdict to trust, so it says `skipped`; either way my repo is left as it was.
- covers: issue #7 criterion 5b (project at the root, tests read tracked `docs/usage.md` and load tracked `scripts/tool.py` by path: exit 0, `ok <head>`, `trial.sandbox` pass); 5e (doctor writes nothing, leaves no extra worktree or temp dir; plain tests that fail give `sandbox` skipped); misuse/failure (failing suite)
- steps:
  1. Fresh venv in the temp dir: `pip install --no-index pytest==9.2.0 mutmut==3.8.1` from wheels pip builds once per machine and Python in `${XDG_CACHE_HOME:-~/.cache}/ekit-scenarios/` (no network after that; the unpinned transitive deps, coverage, libcst and the rest, stay at that first build's versions: delete the dir to refresh them), venv first on PATH (real tools, no stub).
  2. Repo at the root, src layout, the caller doctor asks for (`stack: python`, `test-paths: tests/**`); tests read `docs/usage.md` and load `scripts/tool.py` with `spec_from_file_location`, relative to `__file__`. The suite passes in the checkout. `doctor --repo` (and again with `--stack python`), each under a 90 s limit.
  3. A second repo the same but `test_add` asserts a wrong value. `doctor --repo`.
- expected: step 2 exit 0, trial `{"tests":"pass","command":"python3 -m pytest","mutation_tool":"present","sandbox":"pass"}`, no entries, summary `ok <head>`. Step 3 exit 1, tests `fail`, sandbox `skipped`, an entry naming `python3 -m pytest`. Every run: no traceback, no hang, git state unchanged, one worktree, temp dir empty.
- children: above-project-dir, docs-link, tests-links
