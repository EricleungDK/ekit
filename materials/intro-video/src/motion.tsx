// Motion primitives. Everything is timed in frames (60 fps).
import React from "react";
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useT } from "./ui";

/** A line of copy: plain text, emphasised words, inline code. */
export type Rich = (string | { em: string } | { code: string })[];

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
export const ease = Easing.bezier(0.16, 1, 0.3, 1);
export const prog = (f: number, start: number, dur = 30, easing = ease) =>
  interpolate(f, [start, start + dur], [0, 1], { ...clamp, easing });

/** A decaying 1→0 flash that starts at frame `t`. */
export const pulse = (f: number, t: number, decay = 14) => (f >= t ? Math.exp(-(f - t) / decay) : 0);

/** Word-by-word mask reveal: each word rises out of its own clipped box. */
export const Words: React.FC<{
  parts: Rich;
  at: number;
  stagger?: number;
  style?: React.CSSProperties;
}> = ({ parts, at, stagger = 5, style }) => {
  const t = useT();
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens: { text: string; kind: "plain" | "em" | "code" }[] = [];
  for (const p of parts) {
    if (typeof p === "string") p.split(/\s+/).filter(Boolean).forEach((w) => tokens.push({ text: w, kind: "plain" }));
    else if ("em" in p) p.em.split(/\s+/).filter(Boolean).forEach((w) => tokens.push({ text: w, kind: "em" }));
    else tokens.push({ text: p.code, kind: "code" });
  }
  // Note: words are split on whitespace, so keep punctuation inside the part it follows.
  return (
    <span style={style}>
      {tokens.map((tok, i) => {
        const p = spring({ frame: f - at - i * stagger, fps, config: { damping: 24, stiffness: 170, mass: 0.7 } });
        const inner: React.CSSProperties =
          tok.kind === "em"
            ? { color: t.accent }
            : tok.kind === "code"
              ? {
                  fontFamily: t.mono,
                  fontSize: "0.78em",
                  fontWeight: 500,
                  letterSpacing: "-0.02em",
                  padding: "0 0.25em",
                  background: t.accentSoft,
                  color: t.accent,
                }
              : {};
        return (
          <React.Fragment key={i}>
            <span
              style={{
                display: "inline-block",
                overflow: "hidden",
                verticalAlign: "top",
                padding: "0.06em 0.02em 0.14em",
                margin: "-0.06em -0.02em -0.14em",
              }}
            >
              <span style={{ display: "inline-block", transform: `translateY(${(1 - p) * 135}%)`, ...inner }}>
                {tok.text}
              </span>
            </span>
            {i < tokens.length - 1 ? " " : null}
          </React.Fragment>
        );
      })}
    </span>
  );
};

/** Fade + rise. */
export const Rise: React.FC<{
  at: number;
  dur?: number;
  y?: number;
  x?: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({ at, dur = 36, y = 24, x = 0, style, children }) => {
  const f = useCurrentFrame();
  const p = prog(f, at, dur);
  return (
    <div style={{ opacity: p, transform: `translate(${(1 - p) * x}px, ${(1 - p) * y}px)`, ...style }}>{children}</div>
  );
};

/** A check mark that draws itself. */
export const Check: React.FC<{ at: number; size?: number; color: string; width?: number }> = ({
  at,
  size = 28,
  color,
  width = 3,
}) => {
  const f = useCurrentFrame();
  const p = prog(f, at, 18, Easing.out(Easing.cubic));
  return (
    <svg width={size} height={size} viewBox="0 0 24 24">
      <path
        d="M4 12.5 L9.5 18 L20 6"
        fill="none"
        stroke={color}
        strokeWidth={width}
        strokeLinecap="square"
        pathLength={1}
        strokeDasharray="1 1"
        strokeDashoffset={1 - p}
      />
    </svg>
  );
};
