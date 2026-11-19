# mech-review-baseline/shard-count: the baseline sizes the shards from its measured time: one for a small PR, at most 4 for a large one, never more than the mutants, none empty

- story: As a repo owner I let the `baseline` step pick the shard count: a small PR gets one shard (no wasted jobs), a large one at most 4, never more shards than mutants under the cap, and every shard it asks for has mutants to run.
- covers: #26 B3 (count = min(4, mutants, ceil(estimated minutes / (budget / 2))) from the baseline's measured build + test time; small PR 1, large at most 4; never an empty shard (rust)); B1 (the large PR's shards together test the 40 riskiest once each, merge `partial (40/60)`)
- steps:
  1. Repo and fake cargo-mutants from `mech-review-mutants/fixtures/cap.sh` (60 listed mutants); the fake's baseline-only run writes the measured build and test seconds.
  2. `baseline` with baseline 1+1 s: `count` 1 (also with `--shards 4`). 10+5 s: 2. 60+60 s: 4; 600+600 s: 4 (with and without `--shards 4`, the workflow's ceiling). 60+60 s with `--mutation-budget 60`: 3.
  3. 60+60 s with `--max-mutants 3`: 2; `--max-mutants 1`: 1. A 2-mutant listing at 600+600 s: 2.
  4. Run the large PR's 4 shards (`mutants --shard k/4`): each runs at least one mutant, 40 in all, none twice; `merge --shards 4`: exit 0, `partial: R3 (40/60)`.
- expected: counts as above; no traceback.
