/**
 * TerminalLayout — the Bloomberg-style shell.
 *
 * Structure:
 *   [TICKER STRIP]        ← top, full width, live market data
 *   [NAV SIDEBAR] [MAIN]  ← left sidebar + content area
 *   [STATUS BAR]          ← bottom, full width, system status
 *
 * The sidebar is icon-only (48px) with tooltips.
 * Active route gets a cyan left-border accent.
 */

import React, { useState, useEffect } from "react";

// ── Icons (inline SVG — no dep) ───────────────────────────────────────────────
const Icon = ({ d, size = 16 }: { d: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const ICONS: Record<string, string> = {
  dashboard:  "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z M9 22V12h6v10",
  backtest:   "M18 20V10 M12 20V4 M6 20v-6",
  paper:      "M22 12h-4l-3 9L9 3l-3 9H2",
  risk:       "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z M12 9v4 M12 17h.01",
  guardrails: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  journal:    "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8",
  research:   "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z",
  strategy:   "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  analytics:  "M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z",
  mode:       "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  settings:   "M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z",
};

const NAV_ITEMS = [
  { key: "dashboard",  label: "Dashboard",  icon: "dashboard"  },
  { key: "backtest",   label: "Backtest",   icon: "backtest"   },
  { key: "paper",      label: "Paper Trade",icon: "paper"      },
  { key: "risk",       label: "Risk",       icon: "risk"       },
  { key: "guardrails", label: "Guardrails", icon: "guardrails" },
  { key: "strategy",   label: "Strategy",   icon: "strategy"   },
  { key: "journal",    label: "Journal",    icon: "journal"    },
  { key: "research",   label: "Research",   icon: "research"   },
  { key: "analytics",  label: "Analytics",  icon: "analytics"  },
];

// ── Ticker strip ──────────────────────────────────────────────────────────────
function TickerStrip() {
  const [time, setTime] = useState(new Date());
  const [spy]  = useState({ price: 455.32, change: +1.24, pct: +0.27 });
  const [vix]  = useState(18.4);
  const [ivr]  = useState(42);
  const [mode] = useState("balanced");

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const mktOpen = () => {
    const h = time.getHours(), m = time.getMinutes();
    const day = time.getDay();
    if (day === 0 || day === 6) return false;
    const mins = h * 60 + m;
    return mins >= 570 && mins < 960; // 9:30–4:00 ET
  };

  const etTime = time.toLocaleTimeString("en-US", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    timeZone: "America/New_York", hour12: false,
  });

  return (
    <div style={{
      background: "var(--bg-3)",
      borderBottom: "1px solid var(--line-dim)",
      display: "flex",
      alignItems: "center",
      height: 36,
      padding: "0 16px",
      gap: 0,
      fontFamily: "var(--mono)",
      fontSize: 11,
      flexShrink: 0,
      overflow: "hidden",
    }}>
      {/* Logo */}
      <span style={{ color: "var(--cyan)", fontWeight: 600, letterSpacing: "0.1em", marginRight: 20 }}>
        OLBOS<span style={{ color: "var(--ink-dim)" }}>QUANT</span>
      </span>

      <div style={{ width: 1, background: "var(--line-dim)", height: 20, marginRight: 20 }} />

      {/* SPY */}
      <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>SPY</span>
      <span style={{ color: "var(--ink)", fontWeight: 600, marginRight: 4 }}>
        {spy.price.toFixed(2)}
      </span>
      <span style={{ color: spy.change >= 0 ? "var(--green)" : "var(--red)", marginRight: 20 }}>
        {spy.change >= 0 ? "▲" : "▼"} {Math.abs(spy.pct).toFixed(2)}%
      </span>

      {/* VIX */}
      <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>VIX</span>
      <span style={{ color: vix > 25 ? "var(--amber)" : "var(--ink)", fontWeight: 600, marginRight: 20 }}>
        {vix.toFixed(1)}
      </span>

      {/* IV Rank */}
      <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>IV RANK</span>
      <span style={{ color: ivr > 50 ? "var(--cyan)" : "var(--ink)", fontWeight: 600, marginRight: 20 }}>
        {ivr}
      </span>

      {/* Mode */}
      <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>MODE</span>
      <span className={`mode-badge ${mode}`} style={{ marginRight: 20 }}>{mode}</span>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Market status */}
      <span className={`dot ${mktOpen() ? "live" : "dead"}`} style={{ marginRight: 6 }} />
      <span style={{ color: "var(--ink-dim)", marginRight: 20 }}>
        {mktOpen() ? "MARKET OPEN" : "MARKET CLOSED"}
      </span>

      {/* Time */}
      <span style={{ color: "var(--ink-faint)", marginRight: 4 }}>ET</span>
      <span style={{ color: "var(--ink)", fontWeight: 500 }}>{etTime}</span>
    </div>
  );
}

