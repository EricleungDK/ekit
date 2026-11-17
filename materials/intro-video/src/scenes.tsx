// Scenes. Every string and timing comes from plan.ts (T.<scene>.<item>), so the hold-time check matches what renders.
import React from "react";
import { AbsoluteFill, Easing, interpolate, interpolateColors, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useT, Wordmark } from "./ui";
import { Check, prog, pulse, Rise, Words, type Rich } from "./motion";
import { b, T, type Item } from "./plan";

const PAD = 160;
export const PASS = "#3D7A57";
const PASS_SOFT = "rgba(61,122,87,0.12)";
const soft = Easing.inOut(Easing.sin);

/** A `words` item as rich text: its plain head, then its emphasised tail. */
const rich = (it: Item): Rich => {
  const em = it.em ?? "";
  const plain = it.text.slice(0, it.text.length - em.length);
  return [...(plain ? [plain] : []), ...(em ? [{ em }] : [])];
};

/** Headline reveal for a `words` item; `split` puts the emphasised tail on its own line, revealed in sequence. */
const Head: React.FC<{ it: Item; split?: boolean }> = ({ it, split }) => {
  if (!split || !it.em) return <Words parts={rich(it)} at={it.at} stagger={it.stagger} />;
  const plain = it.text.slice(0, it.text.length - it.em.length);
  const n = plain.split(/\s+/).filter(Boolean).length;
  return (
    <>
      <Words parts={[plain]} at={it.at} stagger={it.stagger} />
      <br />
      <Words parts={[{ em: it.em }]} at={it.at + n * (it.stagger ?? 6)} stagger={it.stagger} />
    </>
  );
};

const Display: React.FC<{ size: number; children: React.ReactNode; style?: React.CSSProperties }> = ({ size, children, style }) => {
  const t = useT();
  return (
    <div style={{ fontFamily: t.display, fontWeight: 600, fontSize: size, lineHeight: 1.08, letterSpacing: "-0.035em", color: t.text, ...style }}>
      {children}
    </div>
  );
};

/** Block reveal: 45 frames, matching plan.ts's `block` items. */
const Block: React.FC<{ at: number; y?: number; style?: React.CSSProperties; children: React.ReactNode }> = ({ at, y = 18, style, children }) => (
  <Rise at={at} dur={45} y={y} style={style}>
    {children}
  </Rise>
);

const Panel: React.FC<{ style?: React.CSSProperties; children: React.ReactNode }> = ({ style, children }) => {
  const t = useT();
  return <div style={{ border: `1.5px solid ${t.text}`, background: t.surface, ...style }}>{children}</div>;
};

const PanelHead: React.FC<{ left: React.ReactNode; right?: React.ReactNode }> = ({ left, right }) => {
  const t = useT();
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        height: 54,
        padding: "0 26px",
        borderBottom: `1px solid ${t.line}`,
        fontFamily: t.mono,
        fontSize: 20,
        color: t.muted,
      }}
    >
      <span>{left}</span>
      {right && <span>{right}</span>}
    </div>
  );
};

/* ───────────── 1. Hook ───────────── */

export const Hook: React.FC = () => {
  const t = useT();
  const f = useCurrentFrame();
  const I = T.hook;
  const [file, removed, ...lines] = I.diff.lines;
  return (
    <AbsoluteFill style={{ padding: `190px ${PAD}px 0` }}>
      <Block at={I.who.at} y={10}>
        <div style={{ fontFamily: t.mono, fontSize: 28, color: t.muted }}>{I.who.text}</div>
      </Block>
      <Display size={136} style={{ marginTop: 18 }}>
        <Head it={I.quote} />
      </Display>
      <Display size={92} style={{ marginTop: 16 }}>
        <Head it={I.line2} />
      </Display>
      <Block at={I.diff.at} y={30} style={{ marginTop: 52 }}>
        <Panel style={{ width: 900, fontFamily: t.mono, fontSize: 28 }}>
          <PanelHead left={file} right={<span style={{ color: t.accent }}>{removed}</span>} />
          <div style={{ padding: "12px 0" }}>
            {lines.map((l, i) => {
              const w = prog(f, I.diff.at + 30 + i * 12, 40, soft);
              return (
                <div key={l} style={{ position: "relative", padding: "5px 26px", whiteSpace: "pre" }}>
                  <div style={{ position: "absolute", inset: 0, background: t.accentSoft, transform: `scaleX(${w})`, transformOrigin: "left" }} />
                  <span style={{ position: "relative", color: interpolateColors(w, [0, 1], [t.text, t.accent]) }}>{l}</span>
                </div>
              );
            })}
          </div>
        </Panel>
      </Block>
    </AbsoluteFill>
  );
};

