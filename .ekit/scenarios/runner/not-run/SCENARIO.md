# runner/not-run: a scenario this host has no shell for

- story: As a dev on a machine without bash (or without PowerShell), a `run.sh` (or `run.ps1`) scenario reads not run here, never PASS and never a plain FAIL, and the runner says what the host lacks.
- covers: #59 run.sh with no bash / run.ps1 with no PowerShell reads not-run (env); `check` says it cannot run here; `can-fail` reads it N/A (exit 4); a run.py beside it still runs
- steps:
  1. A sample git repo with scenarios `posix` (run.sh, exits 0) and `any` (run.py, exits 0); on a host without PowerShell also `win` (run.ps1, exits 0).
  2. With a PATH holding only Python and git (no bash; POSIX hosts, since Windows finds Git Bash beside git.exe): `scenarios.py run`.
  3. `check`; then drop `any` and run `can-fail HEAD`.
- expected: `NOT-RUN posix: bash is not on this machine (env)` (and `NOT-RUN win: PowerShell is not on this machine (env)`), `PASS any`, a `NOT-RUN` summary, exit 1; `check` exit 1 `cannot run here: ...` naming each; `can-fail` `N/A` lines and exit 4. On native Windows: FAIL `CANNOT CHECK: ...` naming why (Git Bash is found beside git.exe, Windows PowerShell under SystemRoot), never a PASS: run it on Linux, macOS or WSL.
