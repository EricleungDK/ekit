# mech-review/spec-reversed/no-link: failure, a removed test with no spec link keeps the R2 `fail`

- story: As a repo owner I trust that an agent cannot turn a removed test into a `confirm` without a real link to the issue the PR closes: no spec line, an issue the PR does not close, a line naming another test, or no `--linked-issue` all leave the `fail`.
- covers: #53 C2 (no spec line; a spec line whose issue is not passed with `--linked-issue`; a spec line naming another test; no `--linked-issue` at all: the `fail` stays); docs limits (the line must be in a commit message of merge-base..head, not a file or a commit on base; R2's exact name, so a bare method name for `TestCalc::test_keeps` does not count; one name removed from several files stays `fail`)
- steps:
  1. Parent's python repo (one-line `test_adds`, `test_keeps`); each head from base drops `test_keeps`, run with `r2 --stack python`:
     no spec line + `--linked-issue 53`; `spec: #53 ...` + `--linked-issue 61`; `spec: #5 ...` + `--linked-issue 53`; lines naming `test_adds`, `test_gone`, `test_keep`, `test_keeps_more`; the right line and no flag; the line only in a committed `NOTES.md`.
  2. The spec line on a commit already in base, the removal after it.
  3. A unittest class, `spec: #7 reverses test_keeps` for `TestCalc::test_keeps`.
  4. `test_keeps` removed from two files under one line.
  5. Rust one-line `keeps` removed, the line naming `adds`; and no flag.
- expected: every run exit 1, an R2 `fail` `test fn \`<name>\` removed` for the removed test (one per file in step 4), no `spec #` confirm, summary `fail ...`. No traceback.
