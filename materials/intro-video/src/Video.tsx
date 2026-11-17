import React from "react";
import { AbsoluteFill, Audio, Easing, interpolate, Sequence, staticFile, useCurrentFrame } from "remotion";
import { theme } from "./theme";
import { ThemeCtx, useT, Wordmark } from "./ui";
import { prog } from "./motion";
import { BAR, BEAT, END_FADE, FADE_IN, FADE_OUT, TIMELINE, TOTAL } from "./plan";
import { Catch, Cta, FixA, FixB, Hook, Loop, Proof, Send } from "./scenes";

const COMPONENTS = { hook: Hook, catch: Catch, send: Send, loop: Loop, fixA: FixA, fixB: FixB, proof: Proof, cta: Cta };
const soft = Easing.inOut(Easing.sin);

/** Soft dissolve in and out, with a very slow push. */
const Shell: React.FC<{ dur: number; first: boolean; last: boolean; children: React.ReactNode }> = ({ dur, first, last, children }) => {
  const f = useCurrentFrame();
  const inP = first ? 1 : prog(f, 0, FADE_IN, soft);
  const outP = last ? 0 : prog(f, dur - FADE_OUT, FADE_OUT, soft);
  const scale = (1 + 0.01 * (f / dur)) * (0.99 + 0.01 * inP) * (1 + 0.008 * outP);
  return <AbsoluteFill style={{ opacity: inP * (1 - outP), transform: `scale(${scale})`, transformOrigin: "50% 45%" }}>{children}</AbsoluteFill>;
};

const Blueprint: React.FC = () => {
  const t = useT();
  const f = useCurrentFrame();
  const drift = f * 0.02;
  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(circle, ${t.line} 1.3px, transparent 1.6px)`,
          backgroundSize: "40px 40px",
          backgroundPosition: `${20 - drift * 0.5}px ${20 - drift * 0.25}px`,
          opacity: 0.55,
        }}
      />
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        <g transform={`translate(${-(drift % 160)}, 0)`} opacity={0.38}>
          {Array.from({ length: 14 }, (_, i) => i * 160).map((x, i) => (
            <line key={x} x1={x} y1={0} x2={x} y2={1080 * prog(f, i * 4, 80, soft)} stroke={t.line} strokeWidth={1} />
          ))}
        </g>
        <g opacity={0.38}>
          {Array.from({ length: 7 }, (_, i) => (i + 1) * 160).map((y, i) => (
            <line key={y} x1={0} y1={y} x2={1920 * prog(f, 16 + i * 4, 80, soft)} y2={y} stroke={t.line} strokeWidth={1} />
          ))}
        </g>
      </svg>
    </AbsoluteFill>
  );
};

const Chrome: React.FC = () => {
  const t = useT();
  const f = useCurrentFrame();
  const cur = [...TIMELINE].reverse().find((s) => f >= s.from)!;
  const idx = TIMELINE.indexOf(cur);
  const labelIn = prog(f - cur.from, 10, 40, soft);
  const labelOut = idx < TIMELINE.length - 1 ? prog(f - cur.from, cur.dur - FADE_OUT, FADE_OUT, soft) : 0;
  const appear = prog(f, 30, 60, soft);
  const x0 = 160, x1 = 1760, y = 1022;
  const bars = TOTAL / BAR;
  const beatPhase = (f % BEAT) / BEAT;
  const breathe = 0.5 + 0.5 * Math.cos(beatPhase * 2 * Math.PI);
  const mark = (x: number, yy: number, dx: number, dy: number) => (
    <path d={`M${x + dx * 26},${yy} L${x},${yy} L${x},${yy + dy * 26}`} fill="none" stroke={t.text} strokeWidth={1.5} opacity={0.5 * appear} />
  );
  return (
    <AbsoluteFill>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {mark(48, 48, 1, 1)}
        {mark(1872, 48, -1, 1)}
        {mark(48, 1032, 1, -1)}
        {mark(1872, 1032, -1, -1)}
        <g opacity={appear}>
          <line x1={x0} y1={y} x2={x1} y2={y} stroke={t.line} strokeWidth={1.5} />
          {Array.from({ length: Math.round(bars) + 1 }, (_, i) => {
            const x = x0 + ((x1 - x0) * i) / bars;
            const isCut = TIMELINE.some((s) => Math.abs(s.from - i * BAR) < 2);
            return <line key={i} x1={x} y1={y} x2={x} y2={y - (isCut ? 14 : 6)} stroke={isCut ? t.text : t.line} strokeWidth={isCut ? 1.5 : 1} />;
          })}
          <line x1={x0} y1={y} x2={x0 + (x1 - x0) * (f / TOTAL)} y2={y} stroke={t.accent} strokeWidth={2.5} />
          <rect x={x0 + (x1 - x0) * (f / TOTAL) - 5} y={y - 5} width={10} height={10} fill={t.accent} opacity={0.7 + 0.3 * breathe} />
        </g>
      </svg>
      <div style={{ position: "absolute", top: 52, left: 160, right: 160, display: "flex", justifyContent: "space-between", fontFamily: t.mono, fontSize: 18, letterSpacing: "0.04em", color: t.muted }}>
        <span style={{ opacity: labelIn * (1 - labelOut) }}>
          <span style={{ color: t.accent }}>0{idx + 1}</span> / {cur.label.toUpperCase()}
        </span>
        <span style={{ opacity: cur.id === "cta" ? 0 : appear }}>
          <Wordmark size={26} />
        </span>
      </div>
    </AbsoluteFill>
  );
};

export const IntroVideo: React.FC = () => {
  const t = theme;
  const f = useCurrentFrame();
  return (
    <ThemeCtx.Provider value={t}>
      {/* no ligatures: real output keeps `->` and `==` as typed */}
      <AbsoluteFill style={{ background: t.bg, color: t.text, fontFamily: t.sans, fontVariantLigatures: "none" }}>
        <Blueprint />
        {TIMELINE.map((s, i) => {
          const C = COMPONENTS[s.id];
          return (
            <Sequence key={s.id} from={s.from} durationInFrames={s.dur} name={s.label}>
              <Shell dur={s.dur} first={i === 0} last={i === TIMELINE.length - 1}>
                <C />
              </Shell>
            </Sequence>
          );
        })}
        <Chrome />
        <AbsoluteFill style={{ background: t.bg, opacity: interpolate(f, [TOTAL - END_FADE, TOTAL], [0, 1], { extrapolateLeft: "clamp", easing: soft }) }} />
        <Audio src={staticFile("music.wav")} />
      </AbsoluteFill>
    </ThemeCtx.Provider>
  );
};
