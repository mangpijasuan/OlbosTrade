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
import { useIsMobile } from "../hooks/useIsMobile";

// ── Icons (inline SVG — no dep) ───────────────────────────────────────────────
const Icon = ({ d, size = 16 }: { d: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const ICONS: Record<string, string> = {
  dashboard:  "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z M9 22V12h6v10",
  symphony:   "M9 18V5l12-2v13 M9 13l12-2 M6 21a3 3 0 100-6 3 3 0 000 6z M18 19a3 3 0 100-6 3 3 0 000 6z",
  equity:     "M23 6l-9.5 9.5-5-5L1 18 M17 6h6v6",
  backtest:   "M18 20V10 M12 20V4 M6 20v-6",
  paper:      "M3 3v18h18 M7 15l3-3 3 3 5-6",
  risk:       "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z M12 9v4 M12 17h.01",
  guardrails: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  journal:    "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8",
  research:   "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z",
  lab:        "M9 2v6l-5 9a2 2 0 002 3h12a2 2 0 002-3l-5-9V2 M7 2h10 M8 14h8",
  flow:       "M3 12h4l3 8 4-16 3 8h4",
  strategy:   "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  analytics:  "M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z",
  markets:    "M3 3v18h18 M7 14v3 M7 8v2 M12 6v11 M12 3v1 M17 11v6 M17 8v1",
  data:       "M12 3c4.418 0 8 1.343 8 3s-3.582 3-8 3-8-1.343-8-3 3.582-3 8-3z M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6 M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6",
  mode:       "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  settings:   "M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z",
  logout:     "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4 M16 17l5-5-5-5 M21 12H9",
  help:       "M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3 M12 17h.01 M12 22a10 10 0 100-20 10 10 0 000 20z",
};

// Grouped navigation. A group is either a leaf (has `key`, navigates directly)
// or a section (has `children`, expands to sub-items). Each leaf `key` routes
// through the alias map in App.tsx — existing pages keep working; not-yet-built
// items land on a shared "coming soon" placeholder.
type NavLeaf  = { key: string; label: string };
type NavGroup = { id: string; label: string; icon: string; key?: string; children?: NavLeaf[] };

const NAV_MODEL: NavGroup[] = [
  { id: "dashboard", label: "Command Center", icon: "dashboard", key: "dashboard" },
  { id: "markets",   label: "Markets",        icon: "markets", children: [
    { key: "markets:heatmaps",   label: "Heatmaps" },
    { key: "markets:watchlists", label: "Watchlists" },
    { key: "markets:chart",      label: "Chart" },
    { key: "markets:news",       label: "News & Catalysts" },
    { key: "markets:calendar",   label: "Calendar" },
  ]},
  { id: "trade", label: "Trade Desk", icon: "paper", children: [
    { key: "trade:copilot",   label: "Copilot Review" },
    { key: "trade:orders",    label: "Orders" },
    { key: "trade:positions", label: "Positions" },
    { key: "trade:logs",      label: "Execution Logs" },
  ]},
  { id: "strat", label: "Strategies", icon: "strategy", children: [
    { key: "equity",        label: "Signals" },
    { key: "strat:cards",   label: "Strategy Cards" },
    { key: "strat:builder", label: "Strategy Builder" },
    { key: "strat:alerts",  label: "Alerts" },
  ]},
  { id: "options", label: "Options Desk", icon: "flow", children: [
    { key: "options:chain",  label: "Options Chain" },
    { key: "scan",           label: "Spread Scanner" },
    { key: "csp",            label: "CSP Screener" },
    { key: "options:cc",     label: "Covered Calls" },
    { key: "options:wheel",  label: "Wheel Lab" },
    { key: "options:flow",   label: "Options Flow" },
  ]},
  { id: "risk", label: "Portfolio & Risk", icon: "risk", key: "risk", children: [
    { key: "risk:heat",     label: "Portfolio Heat" },
    { key: "risk:exposure", label: "Exposure" },
    { key: "risk:var",      label: "Stress & VaR" },
    { key: "risk:drawdown", label: "Drawdown" },
    { key: "risk:rules",    label: "Risk Rules" },
  ]},
  { id: "lab", label: "Research Lab", icon: "lab", children: [
    { key: "backtest",       label: "Backtests" },
    { key: "lab:walkforward",label: "Walk-Forward" },
    { key: "lab:ml",         label: "ML Models" },
    { key: "lab",            label: "Paper Validation" },
  ]},
  { id: "journal",   label: "Journal & Replay", icon: "journal",   key: "journal" },
  { id: "analytics", label: "Performance",      icon: "analytics", key: "analytics" },
  { id: "data", label: "Data & Integrations", icon: "data", children: [
    { key: "data:broker",  label: "Broker Gateway" },
    { key: "data:market",  label: "Market Data" },
    { key: "data:quality", label: "Data Quality" },
  ]},
];

// Which group owns a given active leaf key (for header highlight + auto-open).
function groupIdForKey(key: string): string | null {
  for (const g of NAV_MODEL) {
    if (g.key === key) return g.id;
    if (g.children?.some(c => c.key === key)) return g.id;
  }
  return null;
}

// ── Ticker strip ──────────────────────────────────────────────────────────────
type SnapShot = { last_close: number | null; prev_close: number | null; change_pct: number | null };

function TickerCell({ label, snap }: { label: string; snap: SnapShot }) {
  const price = snap.last_close;
  const pct   = snap.change_pct;
  const up    = pct !== null && pct >= 0;
  return (
    <>
      <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>{label}</span>
      <span style={{ color: "var(--ink)", fontWeight: 600, marginRight: 4 }}>
        {price !== null ? price.toFixed(2) : "—"}
      </span>
      <span style={{ color: pct === null ? "var(--ink-faint)" : up ? "var(--green)" : "var(--red)", marginRight: 20 }}>
        {pct !== null ? `${up ? "▲" : "▼"} ${Math.abs(pct).toFixed(2)}%` : ""}
      </span>
    </>
  );
}

// A single row in the account popover menu (Settings / Help / Log out).
function AccountMenuItem({ icon, label, onClick, danger = false }: {
  icon: string; label: string; onClick: () => void; danger?: boolean;
}) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        width: "100%", display: "flex", alignItems: "center", gap: 10,
        padding: "9px 12px", background: hover ? "var(--bg-3)" : "transparent",
        border: "none", cursor: "pointer", textAlign: "left",
        color: danger ? "var(--red)" : "var(--ink)",
      }}
    >
      <Icon d={ICONS[icon]} size={14} />
      <span style={{ fontFamily: "var(--sans)", fontSize: 12 }}>{label}</span>
    </button>
  );
}

