import React, { createContext, useContext } from "react";
import type { Theme } from "./theme";

export const ThemeCtx = createContext<Theme | null>(null);
export const useT = () => useContext(ThemeCtx)!;

/** The ekit wordmark: the name plus a small accent square. */
export const Wordmark: React.FC<{ size: number }> = ({ size }) => {
  const t = useT();
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "baseline",
        fontFamily: t.display,
        fontWeight: 700,
        fontSize: size,
        letterSpacing: "-0.05em",
        lineHeight: 1,
        color: t.text,
      }}
    >
      ekit
      <span
        style={{
          display: "inline-block",
          width: size * 0.15,
          height: size * 0.15,
          marginLeft: size * 0.05,
          background: t.accent,
        }}
      />
    </div>
  );
};
