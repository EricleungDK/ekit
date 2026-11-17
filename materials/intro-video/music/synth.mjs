// An original, chill lo-fi bed for the intro video, synthesized from scratch (no samples, no downloads).
// 84 BPM: FM electric-piano chords, a warm pad, round sub bass, a muted kick and a soft rim click.
// No noise layers (hats, vinyl hiss or crackle): they read as sizzle under the voiceless video.
// Arranged on src/plan.ts so the sections follow the scenes. Mixed quiet (about -22 LUFS) to sit under the visuals.
//
//   node music/synth.mjs   →  public/music.wav
import { writeFileSync } from "node:fs";
import { BPM, SCENES } from "../src/plan.ts";

const SR = 44100;
const BEAT = 60 / BPM;
const BAR = BEAT * 4;
const BARS = SCENES.reduce((a, s) => a + s.bars, 0);
const LEN = BARS * BAR;
const N = Math.ceil((LEN + 4) * SR);
const TRIM_DB = -9; // sets the integrated loudness (measured with ffmpeg ebur128) to about -22 LUFS

const at = {};
SCENES.reduce((bar, s) => ((at[s.id] = bar), bar + s.bars), 0);

const L = new Float32Array(N);
const R = new Float32Array(N);
const keys = [new Float32Array(N), new Float32Array(N)]; // ducked lightly by the kick

let seed = 424242;
const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32; // 0..1
const noise = () => rnd() * 2 - 1;
const mtof = (m) => 440 * 2 ** ((m - 69) / 12);
const put = (bus, i, l, r = l) => {
  if (i >= 0 && i < N) {
    bus[0][i] += l;
    bus[1][i] += r;
  }
};
const dry = [L, R];

/** Stable state-variable filter (TPT); k = damping. */
const svf = () => {
  let ic1 = 0, ic2 = 0;
  return (x, cutoff, k = 1.2) => {
    const g = Math.tan((Math.PI * Math.min(cutoff, SR * 0.45)) / SR);
    const a1 = 1 / (1 + g * (g + k));
    const a2 = g * a1;
    const a3 = g * a2;
    const v3 = x - ic2;
    const v1 = a1 * ic1 + a2 * v3;
    const v2 = ic2 + a2 * ic1 + a3 * v3;
    ic1 = 2 * v1 - ic1;
    ic2 = 2 * v2 - ic2;
    return { low: v2, band: v1, high: x - k * v1 - v2 };
  };
};

/* ── instruments ── */

/** FM electric piano: sine carrier, ratio-1 modulator whose index decays, a faint tine an octave+ up. */
function epiano(t, m, vel = 0.8, len = 2.8) {
  const s = Math.floor(t * SR);
  const hz = mtof(m);
  let pc = 0, pm = 0, pt = 0;
  const pan = ((m % 12) / 12 - 0.5) * 0.5;
  for (let n = 0; n < len * SR; n++) {
    const x = n / SR;
    pc += (2 * Math.PI * hz) / SR;
    pm += (2 * Math.PI * hz) / SR;
    pt += (2 * Math.PI * hz * 7.02) / SR;
    const index = vel * (1.6 * Math.exp(-x * 5) + 0.18);
    const env = Math.min(1, x / 0.003) * Math.exp(-x * 0.75) * Math.min(1, (len - x) / 0.3);
    const tine = Math.sin(pt) * Math.exp(-x * 22) * 0.12;
    const trem = 1 + 0.18 * Math.sin(2 * Math.PI * 3.2 * (t + x));
    const y = (Math.sin(pc + index * Math.sin(pm)) + tine) * env * vel * 0.085;
    put(keys, s + n, y * (1 - pan) * trem, y * (1 + pan) * (2 - trem));
  }
}

function chord(t, notes, vel = 0.8, len = 2.8) {
  notes.forEach((m, i) => epiano(t + i * 0.014 + rnd() * 0.004, m, vel * (0.85 + rnd() * 0.15), len));
}

function pad(t, dur, notes, g = 1) {
  const s = Math.floor(t * SR);
  for (const m of notes)
    for (const [det, pan] of [[-0.07, -0.7], [0.08, 0.7]]) {
      const f = svf();
      const hz = mtof(m + det);
      let p = rnd();
      for (let n = 0; n < dur * SR; n++) {
        const x = n / SR;
        p = (p + hz / SR) % 1;
        const env = Math.min(1, x / 0.9) * Math.min(1, (dur - x) / 0.9);
        const y = f(p * 2 - 1, 650, 1.4).low * env * 0.034 * g;
        put(keys, s + n, y * (1 - pan * 0.5), y * (1 + pan * 0.5));
      }
    }
}

function bass(t, m, len, g = 1) {
  const s = Math.floor(t * SR);
  const hz = mtof(m);
  let p = 0;
  for (let n = 0; n < len * SR; n++) {
    const x = n / SR;
    p += (2 * Math.PI * hz) / SR;
    const env = Math.min(1, x / 0.012) * Math.min(1, (len - x) / 0.06) * (0.75 + 0.25 * Math.exp(-x * 3));
    put(keys, s + n, (Math.sin(p) + 0.18 * Math.sin(2 * p)) * env * 0.2 * g);
  }
}

