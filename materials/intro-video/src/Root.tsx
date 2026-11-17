import React from "react";
import { Composition } from "remotion";
import { IntroVideo } from "./Video";
import { FPS, TOTAL } from "./plan";

export const Root: React.FC = () => (
  <Composition id="ekit-intro" component={IntroVideo} durationInFrames={TOTAL} fps={FPS} width={1920} height={1080} />
);
