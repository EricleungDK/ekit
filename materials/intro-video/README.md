# ekit intro video

A 94-second, 1920×1080, 60 fps explainer for ekit, made with [Remotion](https://www.remotion.dev). Its story is ekit's core loop: an agent takes a shortcut, ekit's PR checks catch it and leave the fix they want in the PR comment, and in an `/ekit:orchestrate-agent` run "done" is accepted only with proof.

## Run

Needs Node 22.18 or newer (the music and check scripts import `src/plan.ts` directly). From this folder:

```bash
npm ci
npm run studio     # Remotion Studio: scrub and tweak the video
npm run render     # → out/ekit-intro.mp4
npm run stills     # one key frame per scene → stills/  (or: npm run stills -- 300,1200)
npm run check      # typecheck + reading-time check for every text item
```

`studio` and `render` first synthesize the music into `public/music.wav`. Fonts come from Google Fonts at render time (`@remotion/google-fonts`), so the first render needs a network connection.

## Scenes

| # | Scene | Says |
|---|---|---|
| 1 | The problem | "All tests pass." / It deleted the one that didn't (the whole 3-line test). |
| 2 | ekit catches it | The PR's mech-review report for iteration 1: 5 fail, 1 confirm (R3 mutant, deleted test, R1, skip, R4, changed expected value); a fail turns the PR check red. |
| 3 | The fix wanted | The PR comment carries each entry's hint and forbidden shortcut in its JSON, where your agent looks; in `/ekit:orchestrate-agent` runs it goes straight back to the agent. |
| 4 | The loop | In `/ekit:orchestrate-agent`: agent works → claims "done" → mech-review and the finish gate check → sent back, until iteration 2 exits to Done; or blocked after 3 rounds, saying why. |
| 5 | Iteration 2 | Every finding mapped to its fix: test restored, skip removed, `== 2` restored, a new test that is red on the old code, `return 0` replaced by a raise. |
| 6 | Proven | R1 red-first, R2 test-diff guard, R3 mutation and R4 determinism all pass: `all pass`, the same checks the PR runs. |
| 7 | Proof | The finish report: every ✓ has a command and its output, plus the `Mech` line. |
| 8 | Get it | Install commands, `/ekit:ci-doctor` for the PR checks, and the GitHub link. |

Every mech-review and pytest line is real output from a scratch repo built from the README's divide-by-zero example: `main` (with a minimal `pyproject.toml`, which R3 needs), iteration 1 (the shortcut) and iteration 2 (the fix) on branch `claude/fix-div`. Scenes 2 and 6 are what the PR's `report` job posts: the CI jobs' commands run locally (`mech-review.py r2`, `red`, `baseline`, `mutants --shard 0/1`, `merge`, with pytest 9.2.0 and mutmut 3.8.1 as CI pins them), then merged and rendered by the `report` step's own code (`mech_review.merge` + `mech_review.comment`), minus the GitHub call. SHAs are shortened, and some lines are trimmed: R1-c29d8680's problem drops a pytest progress line that leaks into it, and diffs show only the lines that matter.

## Files

| File | Role |
|---|---|
| `src/plan.ts` | Single source of truth: BPM, scene lengths in bars, and every on-screen string and its timing. |
| `src/scenes.tsx` | The eight scenes. They render only strings and timings from `plan.ts`. |
| `src/Video.tsx` | Background grid, scene dissolves, section labels, progress ruler, music. |
| `src/motion.tsx` | Motion primitives: word-by-word reveals, rise-ins, drawn check marks, pulses. |
| `src/theme.ts`, `src/ui.tsx` | Colours, fonts and the wordmark. |
| `src/check-holds.ts` | Fails if any text item stays fully on screen for less than 1.5 s + 0.3 s per word. |
| `music/synth.mjs` | Original 84 BPM lo-fi bed (FM keys, pad, sub bass, a muted kick and soft rim; no hats or vinyl noise, which read as sizzle), synthesized from scratch with no samples, mixed to about −22 LUFS. Scenes are whole bars, so cuts land on downbeats. |

## Editing

Change copy or timing in `src/plan.ts`, then run `npm run check` so every line stays readable. Changing a scene's `bars` moves the music with it.