/* ───────────── 2. Catch ───────────── */

export const Catch: React.FC = () => {
  const t = useT();
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const I = T.catch;
  const rows = [I.row1, I.row2, I.row3, I.row4, I.row5, I.row6];
  const [cardLeft, cardSev, cardCounts] = I.card.parts;
  const [stampTitle, stampSub] = I.stamp.parts;
  const stamp = spring({ frame: f - I.stamp.at, fps, config: { damping: 20, stiffness: 120, mass: 0.9 } });
  return (
    <AbsoluteFill style={{ padding: `140px ${PAD}px 0` }}>
      <Display size={100}>
        <Head it={I.head} />
      </Display>
      <div style={{ position: "relative", marginTop: 48 }}>
        <Block at={I.card.at} y={24}>
          <Panel style={{ width: 1600 }}>
            <PanelHead
              left={cardLeft}
              right={
                <span>
                  <b style={{ color: t.accent }}>{cardSev}</b> {cardCounts}
                </span>
              }
            />
            <div style={{ padding: "10px 0" }}>
              {rows.map((r) => {
                const [sev, id, problem] = r.parts;
                return (
                  <Block key={id} at={r.at} y={10}>
                    <div style={{ display: "flex", gap: 22, padding: "11px 26px", fontFamily: t.mono, fontSize: 25, whiteSpace: "pre" }}>
                      <span style={{ width: 106, fontWeight: 700, color: sev === "fail" ? t.accent : t.confirm }}>{sev}</span>
                      <span style={{ width: 180, color: t.muted }}>{id}</span>
                      <span style={{ color: t.text }}>{problem}</span>
                    </div>
                  </Block>
                );
              })}
            </div>
          </Panel>
        </Block>
        <div
          style={{
            position: "absolute",
            right: 40,
            bottom: -140,
            opacity: f >= I.stamp.at ? Math.min(1, (f - I.stamp.at) / 8) : 0,
            transform: `rotate(-6deg) scale(${interpolate(stamp, [0, 1], [1.5, 1])})`,
          }}
        >
          <div style={{ border: `5px solid ${t.accent}`, padding: 5, background: "rgba(246,243,237,0.92)" }}>
            <div style={{ border: `2px solid ${t.accent}`, padding: "10px 30px 12px", textAlign: "center" }}>
              <div style={{ fontFamily: t.display, fontWeight: 700, fontSize: 60, color: t.accent, lineHeight: 1 }}>{stampTitle}</div>
              <div style={{ fontFamily: t.mono, fontSize: 20, color: t.accent, marginTop: 8, letterSpacing: "0.05em" }}>{stampSub}</div>
            </div>
          </div>
        </div>
      </div>
      <Display size={48} style={{ marginTop: 56, fontWeight: 500, letterSpacing: "-0.025em" }}>
        <Head it={I.caption} />
      </Display>
    </AbsoluteFill>
  );
};

/* ───────────── 3. The fix wanted ───────────── */

const CARD_TOP = 290;
const AGENT_TOP = 610;

