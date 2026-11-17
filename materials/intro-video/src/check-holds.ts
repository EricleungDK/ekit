// Prints how long each text item stays fully on screen after its reveal, against the rule
// hold ≥ 1.5 s + 0.3 s per word.  Run: node src/check-holds.ts
import { END_FADE, FADE_OUT, FPS, T, TIMELINE, revealEnd, wordCount, type Item } from "./plan.ts";

let bad = 0;
for (const s of TIMELINE) {
  const last = s === TIMELINE[TIMELINE.length - 1];
  const sceneEnd = s.dur - (last ? END_FADE : FADE_OUT);
  console.log(`\n${s.id}  (${(s.dur / FPS).toFixed(1)} s)`);
  for (const [k, it] of Object.entries(T[s.id]) as [string, Item][]) {
    const hold = ((it.until ?? sceneEnd) - revealEnd(it)) / FPS;
    const need = 1.5 + 0.3 * wordCount(it);
    const ok = hold >= need;
    if (!ok) bad++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${k.padEnd(9)} ${String(wordCount(it)).padStart(2)} words  hold ${hold.toFixed(1)} s  need ${need.toFixed(1)} s`);
  }
}
const total = TIMELINE.reduce((a, s) => a + s.dur, 0) / FPS;
console.log(`\ntotal ${total.toFixed(1)} s, ${bad} item(s) under the rule`);
process.exit(bad ? 1 : 0);
