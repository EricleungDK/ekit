# mech-review/spec-reversed: a test removed because the linked spec reverses it is one R2 `confirm`, not the `fail`

- story: As a repo owner whose agent removed a test the issue's spec reverses (even a one-line test it cannot rename), I put `spec: #N reverses <test name>` in a commit message, pass the issue the PR closes as `--linked-issue N`, and R2 gives me one `confirm` that names the test and #N and tells me to confirm only against a quoted sentence of #N, instead of a `fail`.
- covers: #53 C1 (a removed test, a commit message line in base..head `spec: #N reverses <test name>`, N passed as `--linked-issue N`: exactly one R2 `confirm` instead of the `fail`; a one-line test; the confirm names the test and #N and says to confirm only against a quoted sentence of #N); docs: `N` or `#N`, repeatable, the lowest N when several linked lines name one test, R2's exact name (`Class::test_fn` in python), `all` takes the flag, the line waives nothing else
- steps:
  1. Python repo, `tests/test_m.py` with one-line tests `test_adds` and `test_keeps`. Head drops `test_keeps`, its commit body says `spec: #53 reverses test_keeps`. `r2 --stack python --linked-issue 53`, then `--linked-issue '#53'`, then `--linked-issue 61 --linked-issue 53`, then no flag.
  2. The spec line in an earlier commit, an unrelated commit after it.
  3. Two linked lines (#61, #53) for the one test, both linked.
  4. A unittest class: `spec: #7 reverses TestCalc::test_keeps`, `--linked-issue 7`.
  5. Rust one-line `fn keeps() { assert_eq!(2 + 2, 4); }` removed, `spec: #53 reverses keeps`; with and without the flag.
  6. Two tests removed, a line for each; then only one named.
  7. The spec line plus a `@pytest.mark.skip` added on `test_adds`.
  8. `all --linked-issue '#53' --test-cmd ekit-no-such-toolchain`; `r2 --format text`.
- expected: steps 1-5 with the issue linked: exit 0, exactly one R2 entry, severity `confirm`, problem `test \`<name>\` removed, spec #N reverses it`, hint naming a quoted sentence of #N and restoring the test, summary `pass <head> (0 fail, 1 confirm; ran: R2; skipped: R1 R3 R4)`; step 3 names #53. No flag: exit 1, the plain `test fn \`<name>\` removed` fail. Step 6: two confirms exit 0; one named: a confirm and a `fail` for `test_more`, exit 1. Step 7: exit 1, the skip still fails. Step 8: `all` not a usage error, one R2 confirm naming #53; the text output names the test and #53. No traceback; nothing written into the kit repo.
- children: no-link, misuse