export const Send: React.FC = () => {
  const t = useT();
  const f = useCurrentFrame();
  const I = T.send;
  const flyStart = I.path.at;
  const flyDur = 60;
  const fly = prog(f, flyStart, flyDur, Easing.inOut(Easing.cubic));
  const landed = pulse(f, flyStart + flyDur, 30);
  const arc = prog(f, flyStart - 10, flyDur + 10, soft);
  const [cardLeft, cardRight, sev, id, problem] = I.card.parts;
  const [agentLeft, agentRight, agentBody] = I.agent.parts;
  const [orIn, orCmd, orRest] = I.orchestrate.parts;
  const fly2 = [
    { it: I.hint, from: CARD_TOP + 54 + 76, to: AGENT_TOP + 54 + 26 },
    { it: I.forbidden, from: CARD_TOP + 54 + 76 + 50, to: AGENT_TOP + 54 + 26 + 50 },
  ];
  return (
    <AbsoluteFill>
      <Display size={84} style={{ position: "absolute", top: 130, left: PAD }}>
        <Head it={I.head} />
      </Display>

      {/* the PR comment */}
      <Block at={I.card.at} style={{ position: "absolute", top: CARD_TOP, left: PAD }}>
        <Panel style={{ width: 1600, height: 250 }}>
          <PanelHead left={cardLeft} right={<b style={{ color: t.accent }}>{cardRight}</b>} />
          <div style={{ padding: "18px 30px", fontFamily: t.mono, fontSize: 27, whiteSpace: "pre" }}>
            <span style={{ color: t.accent, fontWeight: 700 }}>{sev} </span>
            <span style={{ color: t.muted }}>{id} </span>
            <span>{problem}</span>
          </div>
          <div style={{ padding: "6px 30px", fontFamily: t.mono, fontSize: 22, color: t.muted, whiteSpace: "pre", opacity: prog(f, I.sentNote.at, 30) }}>
            {"  " + I.sentNote.text}
          </div>
        </Panel>
      </Block>

      {/* the agent, when it next works on this PR */}
      <Block at={I.agent.at} style={{ position: "absolute", top: AGENT_TOP, left: PAD }}>
        <div style={{ width: 1600, height: 200, border: `${1.5 + 1.5 * landed}px solid ${interpolateColors(landed, [0, 1], [t.text, t.accent])}`, background: t.surface }}>
          <PanelHead left={<span style={{ color: t.text, fontWeight: 500 }}>{agentLeft}</span>} right={agentRight} />
          <div style={{ padding: "26px 30px", fontFamily: t.mono, fontSize: 24, color: t.muted, opacity: 1 - prog(f, flyStart + flyDur - 20, 20) }}>
            {agentBody}
          </div>
        </div>
      </Block>

      {/* the path from the comment to the agent */}
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        <path
          d={`M ${PAD - 8} ${CARD_TOP + 125} C ${PAD - 70} ${CARD_TOP + 200}, ${PAD - 70} ${AGENT_TOP + 20}, ${PAD - 8} ${AGENT_TOP + 100}`}
          fill="none"
          stroke={t.accent}
          strokeWidth={2.5}
          pathLength={1}
          strokeDasharray="1 1"
          strokeDashoffset={1 - arc}
        />
        <polyline
          points={`${PAD - 22},${AGENT_TOP + 92} ${PAD - 8},${AGENT_TOP + 100} ${PAD - 14},${AGENT_TOP + 84}`}
          fill="none"
          stroke={t.accent}
          strokeWidth={2.5}
          opacity={arc > 0.95 ? 1 : 0}
        />
      </svg>
      <div
        style={{
          position: "absolute",
          right: PAD,
          top: (CARD_TOP + 250 + AGENT_TOP) / 2 - 16,
          fontFamily: t.mono,
          fontSize: 22,
          color: t.accent,
          opacity: prog(f, flyStart, 30),
        }}
      >
        {I.path.text}
      </div>

      {/* hint + forbidden: shown in the comment, then carried down to the agent */}
      {fly2.map(({ it, from, to }, i) => {
        const y = interpolate(fly, [0, 1], [from, to]);
        const x = PAD + 30 + Math.sin(Math.PI * fly) * -40;
        const [label, rest] = it.parts;
        return (
          <Block key={label} at={it.at} y={8} style={{ position: "absolute", top: 0, left: 0 }}>
            <div style={{ position: "absolute", left: x, top: y, fontFamily: t.mono, fontSize: 27, whiteSpace: "pre", color: i === 1 ? t.accent : t.text }}>
              <span style={{ fontWeight: 700 }}>{"  " + label}</span> {rest}
            </div>
          </Block>
        );
      })}

      <Display size={44} style={{ position: "absolute", top: 860, left: PAD, fontWeight: 500, letterSpacing: "-0.025em", color: t.muted }}>
        <Head it={I.caption} />
      </Display>
      <Block at={I.orchestrate.at} y={10} style={{ position: "absolute", top: 930, left: PAD }}>
        <div style={{ fontFamily: t.sans, fontSize: 26, color: t.muted }}>
          {orIn} <span style={{ fontFamily: t.mono, fontSize: 24, color: t.accent }}>{orCmd}</span> {orRest}
        </div>
      </Block>
    </AbsoluteFill>
  );
};