// ── Sidebar nav ───────────────────────────────────────────────────────────────
function Sidebar({ active, onNav, expanded, onToggle }: {
  active: string;
  onNav: (k: string) => void;
  expanded: boolean;
  onToggle: () => void;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const W = expanded ? 200 : 48;

  return (
    <div style={{
      width: W,
      minWidth: W,
      background: "var(--bg-2)",
      borderRight: "1px solid var(--line-dim)",
      display: "flex",
      flexDirection: "column",
      alignItems: "stretch",
      paddingTop: 0,
      paddingBottom: 8,
      flexShrink: 0,
      position: "relative",
      transition: "width 0.18s ease, min-width 0.18s ease",
      overflow: "hidden",
    }}>

      {/* Hamburger toggle button */}
      <button
        onClick={onToggle}
        title={expanded ? "Collapse sidebar" : "Expand sidebar"}
        style={{
          width: "100%",
          height: 40,
          display: "flex",
          alignItems: "center",
          justifyContent: expanded ? "flex-end" : "center",
          paddingRight: expanded ? 14 : 0,
          background: "transparent",
          border: "none",
          borderBottom: "1px solid var(--line-dim)",
          borderLeft: "2px solid transparent",
          color: "var(--ink-faint)",
          cursor: "pointer",
          flexShrink: 0,
          transition: "color 0.1s",
          marginBottom: 4,
        }}
        onMouseEnter={e => (e.currentTarget.style.color = "var(--cyan)")}
        onMouseLeave={e => (e.currentTarget.style.color = "var(--ink-faint)")}
      >
        {/* Hamburger icon — three lines */}
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <rect x="2" y="3.5" width="12" height="1.5" rx="0.75" fill="currentColor"/>
          <rect x="2" y="7.25" width="12" height="1.5" rx="0.75" fill="currentColor"/>
          <rect x="2" y="11" width="12" height="1.5" rx="0.75" fill="currentColor"/>
        </svg>
      </button>

      {/* Nav items */}
      {NAV_ITEMS.map(item => {
        const isActive  = active === item.key;
        const isHovered = hovered === item.key;
        return (
          <div
            key={item.key}
            style={{ position: "relative", width: "100%" }}
            onMouseEnter={() => setHovered(item.key)}
            onMouseLeave={() => setHovered(null)}
          >
            <button
              onClick={() => onNav(item.key)}
              style={{
                width: "100%",
                height: 38,
                display: "flex",
                alignItems: "center",
                justifyContent: expanded ? "flex-start" : "center",
                paddingLeft: expanded ? 14 : 0,
                gap: expanded ? 10 : 0,
                background: isActive ? "var(--cyan-dim)" : isHovered ? "var(--bg-3)" : "transparent",
                border: "none",
                borderLeft: isActive ? "2px solid var(--cyan)" : "2px solid transparent",
                color: isActive ? "var(--cyan)" : isHovered ? "var(--ink)" : "var(--ink-faint)",
                cursor: "pointer",
                transition: "all 0.1s",
                overflow: "hidden",
                whiteSpace: "nowrap",
              }}
            >
              <span style={{ flexShrink: 0 }}>
                <Icon d={ICONS[item.icon]} size={15} />
              </span>
              {expanded && (
                <span style={{
                  fontFamily: "var(--mono)",
                  fontSize: 11,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  opacity: expanded ? 1 : 0,
                  transition: "opacity 0.15s ease",
                }}>
                  {item.label}
                </span>
              )}
            </button>

            {/* Tooltip — only when collapsed */}
            {!expanded && isHovered && (
              <div style={{
                position: "absolute",
                left: 52,
                top: "50%",
                transform: "translateY(-50%)",
                background: "var(--bg-4)",
                border: "1px solid var(--line-dim)",
                padding: "4px 10px",
                whiteSpace: "nowrap",
                fontFamily: "var(--mono)",
                fontSize: 10,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: "var(--ink)",
                zIndex: 100,
                pointerEvents: "none",
              }}>
                {item.label}
              </div>
            )}
          </div>
        );
      })}

      {/* Kill switch at bottom */}
      <div style={{ flex: 1 }} />
      <div
        onMouseEnter={() => setHovered("kill")}
        onMouseLeave={() => setHovered(null)}
        style={{ position: "relative", width: "100%" }}
      >
        <button style={{
          width: "100%",
          height: 38,
          display: "flex",
          alignItems: "center",
          justifyContent: expanded ? "flex-start" : "center",
          paddingLeft: expanded ? 14 : 0,
          gap: expanded ? 10 : 0,
          background: "transparent",
          border: "none",
          borderLeft: "2px solid transparent",
          borderTop: "1px solid var(--line-dim)",
          color: "var(--red)",
          cursor: "pointer",
          opacity: 0.8,
          overflow: "hidden",
          whiteSpace: "nowrap",
          transition: "all 0.1s",
        }}>
          <span style={{ flexShrink: 0 }}>
            <Icon d="M18.364 5.636a9 9 0 11-12.728 0M12 3v9" size={15} />
          </span>
          {expanded && (
            <span style={{
              fontFamily: "var(--mono)", fontSize: 11,
              letterSpacing: "0.08em", textTransform: "uppercase",
            }}>
              Kill Switch
            </span>
          )}
        </button>
        {!expanded && hovered === "kill" && (
          <div style={{
            position: "absolute",
            left: 52,
            top: "50%",
            transform: "translateY(-50%)",
            background: "rgba(239,68,68,0.15)",
            border: "1px solid rgba(239,68,68,0.4)",
            padding: "4px 10px",
            whiteSpace: "nowrap",
            fontFamily: "var(--mono)",
            fontSize: 10,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--red)",
            zIndex: 100,
            pointerEvents: "none",
          }}>
            Kill Switch
          </div>
        )}
      </div>
    </div>
  );
}

