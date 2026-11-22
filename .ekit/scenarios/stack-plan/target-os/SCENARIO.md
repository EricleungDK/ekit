# stack-plan/target-os: the stack job's output carries the plan entry's target OS, over its adapter's, read from the base branch

- story: As a repo owner I give a stack in my plan `target-os = "windows"`, and the workflow's stack job (`resolve`) reports windows for it, over what its adapter file says; a PR cannot pick its own runner by editing the plan, and a broken plan never stops the stack job silently.
- covers: #58 58.3 (`resolve` carries the target OS; a stack plan entry's target OS wins over its adapter's; built-ins linux; an adapter file with macos gives macos); #56 56.1 (`target-os` in a plan entry; a bad one is named); misuse/failure (a bad base plan: resolve exit 0 on the adapter's OS with stderr naming the problem, drift exit 2)
- steps:
  1. Parent's install and fixture adapter `kt.toml` (manifest `build.gradle.kts`).
  2. Plan `web` (built-in ts, `target-os = "windows"`): `resolve` auto, then `--stack ts --project-dir web`, then `--stack ts` (dir `.`, no entry).
  3. `mob` with adapter file `.ekit/adapters/kt.toml` set to macos: `resolve --stack kt --project-dir mob --adapter <it>` with the entry's target-os unset, `windows`, `linux`.
  4. A PR that flips the entry from windows to linux: resolve base..PR.
  5. One folder with a retiring (macos) and a current (windows) ts entry: resolve auto.
  6. A base plan with `target-os = "Windows"`: resolve, drift; a plan-only PR that fixes it: resolve base..PR.
- expected: step 2 `windows`, `windows`, `linux`. Step 3 `macos`, `windows`, `linux`. Step 4 `windows` (the base plan). Step 5 `windows`. Step 6 resolve exit 0 `linux` with stderr naming `target-os` and the OS that applied; drift exit 2 naming `stack[0] \`web\`, field target-os`; the fix PR `windows`. No traceback.
