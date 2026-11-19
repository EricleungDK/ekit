# mech-review-mutants/cap: over `--max-mutants` the riskiest run, the same set every run, R3 partial; shards split the pick; a budget cut is untested, not MISSED

- story: As a repo owner whose PR makes more mutants than the cap, R3 tests the riskiest ones, picks the same set on every run, reads `partial (tested/total)` instead of `pass`, splits the pick over shards without testing a mutant twice, and never calls a mutant the budget did not reach MISSED.
- covers: #26 B1 (cap, default 40, same pick on every run and after a shuffled listing, risk order: branch conditions, then returns, then arithmetic and the rest; over the cap `partial (tested/total)`, never `pass`); B2 (budget cut-off: unreached mutants partial with no MISSED entry; a mutant that ran and survived is still MISSED); B3 (shards over the cap: each mutant in one shard, merge counts each once, partial); B5 (within the cap: pass n/n, MISSED fails, cargo-mutants' own argv with no `--re`)
- steps:
  1. Parent's repo (head changes `src/lib.rs`). Fake cargo-mutants (`fixtures/fake_cargo_mutants.py`, MECH_TEST_STUB) answers `--list --json` from a 60-mutant listing (10 functions x: `>`->`==`, `delete !`, match guard (branch conditions), `-> bool with true` (return), `+`->`-` (arithmetic), `delete match arm` (rest)) and runs the mutants named by `--re` or `--shard`, logging each it ran.
  2. `mutants --max-mutants 5`: expect exit 0, R3 partial, `partial: R3 (5/60)`, note `55 past the cap (max-mutants 5): untested`, and exactly the branch mutants of f0 and the first two of f1 ran.
  3. Same with the listing shuffled (two seeds): the same 5 ran, same summary.
  4. No flag (default 40): 40/60 partial; the 30 branch conditions and 10 returns ran, no arithmetic, no match arm.
  5. A survivor among the pick: exit 1, MISSED entries for exactly those two; a survivor only past the cap: partial, no MISSED.
  6. `--max-mutants 60` (within the cap): pass, no cap note, no `--re` in the run argv; a survivor there is MISSED (10 entries).
  7. `--max-mutants 12` on shards 0/3, 1/3, 2/3: the 12 riskiest ran once each; `merge --shards 3`: exit 0, `partial: R3 (12/60)`, no CI entry; a survivor in shard 1 is one MISSED entry in the merge.
  8. Budget cut: the tool runs 3 mutants then hangs, budget 0.05 min. Survivor only in f3 (never reached): exit 0, partial (3/60), no MISSED. Survivors in f0 and f3: exit 1, the f0 one is MISSED, the f3 one is not.
- expected: exit codes, summaries and ran-sets as above; never `pass` or `all pass` with untested mutants; the caller checkout untouched.