/* ───────────── 4. The loop ───────────── */

const C = { x: 800, y: 626, rx: 420, ry: 252 };
const NW = 320;
const NH = 108;
const pt = (deg: number) => ({ x: C.x + C.rx * Math.cos((deg * Math.PI) / 180), y: C.y + C.ry * Math.sin((deg * Math.PI) / 180) });
const DONE = { x: 1600, y: C.y + C.ry };
const BLOCKED = { x: 1600, y: C.y - C.ry };

const LoopNode: React.FC<{
  deg: number;
  title: string;
  sub: string;
  at: number;
  flash?: { at: number; color: string; mark: "x" | "check" }[];
  accentTitle?: boolean;
  lit?: number;
}> = ({ deg, title, sub, at, flash = [], accentTitle, lit = 0 }) => {
  const t = useT();
  const f = useCurrentFrame();
  const p = prog(f, at, 45);
  const { x, y } = pt(deg);
  const active = [...flash].reverse().find((fl) => f >= fl.at);
  const pul = active ? pulse(f, active.at, 26) : 0;
  const color = active ? active.color : t.text;
  const glow = Math.max(pul, lit);
  return (
    <div
      style={{
        position: "absolute",
        left: x - NW / 2,
        top: y - NH / 2,
        width: NW,
        height: NH,
        boxSizing: "border-box",
        padding: "0 24px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        background: t.surface,
        border: `${1.5 + 1.5 * glow}px solid ${interpolateColors(glow, [0, 1], [t.text, color])}`,
        opacity: p,
        transform: `translateY(${(1 - p) * 14}px) scale(${1 + 0.03 * pul})`,
      }}
    >
      <div style={{ fontFamily: t.sans, fontWeight: 600, fontSize: 30, letterSpacing: "-0.01em", color: accentTitle ? t.accent : t.text }}>{title}</div>
      <div style={{ fontFamily: t.sans, fontSize: 21, color: t.muted, marginTop: 6 }}>{sub}</div>
      {active && (
        <div style={{ position: "absolute", top: 14, right: 14, opacity: Math.min(1, (f - active.at) / 10) }}>
          {active.mark === "check" ? (
            <Check at={active.at} color={active.color} size={30} />
          ) : (
            <span style={{ fontFamily: t.mono, fontWeight: 700, fontSize: 26, color: active.color }}>✕</span>
          )}
        </div>
      )}
    </div>
  );
};

/** An exit box beside the ring: `lit` (0–1) turns it green. */
const Exit: React.FC<{ it: Item; pos: { x: number; y: number }; dashed?: boolean; lit?: number; children?: React.ReactNode }> = ({ it, pos, dashed, lit = 0, children }) => {
  const t = useT();
  const [title, sub] = it.parts ?? [];
  return (
    <Rise at={it.at} dur={45} y={14} style={{ position: "absolute", left: pos.x - NW / 2, top: pos.y - NH / 2 }}>
      <div
        style={{
          width: NW,
          height: NH,
          boxSizing: "border-box",
          padding: "0 24px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          border: `${1.5 + 1.5 * lit}px ${dashed ? "dashed" : "solid"} ${interpolateColors(lit, [0, 1], [t.line, PASS])}`,
          background: interpolateColors(lit, [0, 1], [t.bg, "#EEF2EC"]),
          position: "relative",
        }}
      >
        <div style={{ fontFamily: t.sans, fontWeight: 600, fontSize: 30, color: interpolateColors(lit, [0, 1], [t.muted, PASS]) }}>{title}</div>
        <div style={{ fontFamily: t.sans, fontSize: 21, color: t.muted, marginTop: 6 }}>{sub}</div>
        {children}
      </div>
    </Rise>
  );
};

