import React, { createContext, useContext } from "react";

/** Terminal page navigation — provided by TerminalLayout so pages can deep-link. */
const TerminalNavContext = createContext<(key: string) => void>(() => {});

export function TerminalNavProvider({
  onNav,
  children,
}: {
  onNav: (key: string) => void;
  children: React.ReactNode;
}) {
  return (
    <TerminalNavContext.Provider value={onNav}>
      {children}
    </TerminalNavContext.Provider>
  );
}

export function useTerminalNav(): (key: string) => void {
  return useContext(TerminalNavContext);
}
