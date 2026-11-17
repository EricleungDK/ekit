// Plan: the single source of truth for scene lengths, every on-screen string, its timing, and the hold-time check.
// No imports, so plain Node can run it too: `node src/check-holds.ts`, `node music/synth.mjs`.
// scenes.tsx renders only strings from here (an item's `text`, `em`, `parts` or `lines`), so `npm run check` covers all of it.

export const BPM = 84;
export const FPS = 60;
export const BEAT = (FPS * 60) / BPM; // ≈ 42.86 frames
export const BAR = BEAT * 4; // ≈ 171.4 frames ≈ 2.86 s
export const FADE_IN = 42; // 0.7 s
export const FADE_OUT = 40; // 0.67 s
export const END_FADE = 60; // the last scene fades to paper over 1 s
export const b = (beats: number) => Math.round(beats * BEAT);

export type SceneId = "hook" | "catch" | "send" | "loop" | "fixA" | "fixB" | "proof" | "cta";
export const SCENES: { id: SceneId; label: string; bars: number }[] = [
  { id: "hook", label: "The problem", bars: 3 },
  { id: "catch", label: "ekit catches it", bars: 4 },
  { id: "send", label: "The fix wanted", bars: 5 },
  { id: "loop", label: "The loop", bars: 5 },
  { id: "fixA", label: "Iteration 2", bars: 4 },
  { id: "fixB", label: "Proven", bars: 4 },
  { id: "proof", label: "Proof", bars: 4 },
  { id: "cta", label: "Get it", bars: 4 },
];

/** Scene start/length in frames, rounded from bar positions so cuts stay on the music's downbeats. */
export const TIMELINE = (() => {
  let bars = 0;
  return SCENES.map((s) => {
    const from = Math.round(bars * BAR);
    bars += s.bars;
    return { ...s, from, dur: Math.round(bars * BAR) - from };
  });
})();
export const TOTAL = TIMELINE[TIMELINE.length - 1].from + TIMELINE[TIMELINE.length - 1].dur;

/**
 * A text item: `words` items reveal word by word (stagger frames apart, ~40 frames to settle);
 * `block` items fade/rise in over 45 frames. `count` = words a viewer has to read (for code: tokens).
 * `until` = frame (scene-local) where it leaves early; default is the scene's fade-out.
 * `em` = the emphasised tail of a `words` item's text. `parts` / `lines` = the pieces a structured item renders
 * (a table row's cells, a panel's header, a code block's lines); `text` is them joined, so the check counts them.
 */
export type Item = {
  text: string;
  at: number;
  kind: "words" | "block";
  stagger?: number;
  count?: number;
  until?: number;
  em?: string;
  parts?: readonly string[];
  lines?: readonly string[];
};
type Opts = Omit<Item, "text" | "at" | "kind" | "parts" | "lines">;

/** A headline: `plain` then the emphasised `em`, revealed word by word. */
const W = (plain: string, em: string, at: number, stagger: number) =>
  ({ text: plain + em, em, at, kind: "words", stagger }) as const satisfies Item;
/** A structured block: its cells, in render order. */
const P = <const S extends readonly string[]>(parts: S, at: number, o: Opts = {}) =>
  ({ text: parts.join(" "), parts, at, kind: "block", ...o }) as const;
/** A code block: its lines. */
const L = <const S extends readonly string[]>(lines: S, at: number, o: Opts = {}) =>
  ({ text: lines.join(" "), lines, at, kind: "block", ...o }) as const;

