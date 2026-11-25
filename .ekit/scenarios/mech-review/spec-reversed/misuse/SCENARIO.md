# mech-review/spec-reversed/misuse: misuse, a bad `--linked-issue` or one on a subcommand that does not run R2 is a usage error

- story: As a user wiring `--linked-issue` into my workflow I mistype the value (`abc`, `0`, `-1`, `##53`, `53x`, a space, non-ASCII digits, nothing) or pass it to `red`, `mutants`, `plan`, `baseline` or `merge`, and each time get exit 2 with the flag named, never a result I could read as a pass and never a silently ignored flag.
- covers: #53 misuse (bad values and a subcommand that does not run R2 fail clearly with a usage error, not silently); docs (`N` or `#N`, ASCII digits, N >= 1; another subcommand given it is a usage error); odd but valid (the same issue given twice)
- steps:
  1. Parent's python repo; head drops `test_keeps` with `spec: #53 reverses test_keeps`.
  2. `r2 --linked-issue <v>` for `0`, `#0`, `-1`, `abc`, ``, `#`, `##53`, `53x`, `5 3`, ` 53`, `+53`, `53.0`, Arabic-Indic and full-width digits; `53` plus `x`; the flag with no value.
  3. `red`, `mutants`, `plan`, `baseline`, `merge` with `--linked-issue 53`.
  4. `--linked-issue 53 --linked-issue '#53'`; `--linked-issue 999999`.
- expected: steps 2-3 exit 2, empty stdout, stderr names `--linked-issue` (step 2 quotes the bad value; step 3 says it applies to r2 and all), no traceback. Step 4: one confirm exit 0; an unlinked large N exit 1.
