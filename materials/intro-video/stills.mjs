// Renders key-frame stills of the video to stills/ekit-intro-<frame>.png, for checking layout without a full render.
//   node stills.mjs [frames]   e.g. node stills.mjs 300,1200,2400   (default: one frame late in each scene)
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import path from "node:path";
import { FADE_OUT, TIMELINE } from "./src/plan.ts";

const frames = process.argv[2]
  ? process.argv[2].split(",").map(Number)
  : TIMELINE.map((s) => s.from + s.dur - FADE_OUT - 10);
const serveUrl = await bundle({ entryPoint: path.resolve("src/index.ts") });
const composition = await selectComposition({ serveUrl, id: "ekit-intro", inputProps: {} });
for (const frame of frames) {
  const output = `stills/ekit-intro-${String(frame).padStart(4, "0")}.png`;
  await renderStill({ serveUrl, composition, frame, output });
  console.log(output);
}