// Every mech-review and pytest string below is real output from the scratch demo repo (see README): SHAs are
// shortened, and R1-c29d8680's problem drops pytest's progress line that leaks into it.
export const T = {
  hook: {
    who: { text: "› your coding agent", at: 10, kind: "block", count: 3 },
    quote: W("", "“All tests pass.”", 20, 12),
    line2: W("", "It deleted the one that didn’t.", b(3), 8),
    // the real hunk: the whole 3-line test removed (plus 2 blank lines)
    diff: L(["tests/test_calc.py", "−3 lines", "- def test_div_rejects_zero():", "-     with pytest.raises(ZeroDivisionError):", "-         div(1, 0)"], b(4.5), { count: 8 }),
  },
  catch: {
    head: W("ekit ", "catches it.", 15, 10),
    // what the PR's report job posts for iteration 1: guard (R2) + red-first (R1, R4) + mutants (R3), merged
    card: P(["mech-review report · on the PR", "fail", "· 5 fail, 1 confirm"], 50),
    row1: P(["fail", "R3-feb1880c", "MISSED mutant calc.py:3: return 0 -> return 1"], 75),
    row2: P(["fail", "R2-55dee746", "test fn `test_div_rejects_zero` removed"], 95),
    row3: P(["fail", "R1-c29d8680", "`test_div_halves` cannot be proven red on the base's production code"], 115),
    row4: P(["fail", "R2-d15476fc", "test `test_div_halves` marked skipped (skip or xfail)"], 135),
    row5: P(["fail", "R4-4547185d", "test `test_div_halves` did not run at head"], 155),
    row6: P(["confirm", "R2-3c9ea7bc", "expected value changed in `test_div_halves`: was 2, now 2.5"], 175),
    stamp: P(["CHECK FAILED", "mech-review report · fail"], b(7)),
    caption: W("A fail ", "turns the PR check red.", 330, 6),
  },
  send: {
    head: W("And leaves it where ", "your agent looks.", 15, 8),
    card: P(["mech-review · PR comment + JSON", "fail", "fail", "R2-55dee746", "test fn `test_div_rejects_zero` removed"], 70),
    agent: P(["your agent", "on this PR", "reading the PR comment…"], 40),
    hint: P(["hint:", "restore the test and make the code satisfy it; a removed test is not a fix"], 100),
    forbidden: P(["forbidden:", "deleting or renaming a test to hide a failure"], 108),
    path: { text: "↓ the fix wanted, the shortcut banned", at: b(5), kind: "block" },
    sentNote: { text: "hint + forbidden → in the comment’s JSON", at: b(5) + 60, kind: "block", count: 7 },
    caption: W("The PR comment carries the fix wanted ", "and the shortcut that’s banned.", 290, 5),
    orchestrate: P(["In", "/ekit:orchestrate-agent", "runs, it goes straight back to the agent."], 380),
  },
  loop: {
    head: W("Until it’s proven, it goes back, ", "or it stops and tells you why.", 15, 7),
    scope: { text: "/ekit:orchestrate-agent", at: 60, kind: "block", count: 2 },
    nodes: P(["Agent works", "edits code, runs tests", "Claims “done”", "“all tests pass”", "ekit checks", "mech-review · finish gate", "Sent back", "with the fix that’s wanted"], 50),
    blocked: P(["Blocked", "after 3 rounds, it says why"], 150),
    done: P(["Done", "only with proof"], 120),
    iter1: { text: "iteration 1", at: b(5), kind: "block", until: b(11) },
    status1: { text: "No proof: sent back", at: b(7), kind: "block", until: b(13) },
    iter2: { text: "iteration 2", at: b(11), kind: "block" },
    status2: { text: "Proven: done", at: b(13), kind: "block" },
  },
  fixA: {
    head: W("Iteration 2: ", "every finding, resolved.", 10, 8),
    // iteration 2's real diff against iteration 1, in file order: blank lines dropped, one context line kept
    diff: L(
      [
        "calc.py",
        "-         return 0",
        '+         raise ZeroDivisionError(f"cannot divide {a} by zero")',
        "tests/test_calc.py",
        "+ def test_div_rejects_zero():",
        "+     with pytest.raises(ZeroDivisionError):",
        "+         div(1, 0)",
        "- @pytest.mark.skip",
        "  def test_div_halves():",
        "-     assert div(4, 2) == 2.5",
        "+     assert div(4, 2) == 2",
        "+ def test_div_zero_names_the_dividend():",
        '+     with pytest.raises(ZeroDivisionError, match="cannot divide 7 by zero"):',
        "+         div(7, 0)",
      ],
      40,
      { count: 22 },
    ),
    diffTag: { text: "new test", at: 40, kind: "block" },
    row1: P(["R2-55dee746", "test removed", "test_div_rejects_zero restored"], 70),
    row2: P(["R2-d15476fc R4-4547185d", "skipped, did not run", "@pytest.mark.skip removed"], 70 + b(1)),
    row3: P(["R2-3c9ea7bc", "expected value changed", "== 2 restored"], 70 + b(2)),
    row4: P(["R1-c29d8680", "no test fails on the old code", "new test: red on the old code"], 70 + b(3)),
    row5: P(["R3-feb1880c", "missed: return 0 -> return 1", "return 0 gone: div(1, 0) raises"], 70 + b(4)),
    caption: W("Nothing deleted, nothing skipped, ", "no hack left.", 300, 5),
  },
  fixB: {
    head: W("And it’s ", "proven.", 10, 10),
    r1: P(["R1", "red-first", "pass", "The new test fails on the old code, so it really catches the change."], 50),
    r2: P(["R2", "test-diff guard", "pass", "Nothing deleted, skipped or weakened."], 75),
    r3: P(["R3", "mutation", "pass", "All 4 mutants of the changed function are caught."], 100),
    r4: P(["R4", "determinism", "pass", "The new test passes 5 runs in a row."], 125),
    pass: P(["mech-review report · iteration 2 · the same checks the PR runs", "pass", "all pass", "aa6837e"], 160),
  },
  proof: {
    head: W("“Done” now ", "comes with proof.", 10, 8),
    title: P(["## Finish:", "done", "Criterion", "Status", "Evidence"], 50),
    row1: P(["All tests pass", "verified", "`pytest tests/test_calc.py -q`", "→ exit 0, 4 passed"], 80),
    row2: P(["div(7, 0) says “cannot divide 7 by zero”", "verified", "`pytest tests/test_calc.py -k names_the_dividend -q`", "→ exit 0, 1 passed"], 105),
    mech: P(["Mech aa6837e:", "R1 pass · R2 pass · R3 pass · R4 pass"], 130, { count: 10 }),
    caption: W("Every ✓ has a command ", "and its output.", 190, 6),
  },
  cta: {
    tagline: W("Proof before ", "“done”.", 40, 10),
    install: L(["claude plugin marketplace add EricleungDK/ekit", "claude plugin install ekit@ekit --scope user"], 90, { count: 10 }),
    ciDoctor: P(["/ekit:ci-doctor", "# then, in your repo: adds the PR checks"], 125),
    also: { text: "Also installs in Codex, GitHub Copilot and any Agent Skills agent (skills; hooks in Claude Code).", at: 150, kind: "block" },
    star: P(["★", "Star on GitHub", "github.com/EricleungDK/ekit"], 200, { count: 5 }),
  },
} satisfies Record<SceneId, Record<string, Item>>;

export const wordCount = (it: Item) => it.count ?? it.text.split(/\s+/).filter(Boolean).length;
export const revealEnd = (it: Item) =>
  it.kind === "words" ? it.at + (wordCount(it) - 1) * (it.stagger ?? 6) + 40 : it.at + 45;
