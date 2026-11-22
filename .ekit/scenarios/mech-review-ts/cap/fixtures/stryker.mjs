#!/usr/bin/env node
// Fake Stryker 10.0.0 CLI (not a scenario), installed by setup.sh as @stryker-mutator/core/bin/stryker.js.
//   stryker --version                 prints 10.0.0
//   stryker run --mutate F:a-b,...    makes the FAKE_TABLE mutants that lie fully inside a range (as Stryker does),
//                                     logs its log lines and writes reports/mutation/mutation.json
// Env:
//   FAKE_ARGV=<file>     append the run's argv, one line per run
//   FAKE_RAN=<file>      append each mutant it made, `file:start-end mutator`, one per line
//   FAKE_SURVIVE=<re>    mutants (`file:start-end mutator`) that survive; the rest are killed
//   FAKE_HANG=before     hang before any report is written (the budget kills it)
//   FAKE_HANG=after      write a report whose mutants past the first FAKE_DONE are still Pending, then hang
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { rowsFor } from "../../instrumenter/index.js";

const args = process.argv.slice(2);
if (args[0] === "--version") { console.log("10.0.0"); process.exit(0); }
if (process.env.FAKE_ARGV) appendFileSync(process.env.FAKE_ARGV, args.join(" ") + "\n");
const at = args.indexOf("--mutate");
const ranges = (at >= 0 ? args[at + 1] : "").split(",").filter(Boolean).map((s) => {
  const m = /^(.*):(\d+)-(\d+)$/.exec(s);
  return m ? { file: m[1], a: Number(m[2]), b: Number(m[3]) } : { file: s, a: 1, b: 1e9 };
});
const files = [...new Set(ranges.map((g) => g.file))];
const made = [];
for (const file of files) {
  const source = readFileSync(file, "utf8");
  for (const r of rowsFor(file, source)) {
    if (ranges.some((g) => g.file === file && g.a <= r.start && r.end <= g.b)) made.push({ ...r, file, source });
  }
}
const tag = (r) => `${r.file}:${r.start}-${r.end} ${r.mutator}`;
const stamp = "00:00:00 (1)";
console.log(`${stamp} INFO ProjectReader Found ${files.length} of ${files.length} file(s) to be mutated.`);
console.log(`${stamp} INFO Instrumenter Instrumented ${files.length} source file(s) with ${made.length} mutant(s)`);
console.log(`${stamp} INFO DryRunExecutor Initial test run succeeded. Ran 1 tests in 0 seconds (net 1 ms, overhead 1 ms).`);
if (process.env.FAKE_RAN) for (const r of made) appendFileSync(process.env.FAKE_RAN, tag(r) + "\n");
const hang = process.env.FAKE_HANG || "";
const done = Number(process.env.FAKE_DONE || 0);
const survive = process.env.FAKE_SURVIVE ? new RegExp(process.env.FAKE_SURVIVE) : null;
// a mutator the config in cwd excludes (`mutator.excludedMutations`) is made but Ignored, as Stryker reports it
let excluded = [];
try { excluded = JSON.parse(readFileSync("stryker.conf.json", "utf8")).mutator?.excludedMutations ?? []; } catch {}
const status = (r, i) => (excluded.includes(r.mutator) ? "Ignored" : hang === "after" && i >= done ? "Pending"
  : survive && survive.test(tag(r)) ? "Survived" : "Killed");
if (hang !== "before") {
  const report = { schemaVersion: "1.0", thresholds: { high: 80, low: 60, break: null }, projectRoot: process.cwd(), files: {} };
  made.forEach((r, i) => {
    const f = (report.files[r.file] ??= { language: "typescript", source: r.source, mutants: [] });
    const st = status(r, i);
    f.mutants.push({ id: String(i), mutatorName: r.mutator, replacement: r.replacement, status: st,
      testsCompleted: st === "Pending" ? 0 : 1, ...(st === "Killed" ? { killedBy: ["0"] } : {}),
      location: { start: { line: r.start, column: r.c0 + 1 }, end: { line: r.end, column: r.c1 + 1 } } });
  });
  mkdirSync("reports/mutation", { recursive: true });
  writeFileSync("reports/mutation/mutation.json", JSON.stringify(report));
  console.log(`${stamp} INFO JsonReporter Your report can be found at: file://${process.cwd()}/reports/mutation/mutation.json`);
}
if (hang) setInterval(() => {}, 1000);
else console.log(`${stamp} INFO MutationTestExecutor Done in 0 seconds.`);
