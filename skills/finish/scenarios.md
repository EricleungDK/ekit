# Scenario-backed criteria

Repo with `.ekit/scenarios/` (taste-it skill): a scenario-backed criterion is verified by the runner, never the taster's say-so. Run `RUN run`, then `RUN check`. Evidence: the `PASS`/`FAIL` line, the results.json or transcript path, tree hash fresh (`check` exit 0). Any `FAIL`, stale or partial `check` (exit 1) = not done: no ✅ row, no plain "done"; a fix-class FAIL stays an agent job (fix, full `RUN run`, `RUN check`), listed under Open, never handed to the user as a question or check.