export const Loop: React.FC = () => {
  const t = useT();
  const f = useCurrentFrame();
  const I = T.loop;
  const [aT, aS, cT, cS, eT, eS, sT, sS] = I.nodes.parts;
  // packet keyframes (frame → angle in degrees, clockwise from the top)
  const keys = [
    [b(5), -90], [b(6), 0], [b(7), 90], [b(7.6), 90], [b(8.6), 180], [b(10), 270],
    [b(11), 270], [b(12), 360], [b(13), 450],
  ] as const;
  const angle = interpolate(f, keys.map((k) => k[0]), keys.map((k) => k[1]), {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.sin),
  });
  const exitStart = b(13.6);
  const exitEnd = b(14.5);
  const exit = prog(f, exitStart, exitEnd - exitStart, Easing.inOut(Easing.sin));
  const onLoop = f < exitStart;
  const lp = pt(angle);
  const bottom = pt(90);
  const packet = onLoop ? lp : { x: interpolate(exit, [0, 1], [bottom.x, DONE.x]), y: bottom.y };
  const visible = f >= b(5) - 6 && f <= exitEnd + 4;
  const ring = prog(f, 40, 70, soft);
  const backArc = prog(f, b(7.6), b(8.6) - b(7.6) + 20, soft) * (1 - prog(f, b(10.5), 40));
  const exitLine = prog(f, b(13.6), 40, soft);
  const doneLit = prog(f, exitEnd, 20);
  // arrowheads on the ring, pointing clockwise
  const arrow = (deg: number, color: string) => {
    const p = pt(deg);
    const r = (deg * Math.PI) / 180;
    const tx = -C.rx * Math.sin(r);
    const ty = C.ry * Math.cos(r);
    const a = (Math.atan2(ty, tx) * 180) / Math.PI;
    return <polyline key={deg} points="-9,-7 2,0 -9,7" fill="none" stroke={color} strokeWidth={2} transform={`translate(${p.x},${p.y}) rotate(${a})`} opacity={ring > 0.9 ? 1 : 0} />;
  };
  const leftHalf = `M ${pt(90).x} ${pt(90).y} A ${C.rx} ${C.ry} 0 0 1 ${pt(270).x} ${pt(270).y}`;
  const iter = f < I.iter2.at ? I.iter1 : I.iter2;
  const status = f < I.status2.at ? I.status1 : I.status2;
  const statusColor = status === I.status1 ? t.accent : PASS;
  return (
    <AbsoluteFill>
      <Display size={70} style={{ position: "absolute", top: 108, left: PAD }}>
        <Head it={I.head} split />
      </Display>

      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        <ellipse cx={C.x} cy={C.y} rx={C.rx} ry={C.ry} fill="none" stroke={t.text} strokeWidth={1.5} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - ring} />
        <path d={leftHalf} fill="none" stroke={t.accent} strokeWidth={4} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - backArc} />
        {[45, 135, 225, 315].map((d) => arrow(d, d > 90 && d < 270 && backArc > 0.2 ? t.accent : t.text))}
        <line x1={bottom.x + NW / 2} y1={bottom.y} x2={DONE.x - NW / 2 - 6} y2={DONE.y} stroke={t.line} strokeWidth={1.5} strokeDasharray="6 7" opacity={ring} />
        <line x1={bottom.x + NW / 2} y1={bottom.y} x2={bottom.x + NW / 2 + (DONE.x - NW / 2 - 6 - bottom.x - NW / 2) * exitLine} y2={DONE.y} stroke={PASS} strokeWidth={3} />
        <polyline points={`${DONE.x - NW / 2 - 16},${DONE.y - 7} ${DONE.x - NW / 2 - 6},${DONE.y} ${DONE.x - NW / 2 - 16},${DONE.y + 7}`} fill="none" stroke={exitLine > 0.95 ? PASS : t.line} strokeWidth={2} opacity={ring} />
        {visible && (
          <g>
            <rect x={packet.x - 9} y={packet.y - 9} width={18} height={18} fill={f > exitStart ? PASS : t.accent} />
          </g>
        )}
      </svg>

      <LoopNode deg={-90} title={aT} sub={aS} at={I.nodes.at} />
      <LoopNode deg={0} title={cT} sub={cS} at={I.nodes.at + 12} />
      <LoopNode
        deg={90}
        title={eT}
        sub={eS}
        at={I.nodes.at + 24}
        flash={[
          { at: b(7), color: t.accent, mark: "x" },
          { at: b(13), color: PASS, mark: "check" },
        ]}
      />
      <LoopNode deg={180} title={sT} sub={sS} at={I.nodes.at + 36} accentTitle lit={backArc} />

      {/* exits: blocked after 3 rounds, or done */}
      <Exit it={I.blocked} pos={BLOCKED} dashed />
      <Exit it={I.done} pos={DONE} lit={doneLit}>
        {f >= exitEnd && (
          <div style={{ position: "absolute", top: 14, right: 14 }}>
            <Check at={exitEnd} color={PASS} size={30} />
          </div>
        )}
      </Exit>

      {/* centre: scope, iteration, status */}
      <div style={{ position: "absolute", left: C.x - 260, width: 520, top: C.y - 112, textAlign: "center" }}>
        <div style={{ fontFamily: t.mono, fontSize: 24, color: t.accent, opacity: prog(f, I.scope.at, 30), marginBottom: 14 }}>{I.scope.text}</div>
        <div key={iter.text} style={{ fontFamily: t.mono, fontSize: 24, color: t.muted, opacity: prog(f, iter.at, 30) }}>
          {iter.text}
        </div>
        {f >= I.status1.at && (
          <div key={status.text} style={{ marginTop: 12, fontFamily: t.display, fontWeight: 600, fontSize: 46, letterSpacing: "-0.03em", color: statusColor, opacity: prog(f, status.at, 30), transform: `translateY(${(1 - prog(f, status.at, 30)) * 10}px)` }}>
            {status.text}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};

/* ───────────── 5a. Iteration 2: every finding, resolved ───────────── */

// which resolved row (index into ROWS below) each diff line belongs to; null = a file header, -1 = a context line
const DIFF_ROW = [null, 4, 4, null, 0, 0, 0, 1, -1, 2, 2, 3, 3, 3];
const DIFF_TAG = 11;

export const FixA: React.FC = () => {
  const t = useT();
  const f = useCurrentFrame();
  const I = T.fixA;
  const rows = [I.row1, I.row2, I.row3, I.row4, I.row5];
  const tick = (i: number) => rows[i].at + 24;
  return (
    <AbsoluteFill style={{ padding: `120px ${PAD}px 0` }}>
      <Display size={84}>
        <Head it={I.head} />
      </Display>
      <div style={{ display: "flex", gap: 40, marginTop: 44, alignItems: "flex-start" }}>
        <Block at={I.diff.at} y={20}>
          <Panel style={{ width: 920, fontFamily: t.mono, fontSize: 18, padding: "6px 0 14px" }}>
            {I.diff.lines.map((line, i) => {
              const row = DIFF_ROW[i];
              if (row === null)
                return (
                  <div key={i} style={{ padding: "12px 26px 6px", fontSize: 19, color: t.muted }}>
                    {line}
                  </div>
                );
              if (row === -1)
                return (
                  <div key={i} style={{ padding: "4px 26px", whiteSpace: "pre", color: t.muted }}>
                    {line}
                  </div>
                );
              const plus = line.startsWith("+");
              const lit = prog(f, tick(row), 24, soft);
              const c = plus ? PASS : t.accent;
              return (
                <div
                  key={i}
                  style={{
                    position: "relative",
                    padding: "4px 26px",
                    whiteSpace: "pre",
                    color: c,
                    background: plus ? PASS_SOFT : t.accentSoft,
                    boxShadow: `inset ${4 + 2 * lit}px 0 0 ${interpolateColors(lit, [0, 1], ["rgba(0,0,0,0)", c])}`,
                    fontWeight: lit > 0.5 ? 600 : 400,
                  }}
                >
                  {line}
                  {i === DIFF_TAG && <span style={{ position: "absolute", right: 18, color: t.muted, fontSize: 17, fontWeight: 400 }}>{I.diffTag.text}</span>}
                </div>
              );
            })}
          </Panel>
        </Block>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {rows.map((r, i) => {
            const [id, finding, fix] = r.parts;
            return (
              <Block key={id} at={r.at} y={14}>
                <div
                  style={{
                    width: 640,
                    boxSizing: "border-box",
                    padding: "13px 22px",
                    border: `1.5px solid ${interpolateColors(prog(f, tick(i), 24, soft), [0, 1], [t.text, PASS])}`,
                    background: t.surface,
                    display: "flex",
                    alignItems: "center",
                    gap: 16,
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ fontFamily: t.mono, fontSize: 19, color: t.muted }}>
                      <span style={{ color: id.startsWith("R2-3c9") ? t.confirm : t.accent }}>{id}</span> · {finding}
                    </div>
                    <div style={{ fontFamily: t.sans, fontWeight: 600, fontSize: 26, color: t.text, marginTop: 5 }}>{fix}</div>
                  </div>
                  <Check at={tick(i)} color={PASS} size={34} />
                </div>
              </Block>
            );
          })}
        </div>
      </div>
      <Display size={48} style={{ marginTop: 40, fontWeight: 500, letterSpacing: "-0.025em" }}>
        <Head it={I.caption} />
      </Display>
    </AbsoluteFill>
  );
};

/* ───────────── 5b. And it's proven ───────────── */

export const FixB: React.FC = () => {
  const t = useT();
  const I = T.fixB;
  const cards = [I.r1, I.r2, I.r3, I.r4];
  const [passLeft, passRight, passWord, passSha] = I.pass.parts;
  return (
    <AbsoluteFill style={{ padding: `130px ${PAD}px 0` }}>
      <Display size={96}>
        <Head it={I.head} />
      </Display>
      <div style={{ display: "flex", gap: 30, marginTop: 50 }}>
        {cards.map((c) => {
          const [id, name, status, gloss] = c.parts;
          return (
            <Block key={id} at={c.at} y={20}>
              <div
                style={{
                  width: 377,
                  height: 270,
                  boxSizing: "border-box",
                  padding: "24px 26px",
                  border: `1.5px solid ${t.text}`,
                  background: t.surface,
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontFamily: t.mono, fontWeight: 700, fontSize: 30, color: t.accent }}>{id}</span>
                  <span
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      fontFamily: t.mono,
                      fontSize: 19,
                      fontWeight: 700,
                      color: PASS,
                      padding: "4px 10px",
                      background: PASS_SOFT,
                    }}
                  >
                    <Check at={c.at + 30} color={PASS} size={20} />
                    {status}
                  </span>
                </div>
                <div style={{ fontFamily: t.sans, fontWeight: 600, fontSize: 30, color: t.text, marginTop: 18 }}>{name}</div>
                <div style={{ fontFamily: t.sans, fontSize: 24, lineHeight: 1.35, color: t.muted, marginTop: 10 }}>{gloss}</div>
              </div>
            </Block>
          );
        })}
      </div>
      <Block at={I.pass.at} y={18} style={{ marginTop: 40 }}>
        <Panel style={{ width: 1600, fontFamily: t.mono, fontSize: 27 }}>
          <PanelHead left={passLeft} right={<b style={{ color: PASS }}>{passRight}</b>} />
          <div style={{ padding: "18px 28px", whiteSpace: "pre" }}>
            <b style={{ color: PASS }}>{passWord}</b>
            <span style={{ color: t.muted }}> {passSha}</span>
          </div>
        </Panel>
      </Block>
    </AbsoluteFill>
  );
};