// Header pill for a global AI mode (Copilot / Autopilot).
function ModeChip({ label, on, onColor, onClick }: {
  label: string; on: boolean; onColor: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={`${label} — click to toggle`}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        height: 22, padding: "0 9px", borderRadius: 11,
        background: on ? "var(--cyan-dim)" : "transparent",
        border: `1px solid ${on ? onColor : "var(--line-dim)"}`,
        color: on ? onColor : "var(--ink-faint)",
        fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em",
        cursor: "pointer", whiteSpace: "nowrap", transition: "all 0.12s",
      }}
    >
      <span className={`dot ${on ? "live" : "dead"}`} style={{ background: on ? onColor : undefined }} />
      {label} {on ? "ON" : "OFF"}
    </button>
  );
}

function TickerStrip({ onToggle, sidebarExpanded, isMobile }: {
  onToggle: () => void; sidebarExpanded: boolean; isMobile: boolean;
}) {
  // The header's hamburger+logo block width must track the sidebar's actual
  // rendered width so their right-side dividers stay aligned as it expands/
  // collapses. On mobile the sidebar is an overlay (doesn't reserve layout
  // space) so the header block keeps its natural, unconstrained width.
  const showFullLogo = isMobile || sidebarExpanded;
  const headerLeftWidth = isMobile ? undefined : (sidebarExpanded ? 232 : 48);

  const [time, setTime] = useState(new Date());
  const [spy,  setSpy]  = useState<SnapShot>({ last_close: null, prev_close: null, change_pct: null });
  const [qqq,  setQqq]  = useState<SnapShot>({ last_close: null, prev_close: null, change_pct: null });
  const [nvda, setNvda] = useState<SnapShot>({ last_close: null, prev_close: null, change_pct: null });
  const [iwm,  setIwm]  = useState<SnapShot>({ last_close: null, prev_close: null, change_pct: null });
  const [tlt,  setTlt]  = useState<SnapShot>({ last_close: null, prev_close: null, change_pct: null });
  const [gld,  setGld]  = useState<SnapShot>({ last_close: null, prev_close: null, change_pct: null });
  const [uso,  setUso]  = useState<SnapShot>({ last_close: null, prev_close: null, change_pct: null });
  // DXY = ICE US Dollar Index (~98–105). Previously this fed the UUP ETF (~$28),
  // which made the "DXY" ticker read a wrong ~28 value.
  const [dxy,  setDxy]  = useState<SnapShot>({ last_close: null, prev_close: null, change_pct: null });
  const [vix,  setVix]  = useState<number | null>(null);
  const [ivr,  setIvr]  = useState<number | null>(null);
  const [mode, setMode] = useState("balanced");
  // Execution mode (manual / copilot / autopilot) — the real backend tri-state.
  // The two header chips project onto it: Copilot on = copilot OR autopilot;
  // Autopilot on = autopilot. Defaults to manual (matches the no-execute gate).
  const [execMode, setExecMode] = useState<"manual" | "copilot" | "autopilot">("manual");
  const copilotOn   = execMode === "copilot" || execMode === "autopilot";
  const autopilotOn = execMode === "autopilot";

  const setExec = (m: "manual" | "copilot" | "autopilot") => {
    setExecMode(m); // optimistic
    fetch("/api/trade-desk/execution-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: m }),
    })
      .then(r => r.json())
      .then(d => { if (d.mode) setExecMode(d.mode); })
      .catch(() => {});
  };
  const toggleCopilot   = () => setExec(copilotOn ? "manual" : "copilot");
  const toggleAutopilot = () => setExec(autopilotOn ? "copilot" : "autopilot");
  const [regime, setRegime] = useState<{regime: string; equity_allowed: boolean; options_allowed: boolean; equity_strategies: string[]; options_strategies: string[]} | null>(null);

  const fetchSnapshot = (sym: string, setter: (s: SnapShot) => void) => {
    fetch(`/api/market/snapshot/${sym}`)
      .then(r => r.json())
      .then(d => setter({ last_close: d.last_close, prev_close: d.prev_close, change_pct: d.change_pct }))
      .catch(() => {});
  };

  useEffect(() => {
    // Initial fetch
    fetchSnapshot("SPY",  setSpy);
    fetchSnapshot("QQQ",  setQqq);
    fetchSnapshot("NVDA", setNvda);
    fetchSnapshot("IWM",  setIwm);
    fetchSnapshot("TLT",  setTlt);
    fetchSnapshot("GLD",  setGld);
    fetchSnapshot("USO",  setUso);
    fetchSnapshot("DX-Y.NYB", setDxy);

    fetch("/api/market/regime")
      .then(r => r.json())
      .then(d => {
        setRegime(d);
        if (d.vix    !== undefined && d.vix    !== null) setVix(d.vix);
        if (d.iv_rank !== undefined && d.iv_rank !== null) setIvr(Math.round(d.iv_rank));
      })
      .catch(() => {});

    const fetchMode = () =>
      fetch("/api/mode/current")
        .then(r => r.json())
        .then(d => setMode(d.mode || "balanced"))
        .catch(() => {});
    fetchMode();

    const fetchExec = () =>
      fetch("/api/trade-desk/execution-mode")
        .then(r => r.json())
        .then(d => { if (d.mode) setExecMode(d.mode); })
        .catch(() => {});
    fetchExec();

    // Refresh every 5 minutes
    const si = setInterval(() => {
      fetchSnapshot("SPY",  setSpy);
      fetchSnapshot("QQQ",  setQqq);
      fetchSnapshot("NVDA", setNvda);
      fetchSnapshot("IWM",  setIwm);
      fetchSnapshot("TLT",  setTlt);
      fetchSnapshot("GLD",  setGld);
      fetchSnapshot("USO",  setUso);
      fetchSnapshot("DX-Y.NYB", setDxy);
    }, 5 * 60 * 1000);

    const ri = setInterval(() => {
      fetch("/api/market/regime").then(r => r.json()).then(d => {
        setRegime(d);
        if (d.vix    !== undefined && d.vix    !== null) setVix(d.vix);
        if (d.iv_rank !== undefined && d.iv_rank !== null) setIvr(Math.round(d.iv_rank));
      }).catch(() => {});
    }, 60000);

    // Poll mode every 15 seconds so it updates immediately after user changes it
    const mi = setInterval(fetchMode, 15000);
    const ei = setInterval(fetchExec, 15000);

    return () => { clearInterval(si); clearInterval(ri); clearInterval(mi); clearInterval(ei); };
  }, []);

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

  // Build the repeating marquee content
  const sep = <span style={{ color: "var(--line-dim)", margin: "0 16px" }}>·</span>;
  const marqueeContent = (
    <span style={{ display: "inline-flex", alignItems: "center", whiteSpace: "nowrap" }}>
      {/* Equities */}
      <TickerCell label="SPY"  snap={spy}  />
      {sep}
      <TickerCell label="QQQ"  snap={qqq}  />
      {sep}
      <TickerCell label="IWM"  snap={iwm}  />
      {sep}
      <TickerCell label="NVDA" snap={nvda} />
      {sep}
      {/* Bonds */}
      <TickerCell label="TLT"  snap={tlt}  />
      {sep}
      {/* Commodities */}
      <TickerCell label="GOLD" snap={gld}  />
      {sep}
      <TickerCell label="OIL"  snap={uso}  />
      {sep}
      {/* Dollar */}
      <TickerCell label="DXY"  snap={dxy}  />
      {sep}
      {vix !== null && <>
        <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>VIX</span>
        <span style={{ color: vix > 25 ? "var(--amber)" : "var(--ink)", fontWeight: 600, marginRight: 20 }}>
          {vix.toFixed(1)}
        </span>
        {sep}
      </>}
      {ivr !== null && <>
        <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>IV RANK</span>
        <span style={{ color: ivr > 50 ? "var(--cyan)" : "var(--ink)", fontWeight: 600, marginRight: 20 }}>
          {ivr}
        </span>
        {sep}
      </>}
      <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>MODE</span>
      <span className={`mode-badge ${mode}`} style={{ marginRight: 20 }}>{mode}</span>
      {regime && <>
        {sep}
        <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>REGIME</span>
        <span style={{
          fontFamily: "var(--mono)", fontSize: 10, marginRight: 20,
          color: regime.regime === "crisis" ? "var(--red)" :
                 regime.regime.includes("high_vol") ? "var(--amber)" : "var(--cyan)",
          fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em",
        }}>
          {regime.regime.replace(/_/g, " ")}
        </span>
      </>}
      {sep}
    </span>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", flexShrink: 0 }}>
    <div style={{
      background: "var(--bg-3)",
      borderBottom: "1px solid var(--line-dim)",
      display: "flex",
      alignItems: "center",
      height: 38,
      fontFamily: "var(--mono)",
      fontSize: 11,
      flexShrink: 0,
      overflow: "hidden",
    }}>
      {/* Hamburger + logo — pinned left, width tracks the sidebar's own width
          so this block's right divider stays aligned with the sidebar's. */}
      <div style={{
        display: "flex", alignItems: "center", flexShrink: 0,
        width: headerLeftWidth, height: "100%",
        borderRight: "1px solid var(--line-dim)",
        transition: "width 0.18s ease",
      }}>
        <button
          onClick={onToggle}
          style={{
            width: 48, height: "100%", flexShrink: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: "transparent", border: "none",
            color: "var(--ink-faint)", cursor: "pointer",
            transition: "color 0.12s",
          }}
          onMouseEnter={e => (e.currentTarget.style.color = "var(--cyan)")}
          onMouseLeave={e => (e.currentTarget.style.color = "var(--ink-faint)")}
          title="Toggle sidebar"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="2" y="3.5"  width="12" height="1.5" rx="0.75" fill="currentColor"/>
            <rect x="2" y="7.25" width="12" height="1.5" rx="0.75" fill="currentColor"/>
            <rect x="2" y="11"   width="12" height="1.5" rx="0.75" fill="currentColor"/>
          </svg>
        </button>

        {showFullLogo && (
          <div style={{ display: "flex", flexDirection: "column", gap: 2, overflow: "hidden", paddingRight: 12 }}>
            <span style={{
              fontFamily: "'Georgia', 'Times New Roman', serif",
              fontWeight: 700, fontSize: 17, letterSpacing: "0.06em", lineHeight: 1, whiteSpace: "nowrap",
            }}>
              <span style={{ color: "var(--brand)" }}>OLBOS</span>
              <span style={{ color: "var(--brand)" }}>&nbsp;</span>
              <span style={{ color: "var(--ink)", fontWeight: 400 }}>QUANT</span>
            </span>
            <span style={{
              fontFamily: "var(--mono)", fontSize: 8, fontWeight: 500,
              letterSpacing: "0.55em", color: "var(--ink-faint)", lineHeight: 1, paddingLeft: 1, whiteSpace: "nowrap",
            }}>TERMINAL</span>
          </div>
        )}
      </div>

      {/* Marquee strip — scrolls continuously */}
      <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        <div style={{ display: "inline-flex", animation: "ticker-scroll 55s linear infinite" }}>
          {marqueeContent}{marqueeContent}
        </div>
      </div>

      {/* AI mode chips — pinned right, before market status */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8, flexShrink: 0,
        padding: "0 12px", borderLeft: "1px solid var(--line-dim)",
      }}>
        <ModeChip label="COPILOT" on={copilotOn}   onColor="var(--cyan)"  onClick={toggleCopilot} />
        <ModeChip label="AUTOPILOT" on={autopilotOn} onColor="var(--amber)" onClick={toggleAutopilot} />
      </div>

      {/* Market status + clock — pinned right */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10, flexShrink: 0,
        padding: "0 14px", borderLeft: "1px solid var(--line-dim)",
      }}>
        <span className={`dot ${mktOpen() ? "live" : "dead"}`} />
        <span style={{ color: "var(--ink-dim)", fontSize: 10 }}>
          {mktOpen() ? "OPEN" : "CLOSED"}
        </span>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", lineHeight: 1.25 }}>
          <div>
            <span style={{ color: "var(--ink-faint)", marginRight: 3, fontSize: 9 }}>ET</span>
            <span style={{ color: "var(--ink)", fontWeight: 500, fontSize: 11 }}>{etTime}</span>
          </div>
          <div style={{ fontSize: 9, color: "var(--ink-faint)" }}>
            {time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}
            {" "}{Intl.DateTimeFormat().resolvedOptions().timeZone.split("/").pop()?.replace("_", " ")}
          </div>
        </div>
      </div>
    </div>
    </div>
  );
}

