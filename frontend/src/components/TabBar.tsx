import React from "react";

/**
 * Minimal terminal-style tab bar. Used to fold related pages into one nav entry
 * (e.g. Risk = Monitor + Guardrails) without rewriting their internals.
 */
export interface Tab { key: string; label: string; }

export default function TabBar({ tabs, active, onChange }: {
  tabs: Tab[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div style={{
      display: "flex", gap: 0, borderBottom: "1px solid var(--line-dim)",
      background: "var(--bg-2)", flexWrap: "wrap",
    }}>
      {tabs.map(t => {
        const on = t.key === active;
        return (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            className="mono"
            style={{
              padding: "10px 18px", fontSize: 11, letterSpacing: "0.1em",
              textTransform: "uppercase", cursor: "pointer", background: "transparent",
              border: "none",
              borderBottom: on ? "2px solid var(--cyan)" : "2px solid transparent",
              color: on ? "var(--cyan)" : "var(--ink-dim)",
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