/* ───────────── 6. Proof ───────────── */

export const Proof: React.FC = () => {
  const t = useT();
  const I = T.proof;
  const col = [580, 200, 760];
  const [titleHash, titleDone, ...heads] = I.title.parts;
  const [mechSha, mechChecks] = I.mech.parts;
  const rows = [I.row1, I.row2];
  return (
    <AbsoluteFill style={{ padding: `140px ${PAD}px 0` }}>
      <Display size={96}>
        <Head it={I.head} />
      </Display>
      <Block at={I.title.at} y={24} style={{ marginTop: 50 }}>
        <Panel style={{ width: 1600 }}>
          <div style={{ padding: "20px 30px 10px", fontFamily: t.mono, fontSize: 30, fontWeight: 700, color: t.text }}>
            {titleHash} <span style={{ color: PASS }}>{titleDone}</span>
          </div>
          <div style={{ display: "flex", padding: "10px 30px", fontFamily: t.sans, fontSize: 18, letterSpacing: "0.1em", textTransform: "uppercase", color: t.muted, borderBottom: `1px solid ${t.line}` }}>
            {heads.map((h, i) => (
              <span key={h} style={{ width: col[i] }}>
                {h}
              </span>
            ))}
          </div>
          {rows.map((r) => {
            const [crit, status, cmd, out] = r.parts;
            return (
              <Block key={crit} at={r.at} y={10}>
                <div style={{ display: "flex", alignItems: "center", padding: "18px 30px", borderBottom: `1px solid ${t.line}` }}>
                  <span style={{ width: col[0], paddingRight: 24, boxSizing: "border-box", fontFamily: t.sans, fontSize: 28, lineHeight: 1.3, color: t.text }}>{crit}</span>
                  <span style={{ width: col[1], display: "flex", alignItems: "center", gap: 10, fontFamily: t.sans, fontWeight: 600, fontSize: 26, color: PASS }}>
                    <Check at={r.at + 20} color={PASS} size={28} /> {status}
                  </span>
                  <span style={{ width: col[2], fontFamily: t.mono, fontSize: 23, lineHeight: 1.5, color: t.text, whiteSpace: "pre" }}>
                    {cmd}
                    {"\n"}
                    <span style={{ color: t.muted }}>{out}</span>
                  </span>
                </div>
              </Block>
            );
          })}
          <Block at={I.mech.at} y={10}>
            <div style={{ padding: "18px 30px 20px", fontFamily: t.mono, fontSize: 24, whiteSpace: "pre", color: t.text }}>
              <b>{mechSha}</b> <span style={{ color: PASS }}>{mechChecks}</span>
            </div>
          </Block>
        </Panel>
      </Block>
      <Display size={48} style={{ marginTop: 44, fontWeight: 500, letterSpacing: "-0.025em" }}>
        <Head it={I.caption} />
      </Display>
    </AbsoluteFill>
  );
};

