/**
 * Panel layout persistence for Trade Desk shell (Phase B).
 * Collapse/expand rails; widths stored per user in localStorage.
 */

import React, { useCallback, useState } from "react";

const STORAGE_KEY = "olbos.tradeDesk.panelLayout.v1";

export type PanelId = "discovery" | "intelligence" | "activity";

export interface PanelLayoutState {
  discoveryCollapsed: boolean;
  intelligenceCollapsed: boolean;
  activityCollapsed: boolean;
  discoveryWidth: number;
  intelligenceWidth: number;
  activityHeight: number;
}

export const DEFAULT_PANEL_LAYOUT: PanelLayoutState = {
  discoveryCollapsed: false,
  intelligenceCollapsed: false,
  activityCollapsed: false,
  discoveryWidth: 260,
  intelligenceWidth: 300,
  activityHeight: 180,
};

function loadLayout(): PanelLayoutState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_PANEL_LAYOUT };
    return { ...DEFAULT_PANEL_LAYOUT, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_PANEL_LAYOUT };
  }
}

function saveLayout(state: PanelLayoutState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* ignore */
  }
}

export function usePanelLayout() {
  const [layout, setLayout] = useState<PanelLayoutState>(loadLayout);

  const update = useCallback((patch: Partial<PanelLayoutState>) => {
    setLayout((prev) => {
      const next = { ...prev, ...patch };
      saveLayout(next);
      return next;
    });
  }, []);

  const toggle = useCallback((id: PanelId) => {
    setLayout((prev) => {
      const key =
        id === "discovery" ? "discoveryCollapsed" :
        id === "intelligence" ? "intelligenceCollapsed" :
        "activityCollapsed";
      const next = { ...prev, [key]: !prev[key] };
      saveLayout(next);
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    const next = { ...DEFAULT_PANEL_LAYOUT };
    saveLayout(next);
    setLayout(next);
  }, []);

  return { layout, update, toggle, reset };
}

/** Thin chrome for a collapsible rail — used by Equity/Options desks in later phases. */
export function PanelChrome({
  title,
  collapsed,
  onToggle,
  children,
  style,
}: {
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className="instrument-card"
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        ...style,
      }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "6px 10px",
          border: "none",
          borderBottom: collapsed ? "none" : "1px solid var(--line-dim)",
          background: "var(--bg-3)",
          color: "var(--ink-dim)",
          fontFamily: "var(--mono)",
          fontSize: 10,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          cursor: "pointer",
        }}
      >
        <span>{title}</span>
        <span aria-hidden>{collapsed ? "+" : "−"}</span>
      </button>
      {!collapsed && (
        <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>{children}</div>
      )}
    </div>
  );
}
