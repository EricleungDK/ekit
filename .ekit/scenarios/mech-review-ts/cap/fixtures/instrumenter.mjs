// Fake @stryker-mutator/instrumenter 10.0.0 (not a scenario): the public `Instrumenter` class, whose
// `instrument(files, options)` resolves to `{ files, mutants }`. The mutants come from FAKE_TABLE (a JSON list of
// {file, mutator, replacement, start, end, from}: repo-relative file, 1-based lines, `from` the original text),
// not from parsing: so the scenario knows every mutant on every changed line. As the real one does, a mutant whose
// mutator `options.excludedMutations` names is returned with status "Ignored".
// FAKE_SHUFFLE=<seed> returns the mutants in a shuffled order (the pick must not depend on it).
import { readFileSync } from "node:fs";

export function rowsFor(name, source) {
  const lines = source.split("\n");
  const table = JSON.parse(readFileSync(process.env.FAKE_TABLE, "utf8"));
  return table.filter((r) => name === r.file || name.endsWith("/" + r.file)).map((r) => {
    const first = lines[r.start - 1] ?? "";
    const last = lines[r.end - 1] ?? "";
    const c0 = Math.max(0, first.indexOf(r.from.split("\n")[0]));
    const c1 = r.start === r.end ? c0 + r.from.length : last.length;
    return { ...r, c0, c1 };
  });
}

function shuffle(xs, seed) {
  let s = [...String(seed)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  const out = [...xs];
  for (let i = out.length - 1; i > 0; i--) {
    s = (s * 1103515245 + 12345) >>> 0;
    const j = s % (i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export class Instrumenter {
  constructor(logger) { this.logger = logger; }
  async instrument(files, options) {
    const ex = options && options.excludedMutations;
    const excluded = (m) => !!ex && typeof ex.includes === "function" && ex.includes(m);
    let id = 0;
    let mutants = [];
    for (const f of files) {
      for (const r of rowsFor(f.name, f.content)) {
        const m = { id: String(id++), fileName: f.name, mutatorName: r.mutator, replacement: r.replacement,
          location: { start: { line: r.start - 1, column: r.c0 }, end: { line: r.end - 1, column: r.c1 } } };
        if (excluded(r.mutator)) { m.status = "Ignored"; m.statusReason = "excluded by excludedMutations"; }
        mutants.push(m);
      }
    }
    if (process.env.FAKE_SHUFFLE) mutants = shuffle(mutants, process.env.FAKE_SHUFFLE);
    return { files: files.map((f) => ({ name: f.name, content: f.content, mutate: f.mutate })), mutants };
  }
}
