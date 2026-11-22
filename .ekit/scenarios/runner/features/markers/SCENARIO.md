# runner/features/markers: misuse, a feature line in the wrong form, or one that is only text

- story: As a dev who mistypes a scenario's feature line (two of them, `Feature:`, bold, a code fence left open above it), `run` names the mistake on that scenario instead of counting or dropping it in silence; a `- feature:` inside a fence or an HTML comment, a Gherkin `Feature:` line and a nested bullet are text, so those scenarios read as unmarked; a run that writes into my repo counts no feature as working.
- covers: #60 60.3 misuse (a bad feature line is a named FAIL; marker-like text is no marker, and the scenario reads as before: PASS, not counted in M; no features working in a run that modified the repo)
- steps:
  1. `git clone` the kit into the temp cwd. A user repo whose run.py scenarios all exit 0: `real` (`- feature: export`), `two` (two feature lines), `caps` (`- Feature: x`), `bold` (`- **feature**: x`), `open-fence` (a code fence opened above `- feature: z`, never closed), `fenced` (`- feature: fake` inside a closed fence), `comment` (`- feature: hidden` inside `<!-- -->`), `gherkin` (`Feature: login`), `nested` (a nested `  - feature: deep` bullet).
  2. `scenarios.py run`, `check`.
  3. Add `writer` (`- feature: notes`, exits 0, writes `notes.txt` into `$EKIT_REPO`); `run`.
- expected: step 2: exit 1; `FAIL two: ...` naming both names, `FAIL caps: ...` and `FAIL bold: ...` quoting the line, `FAIL open-fence: ...` naming the fence; `PASS` for real, fenced, comment, gherkin and nested; last line `1 of 1 features working` (only `export`: no `fake`, `hidden`, `login` or `deep` counted); `check` exit 1 ending `1 of 1 features working`. Step 3: exit 1, `modified the repo`, last line `0 of 2 features working`. No traceback.