// ── Status bar ────────────────────────────────────────────────────────────────
function StatusBar({ page }: { page: string }) {
  return (
    <div style={{
      height: 28,
      background: "var(--bg-3)",
      borderTop: "1px solid var(--line-dim)",
      display: "flex",
      alignItems: "center",
      padding: "0 16px",
      gap: 24,
      fontFamily: "var(--mono)",
      fontSize: 10,
      color: "var(--ink-faint)",
      letterSpacing: "0.08em",
      flexShrink: 0,
    }}>
      <span style={{ color: "var(--cyan)", textTransform: "uppercase" }}>{page}</span>
      <span>PAPER TRADING</span>
      <span>TRADIER SANDBOX</span>
      <span>SPY · QQQ · IWM</span>
      <div style={{ flex: 1 }} />
      <span>OlbosQuant v5.0</span>
    </div>
  );
}

// ── Layout shell ──────────────────────────────────────────────────────────────
export default function TerminalLayout({ children, activePage, onNav }: {
  children: React.ReactNode;
  activePage: string;
  onNav: (key: string) => void;
}) {
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      <TickerStrip />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar
          active={activePage}
          onNav={onNav}
          expanded={sidebarExpanded}
          onToggle={() => setSidebarExpanded(p => !p)}
        />
        <main style={{
          flex: 1,
          overflow: "auto",
          background: "var(--bg)",
        }}>
          {children}
        </main>
      </div>
      <StatusBar page={activePage} />
    </div>
  );
}
