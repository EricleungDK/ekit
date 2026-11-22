# Scenario-backed criteria

Repo with `.ekit/scenarios/` (taste-it skill): a scenario-backed criterion is verified by the runner, never the taster's say-so. Run `RUN run`, then `RUN check`. Evidence: the `PASS`/`FAIL` line, the results.json or transcript path, tree hash fresh (`check` exit 0). Any `FAIL`, stale or partial `check` (exit 1) = not done (a seeding task excepted, below): no ✅ row, no plain "done"; a fix-class FAIL stays an agent job (fix, full `RUN run`, `RUN check`), listed under Open, never handed to the user as a question or check.

Features: with a `- feature:` marker on any scenario (taste-it's seeded ones), a fresh `RUN check` ends with `N of M features working`. Copy that line into the report as printed, in either branch; never count by hand. `RUN check` printed no such line → leave the line out. N below M = not done for a task that claims the features built: a feature the user asked for does not work yet.

A seeding task (taste-it §7: scenarios written, no feature built) is done when each written scenario's last `RUN seeded <id>` is `SEEDED ✓` and `RUN check` prints `0 of M features working`: its criteria are the seeded scenarios, each row's evidence its `SEEDED ✓` line. Its `FAIL`s are the point, not a red to fix. A `CHECKS NOTHING YET` or a seeded scenario that fails for another reason is still to fix.
