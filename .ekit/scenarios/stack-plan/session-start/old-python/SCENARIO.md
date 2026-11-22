# stack-plan/session-start/old-python: on python older than 3.11 the session gets one line saying the drift check needs 3.11+ and CI still runs it

- story: As a developer whose hooks run on python 3.9 or 3.10, a repo with a stack plan starts my session with one line telling me the drift check needs python 3.11 or newer and that CI still runs it, instead of a crash or a silence that reads as clean; my other session lines stay as they are.
- covers: #57 57.2 (on Python older than 3.11 one line says the drift check needs 3.11+ and CI still runs it; never a crash, never clean); 57.1 (a repo with no plan adds nothing, on this python too); misuse/failure (`drift` itself on that python: exit 2 naming 3.11, never pass)
- steps:
  1. Parent's install. A python older than 3.11 found offline: `uv python find --offline 3.10`, then 3.9 (uv's installed pythons, no download), else `python3.10`/`python3.9` on PATH; none is unrunnable here, not a pass.
  2. With that python, the SessionStart hook (payload on stdin, `CLAUDE_PLUGIN_ROOT` set) in three repos: a plan that leaves `api/pyproject.toml` uncovered, a clean plan, a plan with status `done`.
  3. The same hook in a repo with no plan.
  4. `drift --base C --head C` with that python on a repo with a plan.
- expected: step 2 hook exit 0, no traceback, exactly one `[ekit] Stack plan` line naming 3.11, the python's version and `CI still runs the drift check`, no `drift at HEAD` header or `unchecked manifest` line, in all three. Step 3 no `Stack plan` line, and its context equals step 2's first context without that line. Step 4 exit 2, stderr naming 3.11, no `pass` summary.
