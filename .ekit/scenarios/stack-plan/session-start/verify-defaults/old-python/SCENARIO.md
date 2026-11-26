# stack-plan/session-start/verify-defaults/old-python: on python older than 3.11 the session gets one line naming the version needed and no default is declared

- story: As a developer whose `python3` is 3.9, a session in a repo with stacks starts with one line telling me the default verify commands need python 3.11 or newer, and no half-read command is declared for me, so I declare them per task.
- covers: #61 61.5 (on Python older than 3.11 one line names the version needed and nothing is declared: with a plan, with the one project `auto` finds, with a repo adapter file)
- steps:
  1. Parent's install. The hooks' `python3` is 3.9: the clone's SessionStart command run under `uv run --offline --no-project --python 3.9` (uv's installed 3.9), else a `python3.9`/`python3.10` on PATH put first as `python3`; none is unrunnable here, not a pass.
  2. Three repos: a plan of two current stacks (`web` adapter file with build and lint, `api` python); no plan with a root jest package.json; no plan with `.ekit/adapters/tool.toml` naming build and test.
- expected: hook exit 0, no traceback; exactly one `[ekit] Verify defaults` line, `none declared`, naming 3.11 and the python's version, no `task-verify.py --repo` run line; `task-verify.py check` says no verify command was declared for the session. All three repos.
