# Scenario-backed criteria

Repo with `.ekit/scenarios/` (taste-it skill): a scenario-backed criterion is verified by the runner, never the taster's say-so. Run `RUN run`, then `RUN check`. Evidence: the `PASS`/`FAIL` line, the results.json or transcript path, tree hash fresh (`check` exit 0). Any `FAIL`, stale or partial `check` (exit 1) = not done: no ✅ row, no plain "done"; a fix-class FAIL stays an agent job (fix, full `RUN run`, `RUN check`), listed under Open, never handed to the user as a question or check.

Features: with a `- feature:` marker on any scenario (taste-it's seeded ones), a fresh `RUN check` ends with `features: N of M working`. Copy it into the report's `Features:` line as printed; never count by hand. `RUN check` printed no such line → leave the line out. N below M = not done: a feature the user asked for does not work yet.
