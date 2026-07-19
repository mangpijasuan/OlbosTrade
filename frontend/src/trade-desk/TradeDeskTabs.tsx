/**
 * Trade Desk primary tabs — workspace switch without full-page remount of shell chrome.
 */

import React from "react";

export type TradeDeskTab =
  | "overview"
  | "equities"
  | "options"
  | "copilot"
  | "positions"
  | "orders"
  | "execution"
  | "replay"
  | "settings";

export const TRADE_DESK_TABS: { key: TradeDeskTab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "equities", label: "Equities" },
  { key: "options", label: "Options" },
  { key: "copilot", label: "Copilot" },
  { key: "positions", label: "Positions" },
  { key: "orders", label: "Orders" },
  { key: "execution", label: "Execution" },
  { key: "replay", label: "Replay" },
  { key: "settings", label: "Settings" },
];

export function tabFromNavKey(pageKey: string): TradeDeskTab {
  const map: Record<string, TradeDeskTab> = {
    "trade:overview": "overview",
    "trade:equity": "equities",
    "trade:options": "options",
    "trade:copilot": "copilot",
    "trade:positions": "positions",
    "trade:orders": "orders",
    "trade:execlog": "execution",
    "trade:replay": "replay",
    "trade:settings": "settings",
    // Legacy aliases while flag is on
    "trade:logs": "overview",
    paper: "overview",
  };
  return map[pageKey] ?? "overview";
}

export function navKeyFromTab(tab: TradeDeskTab): string {
  const map: Record<TradeDeskTab, string> = {
    overview: "trade:overview",
    equities: "trade:equity",
    options: "trade:options",
    copilot: "trade:copilot",
    positions: "trade:positions",
    orders: "trade:orders",
    execution: "trade:execlog",
    replay: "trade:replay",
    settings: "trade:settings",
  };
  return map[tab];
}

export default function TradeDeskTabs({
  active,
  onChange,
  badges,
}: {
  active: TradeDeskTab;
  onChange: (tab: TradeDeskTab) => void;
  badges?: Partial<Record<TradeDeskTab, number | string>>;
}) {
  const moveFocus = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const buttons = Array.from(
      event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]') || [],
    );
    if (!buttons.length) return;
    const next =
      event.key === "Home" ? 0 :
      event.key === "End" ? buttons.length - 1 :
      (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next].focus();
    buttons[next].click();
  };

  return (
    <div
      role="tablist"
      aria-label="Trade Desk workspaces"
      style={{
        display: "flex",
        gap: 0,
        borderBottom: "1px solid var(--line-dim)",
        background: "var(--bg-2)",
        flexWrap: "nowrap",
        flexShrink: 0,
        overflowX: "auto",
        WebkitOverflowScrolling: "touch",
      }}
    >
      {TRADE_DESK_TABS.map((t, index) => {
        const on = t.key === active;
        const badge = badges?.[t.key];
        return (
          <button
            type="button"
            role="tab"
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            key={t.key}
            onClick={() => onChange(t.key)}
            onKeyDown={(e) => moveFocus(e, index)}
            className="mono"
            style={{
              padding: "10px 14px",
              fontSize: 11,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              cursor: "pointer",
              background: "transparent",
              border: "none",
              borderBottom: on ? "2px solid var(--cyan)" : "2px solid transparent",
              color: on ? "var(--cyan)" : "var(--ink-dim)",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              flexShrink: 0,
              whiteSpace: "nowrap",
            }}
          >
            {t.label}
            {badge != null && badge !== 0 && badge !== "" && (
              <span
                style={{
                  fontSize: 9,
                  padding: "1px 5px",
                  border: "1px solid var(--line)",
                  color: "var(--amber)",
                  background: "var(--bg-3)",
                }}
              >
                {badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
