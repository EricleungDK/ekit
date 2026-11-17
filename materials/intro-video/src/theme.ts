// The Blueprint look: Inter Tight headlines on a dotted grid, one clay accent, hairline boxes.
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadInterTight } from "@remotion/google-fonts/InterTight";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";

const opts = { subsets: ["latin" as const] };

export const theme = {
  bg: "#EEEAE2",
  text: "#18212C",
  muted: "#66707A",
  accent: "#CF5F3A",
  accentSoft: "rgba(207,95,58,0.10)",
  line: "#B9B2A6",
  surface: "#F6F3ED",
  confirm: "#A8781F",
  display: loadInterTight("normal", { ...opts, weights: ["500", "600", "700"] }).fontFamily,
  sans: loadInter("normal", { ...opts, weights: ["400", "500", "600"] }).fontFamily,
  mono: loadMono("normal", { ...opts, weights: ["400", "500", "700"] }).fontFamily,
};

export type Theme = typeof theme;
