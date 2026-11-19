# mech-review/adapter-file/malformed/bracket-pair: misuse, a bracket entry that is not a pair is named as `lexer.brackets`

- story: As a user I mistype a bracket pair in my adapter file (`"(]"` for `"()"`) and am told `lexer.brackets` is wrong, instead of every file failing "does not parse" or an error that blames `functions.shapes`.
- covers: #16 A2 (bad value: a usage error that names the field; not a needs-human fail on every file)
- steps:
  1. Parent's fixtures. `ktspec.toml` with `brackets = ["(]", "[]", "{}"]` (a `(` and `)` that are not a pair, `()` missing): `r2 --stack ktspec --adapter`.
  2. The same with the `[functions]` table removed.
- expected: both exit 2, empty stdout, stderr names `lexer.brackets`, no traceback.
