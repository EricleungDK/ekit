# mech-review/adapter-file/target-os: an adapter file's `target-os` is linux, macos or windows, linux when left out, and `resolve` prints it

- story: As a repo owner whose stack's tests must run on macOS or Windows, I set `target-os` in my adapter file and the workflow's stack job (`resolve`) reports it, so the right runner is picked; a typo in the value or the key stops me with the field named, and the built-in stacks and a file without the key stay on linux.
- covers: #58 58.1 (`target-os` = linux/macos/windows parses; any other value is a usage error naming the field); 58.2 (a missing `target-os` reads linux; the built-in stacks are linux); 58.3 (`resolve` carries the target OS: built-ins linux, an adapter file with macos gives macos); misuse (wrong case, `win`, `darwin`, a runner label, a trailing space, empty, a number, a boolean, a list, the key misspelt `target_os`, `--stack` not the file's name)
- steps:
  1. Clone the kit from `$EKIT_REPO`; a ts repo (`package.json`, `src/calc.ts`, `tests/calc.test.ts`) committed.
  2. `resolve --base B --head B` with `--stack` auto, rust, python, ts; then `--stack ts --adapter <kit>/scripts/mech_review/adapters/ts.toml` (no `target-os` in it).
  3. Copies of the shipped ts.toml with `target-os` = `"linux"`, `"macos"`, `"windows"`: `resolve --stack ts --adapter <copy>` and `r2` through the same copy; the macos copy by a relative path from the repo.
  4. Copies with `target-os` = `"Linux"`, `"MacOS"`, `"win"`, `"darwin"`, `"ubuntu-latest"`, `"linux "`, `""`, `1`, `true`, `["linux"]`: `resolve` and `r2` through each. A copy with `target_os = "windows"`. `--stack python` with the macos copy.
- expected: step 2 exit 0, `target_os` `linux` every time (auto finds `ts`). Step 3 exit 0, `target_os` the value set, keys `error project_dir stack target_os`; r2 exit 0 `pass <sha>`; relative path `macos`. Step 4 every run exit 2, empty stdout, stderr `adapter file <path>: target-os ...` (the typo names `target_os`), no traceback.
