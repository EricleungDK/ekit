# mech-review-ts/cap/budget: failure, a Stryker run the budget stops is partial with no MISSED for unreached mutants, never pass

- story: As a TypeScript repo owner whose Stryker run hits `mutation-budget`, R3 says `partial` and counts what is untested; it never reports MISSED for a mutant Stryker had not reached, never reads `pass`, and still fails on a mutant that really ran and survived, capped or not.
- covers: #63 63.3 (a run stopped at the budget: R3 `partial (tested/total)`, no MISSED for unreached mutants, never `pass`; before the report: `partial` with the listed total 14, tested unknown; after a report with Pending mutants: `partial (2/14)`, entry `R3 partial: 12/14 mutants untested`; a mutant that ran and survived is still MISSED); 63.1 (a run that makes more mutants on the picked lines than were listed did not keep the cap: `n/a`, never pass; under the budget stop the capped note still names the mutants past the cap)
- steps:
  1. Parent's kit clone, fake Stryker install and repo (14 mutants on the changed lines of two files).
  2. For `--max-mutants 5` and for no cap, `mutants --stack ts --mutation-budget 0.05` with the fake Stryker hanging before it writes a report, every mutant set to survive: exit 0, R3 partial, `total` 14, no MISSED, summary names `partial: R3`.
  3. The fake writes a report with 2 mutants done and the rest Pending, then hangs: exit 0, `partial: R3 (2/14)`, no MISSED, entry `R3 partial: 12/14 mutants untested`.
  4. The same with every string and condition set to survive: exit 1, R3 fail, exactly one MISSED: the one that ran (capped: `src/grade.ts:6` ConditionalExpression; uncapped: `src/grade.ts:2` StringLiteral); the Pending survivors are not MISSED.
  5. Capped, the note still says `9 past the cap (max-mutants 5): untested`.
  6. A Stryker run that makes one more mutant on the picked lines than the instrumenter listed (cap 3, every mutant killed): exit 0, R3 `n/a` (not pass), note `the cap was not kept`, summary `n/a: R3`.
- expected: as above; no traceback; the checkout untouched.