/* ───────────── 7. CTA ───────────── */

export const Cta: React.FC = () => {
  const t = useT();
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const I = T.cta;
  const star = spring({ frame: f - I.star.at, fps, config: { damping: 18, stiffness: 110, mass: 0.8 } });
  const typed = (s: string, at: number) => s.slice(0, Math.max(0, Math.floor((f - at) * 3)));
  const [doctorCmd, doctorNote] = I.ciDoctor.parts;
  const [starIcon, starLabel, starUrl] = I.star.parts;
  return (
    <AbsoluteFill style={{ padding: `130px ${PAD}px 0` }}>
      <div style={{ overflow: "hidden", paddingBottom: 18 }}>
        <div style={{ transform: `translateY(${(1 - prog(f, 6, 50)) * 105}%)` }}>
          <Wordmark size={190} />
        </div>
      </div>
      <Display size={92} style={{ marginTop: 14 }}>
        <Head it={I.tagline} />
      </Display>
      <Block at={I.install.at} style={{ marginTop: 44 }}>
        <Panel style={{ display: "inline-block", padding: "22px 34px", fontFamily: t.mono, fontSize: 30, lineHeight: 1.75, minWidth: 880 }}>
          {I.install.lines.map((l, i) => (
            <div key={l} style={{ whiteSpace: "pre" }}>
              <span style={{ color: t.accent }}>$ </span>
              {typed(l, I.install.at + 5 + i * 17)}
            </div>
          ))}
          <div style={{ whiteSpace: "pre", opacity: prog(f, I.ciDoctor.at, 20) }}>
            <span style={{ color: t.accent }}>› </span>
            {typed(doctorCmd, I.ciDoctor.at)}
            <span style={{ color: t.muted, opacity: prog(f, I.ciDoctor.at + 8, 30) }}>{"   " + doctorNote}</span>
          </div>
        </Panel>
      </Block>
      <Block at={I.also.at} style={{ marginTop: 16 }}>
        <div style={{ fontFamily: t.sans, fontSize: 24, color: t.muted }}>{I.also.text}</div>
      </Block>
      <div style={{ display: "flex", alignItems: "center", gap: 28, marginTop: 36, opacity: Math.min(1, star * 1.3) }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            padding: "16px 28px",
            background: t.accent,
            color: "#FFF8F3",
            fontFamily: t.sans,
            fontWeight: 600,
            fontSize: 30,
            transform: `scale(${0.92 + 0.08 * star})`,
            transformOrigin: "left center",
          }}
        >
          <span style={{ display: "inline-block", transform: `rotate(${(1 - star) * -72}deg)` }}>{starIcon}</span>
          {starLabel}
        </div>
        <div style={{ fontFamily: t.mono, fontSize: 32, color: t.text }}>{starUrl}</div>
      </div>
    </AbsoluteFill>
  );
};