// ── Sidebar nav ───────────────────────────────────────────────────────────────
function Sidebar({ active, onNav, expanded, isMobile = false }: {
  active: string;
  onNav: (k: string) => void;
  expanded: boolean;
  isMobile?: boolean;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  // Accordion state: which group section is expanded. Auto-opens the group that
  // owns the active page.
  const [openGroup, setOpenGroup] = useState<string | null>(() => groupIdForKey(active));
  useEffect(() => {
    const g = groupIdForKey(active);
    if (g) setOpenGroup(g);
  }, [active]);

  // On mobile, labels always show (it's a full overlay panel); on desktop they
  // appear only when expanded (icon rail otherwise).
  const showLabels = expanded || isMobile;
  const W = isMobile ? 240 : (expanded ? 232 : 48);

  const containerStyle: React.CSSProperties = isMobile
    ? {
        position: "absolute", top: 0, bottom: 0, left: 0, zIndex: 50,
        width: W, minWidth: W,
        transform: expanded ? "translateX(0)" : "translateX(-100%)",
        transition: "transform 0.2s ease",
        background: "var(--bg-2)", borderRight: "1px solid var(--line-dim)",
        display: "flex", flexDirection: "column", alignItems: "stretch",
        paddingTop: 0, paddingBottom: 8, overflowY: "auto", overflowX: "hidden",
        boxShadow: expanded ? "4px 0 24px rgba(0,0,0,0.5)" : "none",
      }
    : {
        width: W, minWidth: W,
        background: "var(--bg-2)", borderRight: "1px solid var(--line-dim)",
        display: "flex", flexDirection: "column", alignItems: "stretch",
        paddingTop: 0, paddingBottom: 8, flexShrink: 0, position: "relative",
        transition: "width 0.18s ease, min-width 0.18s ease",
        overflowY: expanded ? "auto" : "hidden", overflowX: "hidden",
      };

  // A group header is highlighted when it's a leaf on the active page, or it owns
  // the active sub-item.
  const groupActive = (g: NavGroup) =>
    g.key === active || !!g.children?.some(c => c.key === active);

  const renderGroup = (g: NavGroup) => {
    const isLeaf    = !g.children;
    const isOpen    = openGroup === g.id;
    const isActive  = groupActive(g);
    const isHovered = hovered === g.id;

    const onHeaderClick = () => {
      if (isLeaf) { onNav(g.key!); return; }
      if (!showLabels) { onNav(g.children![0].key); return; } // icon rail: jump to first item
      setOpenGroup(prev => (prev === g.id ? null : g.id));
    };

    return (
      <div key={g.id} style={{ width: "100%" }}>
        <div
          style={{ position: "relative", width: "100%" }}
          onMouseEnter={() => setHovered(g.id)}
          onMouseLeave={() => setHovered(null)}
        >
          <button
            onClick={onHeaderClick}
            style={{
              width: "100%", height: 38, display: "flex", alignItems: "center",
              justifyContent: showLabels ? "flex-start" : "center",
              paddingLeft: showLabels ? 14 : 0, gap: showLabels ? 10 : 0,
              background: isActive ? "var(--cyan-dim)" : isHovered ? "var(--bg-3)" : "transparent",
              border: "none",
              borderLeft: isActive ? "2px solid var(--cyan)" : "2px solid transparent",
              color: isActive ? "var(--cyan)" : isHovered ? "var(--ink)" : "var(--ink-faint)",
              cursor: "pointer", transition: "all 0.1s", overflow: "hidden", whiteSpace: "nowrap",
            }}
          >
            <span style={{ flexShrink: 0 }}><Icon d={ICONS[g.icon]} size={15} /></span>
            {showLabels && (
              <span style={{
                flex: 1, textAlign: "left", fontFamily: "var(--mono)", fontSize: 11,
                letterSpacing: "0.08em", textTransform: "uppercase",
              }}>
                {g.label}
              </span>
            )}
            {showLabels && !isLeaf && (
              <span style={{ flexShrink: 0, paddingRight: 12, opacity: 0.6, transition: "transform 0.15s", transform: isOpen ? "rotate(90deg)" : "none" }}>
                <Icon d="M9 18l6-6-6-6" size={12} />
              </span>
            )}
          </button>

          {/* Tooltip — only on the collapsed desktop icon rail */}
          {!showLabels && isHovered && (
            <div style={{
              position: "absolute", left: 52, top: "50%", transform: "translateY(-50%)",
              background: "var(--bg-4)", border: "1px solid var(--line-dim)", padding: "4px 10px",
              whiteSpace: "nowrap", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em",
              textTransform: "uppercase", color: "var(--ink)", zIndex: 100, pointerEvents: "none",
            }}>
              {g.label}
            </div>
          )}
        </div>

        {/* Sub-items — only when expanded and open */}
        {showLabels && !isLeaf && isOpen && g.children!.map(c => {
          const subActive  = active === c.key;
          const subHovered = hovered === c.key;
          return (
            <button
              key={c.key}
              onClick={() => onNav(c.key)}
              onMouseEnter={() => setHovered(c.key)}
              onMouseLeave={() => setHovered(null)}
              style={{
                width: "100%", height: 32, display: "flex", alignItems: "center",
                paddingLeft: 40, gap: 0,
                background: subActive ? "var(--cyan-dim)" : subHovered ? "var(--bg-3)" : "transparent",
                border: "none",
                borderLeft: subActive ? "2px solid var(--cyan)" : "2px solid transparent",
                color: subActive ? "var(--cyan)" : subHovered ? "var(--ink)" : "var(--ink-dim)",
                cursor: "pointer", transition: "all 0.1s", overflow: "hidden", whiteSpace: "nowrap",
                textAlign: "left",
              }}
            >
              <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: "0.04em" }}>
                {c.label}
              </span>
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <div style={containerStyle}>

      {/* Grouped nav */}
      {NAV_MODEL.map(renderGroup)}

      {/* Settings / account — pinned bottom, above kill switch */}
      <div style={{ flex: 1 }} />

      {/* Account plate — avatar initials + name, opens a small account menu.
          TODO: source from a real auth/user backend once one exists (see
          Settings.tsx's "presentational only" note); hardcoded for now. */}
      <div
        onMouseEnter={() => setHovered("account")}
        onMouseLeave={() => setHovered(null)}
        style={{ position: "relative", width: "100%" }}
      >
        <button
          onClick={() => setAccountMenuOpen(o => !o)}
          title="Mangpi Jasuan — Account"
          style={{
            width: "100%", height: 44, display: "flex", alignItems: "center",
            justifyContent: showLabels ? "flex-start" : "center",
            paddingLeft: showLabels ? 14 : 0, gap: showLabels ? 10 : 0,
            background: accountMenuOpen || hovered === "account" ? "var(--bg-3)" : "transparent",
            border: "none", borderTop: "1px solid var(--line-dim)",
            cursor: "pointer", overflow: "hidden", whiteSpace: "nowrap", transition: "all 0.1s",
          }}
        >
          <span style={{
            flexShrink: 0, width: 24, height: 24, borderRadius: "50%",
            background: "var(--cyan-dim)", color: "var(--cyan)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: "var(--mono)", fontSize: 10, fontWeight: 700,
          }}>
            MJ
          </span>
          {showLabels && (
            <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", lineHeight: 1.3, overflow: "hidden" }}>
              <span style={{ fontFamily: "var(--sans)", fontSize: 12, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                Mangpi Jasuan
              </span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)", letterSpacing: "0.06em" }}>
                ACCOUNT
              </span>
            </span>
          )}
        </button>
        {!showLabels && !accountMenuOpen && hovered === "account" && (
          <div style={{
            position: "absolute", left: 52, top: "50%", transform: "translateY(-50%)",
            background: "var(--bg-4)", border: "1px solid var(--line-dim)", padding: "4px 10px",
            whiteSpace: "nowrap", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em",
            textTransform: "uppercase", color: "var(--ink)", zIndex: 100, pointerEvents: "none",
          }}>
            Mangpi Jasuan
          </div>
        )}

        {/* Account menu — opens upward, anchored to the plate. On the collapsed
            icon rail it opens to the right instead, like the hover tooltips. */}
        {accountMenuOpen && (
          <>
            <div
              onClick={() => setAccountMenuOpen(false)}
              style={{ position: "fixed", inset: 0, zIndex: 90 }}
            />
            <div style={{
              position: "absolute",
              ...(showLabels
                ? { bottom: "100%", left: 8, right: 8, marginBottom: 4 }
                : { bottom: 0, left: 52 }),
              width: showLabels ? undefined : 200,
              background: "var(--bg-4)", border: "1px solid var(--line-dim)",
              borderRadius: 6, boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
              zIndex: 100, overflow: "hidden",
            }}>
              <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--line-dim)" }}>
                <div style={{ fontFamily: "var(--sans)", fontSize: 12, color: "var(--ink)" }}>Mangpi Jasuan</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)", marginTop: 2 }}>
                  mangpijasuan@zomiok.org
                </div>
              </div>
              <AccountMenuItem icon="settings" label="Settings"
                onClick={() => { setAccountMenuOpen(false); onNav("settings"); }} />
              <AccountMenuItem icon="help" label="Help"
                onClick={() => setAccountMenuOpen(false)} />
              <AccountMenuItem icon="logout" label="Log out" danger
                onClick={() => setAccountMenuOpen(false)} />
            </div>
          </>
        )}
      </div>

      {/* Kill switch at bottom */}
      <div
        onMouseEnter={() => setHovered("kill")}
        onMouseLeave={() => setHovered(null)}
        style={{ position: "relative", width: "100%" }}
      >
        <button
          onClick={() => onNav("risk")}
          title="Open the kill switch (press &amp; hold to engage on the Risk page)"
          style={{
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
      <span>TRADE DESK</span>
      <span id="broker-status-bar">IBKR GATEWAY</span>
      <span>SPY · QQQ · IWM · NVDA · AAPL</span>
      <div style={{ flex: 1 }} />
      <span style={{ color: "var(--brand)", fontWeight: 700 }}>OlbosQuant v5.0</span>
    </div>
  );
}

// ── Layout shell ──────────────────────────────────────────────────────────────
export default function TerminalLayout({ children, activePage, onNav }: {
  children: React.ReactNode;
  activePage: string;
  onNav: (key: string) => void;
}) {
  const isMobile = useIsMobile();
  // On desktop the sidebar starts collapsed (icon rail); on mobile it starts
  // hidden and slides in as an overlay.
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  // On mobile, navigating closes the overlay.
  const handleNav = (key: string) => {
    onNav(key);
    if (isMobile) setSidebarExpanded(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      <TickerStrip onToggle={() => setSidebarExpanded(p => !p)} sidebarExpanded={sidebarExpanded} isMobile={isMobile} />
      <div style={{ display: "flex", flex: 1, overflow: "hidden", position: "relative" }}>
        <Sidebar
          active={activePage}
          onNav={handleNav}
          expanded={sidebarExpanded}
          isMobile={isMobile}
        />
        {/* Tap-away backdrop when the overlay sidebar is open on mobile */}
        {isMobile && sidebarExpanded && (
          <div
            onClick={() => setSidebarExpanded(false)}
            style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 45 }}
          />
        )}
        <main style={{
          flex: 1,
          overflow: "auto",
          background: "var(--bg)",
          minWidth: 0,   // allow children to shrink instead of forcing overflow
        }}>
          {children}
        </main>
      </div>
      <StatusBar page={activePage} />
    </div>
  );
}
