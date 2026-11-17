# gate/stale-after-edit: misuse, edit after PASS

- story: As a user I pass scenarios, then keep editing; the gate blocks again until I re-run.
- covers: #9 misuse scenario; gate rejects a stale PASS
- steps: reuse parent flow: installed kit, fresh PASS and a green verify command (`scripts/task-verify.py`), then edit a file; Stop hook; re-run scenarios; Stop hook with the report; re-run the verify command; Stop hook with the report.
- expected: block mentioning "stale" after the edit; with only the scenarios re-run, the report is blocked because the verify pass predates the edit; allow once both are re-run.
