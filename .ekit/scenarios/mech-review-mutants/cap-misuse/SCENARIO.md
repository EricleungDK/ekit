# mech-review-mutants/cap-misuse: misuse, bad cap/budget/shard flags are usage errors; a config or listing that defeats the pick is n/a, never pass

- story: As a repo owner who mistypes `max-mutants`, `mutation-budget` or a shard index, or whose crate has an `examine_re` or a listing that fails, I get a clear usage error or an honest `n/a`/`partial`, never a traceback and never a `pass` over untested mutants.
- covers: #26 B1 misuse (`--max-mutants` 0, -1, abc, empty, 1.5: exit 2; `--mutation-budget` nan, inf: exit 2; `--shard` past the count: exit 2; declared limit: `examine_re` in `.cargo/mutants.toml` -> R3 `n/a (env)` naming `examine_re`, shard too, merge not pass); B3 misuse (`--shards 0`: exit 2; an empty share reads `0 mutants in this shard`, runs nothing); failure: a `--list` that fails is `n/a (env)` (shard run and baseline, no shards); budget 0 never pass
- steps:
  1. Parent's repo and fake cargo-mutants (60 listed mutants).
  2. `mutants` and `baseline` with `--max-mutants` 0, -1, abc, '', 1.5: exit 2, empty stdout, `want a whole number >= 1`, no traceback.
  3. `--mutation-budget` nan, inf, NaN: exit 2, `finite number`. `--shard` 3/3, 5/3, 0/0, a/b: exit 2, `want K/N with 0 <= K < N`. `baseline --shards 0`: exit 2.
  4. The fake also runs the `+`->`-` mutants (what `examine_re` does): `--max-mutants 5` gives exit 0, R3 n/a, note names `examine_re` and `(env)`, summary `n/a: R3`; a shard 1/2 likewise, and merging it with a good shard 0 is not pass.
  5. `--list` exits 1: `mutants` (and shard 1/2) R3 n/a, note `--list failed (env)`; `baseline` n/a with `run` false.
  6. `--max-mutants 5 --shard 9/10`: note `0 mutants in this shard`, nothing run.
  7. `--mutation-budget 0`: R3 not pass.
- expected: as above; no traceback anywhere; the caller checkout untouched.
