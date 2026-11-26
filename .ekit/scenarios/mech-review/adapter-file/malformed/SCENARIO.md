# mech-review/adapter-file/malformed: misuse, a broken adapter file or flag is a usage error that names what is wrong

- story: As a user writing my first adapter file I make every usual mistake (a key missing or misspelt, a wrong type or value, an empty file, not TOML, a directory or a missing path, a `--stack` that is not the file's name, `--adapter` on another subcommand) and each time get exit 2 with a line naming the field, never a traceback and never a result that could read as a pass.
- covers: #16 A2 (malformed adapter file: missing field, bad value, wrong type, unknown key, empty, not TOML, not UTF-8, a directory, a missing path: exit 2, nothing on stdout, a `mech-review: adapter file <path>: <field>: ...` line, no traceback); agreed limits (`--adapter` with `merge` is a usage error, since merge reads no tree; with `red` or `all`, one for a file without `[run]` (#18); `--stack` must equal the file's `name`; a name not built in needs `--adapter`); odd but valid (a CRLF adapter file, a relative path from another cwd)
- steps:
  1. Parent's fixtures: `ktspec.toml` and the base repo; head marks `keeps` as `xtest` (a fail with the good file).
  2. With the good file: exit 1, the cheat named.
  3. One edited copy per mistake, each through `r2 --stack ktspec --adapter <copy>`; then `--stack ts` and `--stack KtSpec` with the good file; `merge` with the shipped `ts.toml` and `--stack ts`; `red`, `all` with the good file (no `[run]`); `--stack ktspec` with no `--adapter`.
  4. The good file with CRLF line ends, and by a relative path from a subdir.
- expected: step 3 every run exit 2, empty stdout, no `Traceback`, stderr naming the field and the problem (e.g. `tests.cases: missing`, `format: \`1\`: want 1`, `tests.casse: unknown key`, `cannot read`, `not valid TOML`, `describes stack \`ktspec\`, not \`ts\``, `--adapter applies to r2, red, all, mutants, baseline and plan (merge reads no tree)`, `--adapter applies to r2 only for good.toml: it has no [run] table`). Step 4 exit 1 with the cheat named.
- children: bracket-pair
