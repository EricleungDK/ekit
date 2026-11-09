# gate/failing-scenario: misuse, red scenario

- story: As a user whose scenario fails, the gate keeps blocking, and a repo with no scenarios dir is not forced into taste-it.
- covers: #9 misuse scenario; gate blocks on FAIL
- steps: installed kit, scenario exits 1, edit file, run runner (FAIL), Stop hook.
- expected: block "last run FAIL". Separately, a plain repo (no .ekit/scenarios) with an edit is asked for the finish report, not "Scenarios not green", and may stop once the last message is that report.