const kickTimes = [];
function kick(t, g = 1) {
  kickTimes.push(t);
  const s = Math.floor(t * SR);
  let p = 0;
  for (let n = 0; n < 0.35 * SR; n++) {
    const x = n / SR;
    p += (2 * Math.PI * (48 + 40 * Math.exp(-x * 40))) / SR;
    put(dry, s + n, Math.sin(p) * Math.exp(-x * 10) * 0.5 * g);
  }
}

function rim(t, g = 1) {
  const s = Math.floor(t * SR);
  const f = svf();
  let p = 0;
  for (let n = 0; n < 0.18 * SR; n++) {
    const x = n / SR;
    p += (2 * Math.PI * 185) / SR;
    const y = f(noise(), 1200, 2).band * Math.exp(-x * 40) * 0.18 + Math.sin(p) * Math.exp(-x * 40) * 0.3;
    put(dry, s + n, y * 0.32 * g, y * 0.28 * g);
  }
}

/* ── arrangement ── */

// Fmaj9 – Em7 – Dm9 – Cmaj9, a slow descending loop
const CHORDS = [
  { notes: [53, 57, 60, 64, 67], root: 41 },
  { notes: [52, 55, 59, 62, 66], root: 40 },
  { notes: [50, 53, 57, 60, 64], root: 38 },
  { notes: [48, 52, 55, 59, 62], root: 36 },
];
// a sparse melody on top, two bars long, in beats
const MOTIF = [
  [0.5, 76], [1.5, 74], [3, 72],
  [4.5, 71], [6, 69], [7.5, 67],
];

const lastBar = BARS - 1;
const drumsOn = (bar) => bar >= at.catch && bar < at.cta + 1;

for (let bar = 0; bar < BARS; bar++) {
  const t0 = bar * BAR;
  const ch = CHORDS[bar % 4];
  const end = bar === lastBar;

  pad(t0, BAR + 0.6, ch.notes.slice(1, 4), bar < at.catch ? 0.8 : 1);
  chord(t0, ch.notes, end ? 0.75 : 0.8, end ? BAR * 1.4 : 2.6);
  if (!end) chord(t0 + 2.5 * BEAT, ch.notes.slice(2), 0.5, 1.6);

  if (bar >= 1 && !end) {
    bass(t0, ch.root, BEAT * 2.4);
    bass(t0 + 2.5 * BEAT, ch.root + (bar % 2 ? 7 : 0), BEAT * 1.45, 0.8);
  }
  if (end) bass(t0, ch.root, BAR * 1.2);

  if (bar >= at.send && bar < at.cta && bar % 2 === 0)
    for (const [beat, m] of MOTIF) if (beat < 8) epiano(t0 + beat * BEAT, m, 0.42, 1.8);

  if (drumsOn(bar)) {
    kick(t0);
    kick(t0 + 2.5 * BEAT, 0.8);
    if (bar % 4 === 3) kick(t0 + 1.75 * BEAT, 0.55);
    rim(t0 + BEAT + rnd() * 0.01);
    rim(t0 + 3 * BEAT + rnd() * 0.01);
  }
}

/* ── mix ── */

kickTimes.sort((a, b) => a - b);
const warmL = svf(), warmR = svf();
let k = 0;
const len = Math.round(LEN * SR);
const outL = new Float32Array(len), outR = new Float32Array(len);
for (let i = 0; i < len; i++) {
  const t = i / SR;
  while (k + 1 < kickTimes.length && kickTimes[k + 1] <= t) k++;
  const since = kickTimes.length && kickTimes[k] <= t ? t - kickTimes[k] : 9;
  const duck = 1 - 0.2 * Math.exp(-since * 7);
  const l = L[i] + keys[0][i] * duck;
  const r = R[i] + keys[1][i] * duck;
  outL[i] = Math.tanh(warmL(l, 5000, 1.3).low * 1.2);
  outR[i] = Math.tanh(warmR(r, 5000, 1.3).low * 1.2);
}

let peak = 0;
for (let i = 0; i < len; i++) {
  const fade = Math.min(1, i / (2.0 * SR), (len - i) / (3.0 * SR));
  outL[i] *= fade;
  outR[i] *= fade;
  peak = Math.max(peak, Math.abs(outL[i]), Math.abs(outR[i]));
}
const gain = (0.89 / peak) * 10 ** (TRIM_DB / 20);

const buf = Buffer.alloc(44 + len * 4);
buf.write("RIFF", 0);
buf.writeUInt32LE(36 + len * 4, 4);
buf.write("WAVEfmt ", 8);
buf.writeUInt32LE(16, 16);
buf.writeUInt16LE(1, 20);
buf.writeUInt16LE(2, 22);
buf.writeUInt32LE(SR, 24);
buf.writeUInt32LE(SR * 4, 28);
buf.writeUInt16LE(4, 32);
buf.writeUInt16LE(16, 34);
buf.write("data", 36);
buf.writeUInt32LE(len * 4, 40);
for (let i = 0; i < len; i++) {
  buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, outL[i] * gain)) * 32767), 44 + i * 4);
  buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, outR[i] * gain)) * 32767), 46 + i * 4);
}
writeFileSync(new URL("../public/music.wav", import.meta.url), buf);
console.log(`public/music.wav: ${LEN.toFixed(1)}s, ${BPM} BPM, ${BARS} bars`);
