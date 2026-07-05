import React, { useEffect, useState } from "react";
import NotificationBell from "./NotificationBell";
import KillSwitchButton from "./KillSwitchButton";

import React, { useState, useEffect } from "react";
import { useIsMobile } from "../hooks/useIsMobile";

// ── Icons (inline SVG — no dep) ───────────────────────────────────────────────
const Icon = ({ d, size = 16 }: { d: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
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
  mode:       "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  settings:   "M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z",
};

const NAV_ITEMS = [
  { key: "dashboard",  label: "Dashboard",    icon: "dashboard"  },
  { key: "paper",      label: "Trade Desk",   icon: "paper"      },
  { key: "equity",     label: "Signals",      icon: "equity"     },
  { key: "backtest",   label: "Backtest",     icon: "backtest"   },
  { key: "lab",        label: "Research Lab", icon: "lab"        },
  { key: "risk",       label: "Risk",         icon: "risk"       },
  { key: "journal",    label: "Journal",      icon: "journal"    },
  { key: "analytics",  label: "Performance",  icon: "analytics"  },
];

const PAGE_LABELS = Object.fromEntries(
  NAV_SECTIONS.flatMap((section) => section.items.map((item) => [item.key, item.label])),
) as Record<string, string>;

type SnapShot = {
  last_close: number | null;
  change_pct: number | null;
};

function TickerCell({ label, snap }: { label: string; snap: SnapShot }) {
  const price = snap.last_close;
  const pct = snap.change_pct;
  const up = pct != null && pct >= 0;

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, marginRight: 22 }}>
      <span style={{ color: "var(--ink-dim)" }}>{label}</span>
      <span style={{ color: "var(--ink)", fontWeight: 600 }}>{price != null ? price.toFixed(2) : "—"}</span>
      <span style={{ color: pct == null ? "var(--ink-faint)" : up ? "var(--green)" : "var(--red)" }}>
        {pct == null ? "" : `${up ? "▲" : "▼"} ${Math.abs(pct).toFixed(2)}%`}
      </span>
      <span style={{ color: pct === null ? "var(--ink-faint)" : up ? "var(--green)" : "var(--red)", marginRight: 20 }}>
        {pct !== null ? `${up ? "▲" : "▼"} ${Math.abs(pct).toFixed(2)}%` : ""}
      </span>
    </>
  );
}

function TickerStrip({ onToggle }: { onToggle: () => void }) {
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

    return () => { clearInterval(si); clearInterval(ri); clearInterval(mi); };
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
}

function TickerStrip({
  activePage,
  sidebarExpanded,
  onToggleSidebar,
  onNav,
}: {
  activePage: string;
  sidebarExpanded: boolean;
  onToggleSidebar: () => void;
  onNav: (key: string) => void;
}) {
  const [time, setTime] = useState(new Date());
  const [menuOpen, setMenuOpen] = useState(false);
  const [snapshots, setSnapshots] = useState<Record<string, SnapShot>>({
    SPY: { last_close: null, change_pct: null },
    QQQ: { last_close: null, change_pct: null },
    NVDA: { last_close: null, change_pct: null },
    TLT: { last_close: null, change_pct: null },
    GLD: { last_close: null, change_pct: null },
    USO: { last_close: null, change_pct: null },
  });
  const [regime, setRegime] = useState<any>(null);
  const [portfolio, setPortfolio] = useState<any>(null);
  const [execMode, setExecMode] = useState("manual");

  const loadSnapshot = (symbol: string) =>
    fetch(`/api/market/snapshot/${symbol}`)
      .then((res) => res.json())
      .then((data) => ({ [symbol]: { last_close: data.last_close, change_pct: data.change_pct } }))
      .catch(() => ({ [symbol]: { last_close: null, change_pct: null } }));

  useEffect(() => {
    const loadAll = () => {
      Promise.all(["SPY", "QQQ", "NVDA", "TLT", "GLD", "USO"].map(loadSnapshot))
        .then((result) => setSnapshots((prev) => ({ ...prev, ...Object.assign({}, ...result) })))
        .catch(() => {});
      fetch("/api/market/regime").then((res) => res.json()).then(setRegime).catch(() => setRegime(null));
      fetch("/api/paper-trade/portfolio").then((res) => res.json()).then((data) => setPortfolio(data.portfolio || null)).catch(() => setPortfolio(null));
      fetch("/api/trade-desk/execution-mode").then((res) => res.json()).then((data) => setExecMode(data.mode || "manual")).catch(() => setExecMode("manual"));
    };

    loadAll();
    const fast = setInterval(() => setTime(new Date()), 1000);
    const slow = setInterval(loadAll, 60000);
    return () => {
      clearInterval(fast);
      clearInterval(slow);
    };
  }, []);

  const etParts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(time);
  const etHour = Number(etParts.find((part) => part.type === "hour")?.value || "0");
  const etMinute = Number(etParts.find((part) => part.type === "minute")?.value || "0");
  const day = Number(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short" }).format(time) === "Sun" ? 0 :
    new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short" }).format(time) === "Sat" ? 6 : 1);
  const etMinutes = etHour * 60 + etMinute;
  const marketOpen = day !== 0 && day !== 6 && etMinutes >= 570 && etMinutes < 960;

  return (
    <div style={{
      background: "linear-gradient(180deg, rgba(16,24,43,0.98), rgba(11,18,33,0.98))",
      borderBottom: "1px solid var(--line-dim)",
      boxShadow: "0 10px 30px rgba(0,0,0,0.22)",
      flexShrink: 0,
    }}>
      <div style={{
        display: "grid",
        gridTemplateColumns: "auto 48px minmax(0, 1fr) auto",
        alignItems: "stretch",
        minHeight: 46,
      }} className="terminal-top-strip">
        <div style={{
          borderRight: "1px solid var(--line-dim)",
          padding: "0 14px",
          display: "flex",
          alignItems: "center",
          background: "linear-gradient(180deg, rgba(10,18,33,0.86), rgba(7,12,23,0.96))",
        }}>
          <div style={{
            fontFamily: "'Georgia', 'Times New Roman', serif",
            fontSize: 15,
            lineHeight: 1,
            letterSpacing: "0.04em",
            whiteSpace: "nowrap",
          }}>
            <span style={{ color: "var(--brand)", fontWeight: 700 }}>OLBOS</span>
            <span style={{ color: "#e5e7eb", fontWeight: 400 }}>QUANT</span>
          </div>
        </div>

        <button
          onClick={onToggleSidebar}
          aria-label={sidebarExpanded ? "Collapse sidebar" : "Expand sidebar"}
          title={sidebarExpanded ? "Collapse sidebar" : "Expand sidebar"}
          style={{
            border: "none",
            borderRight: "1px solid var(--line-dim)",
            background: "linear-gradient(180deg, rgba(10,18,33,0.9), rgba(7,12,23,0.98))",
            color: sidebarExpanded ? "var(--ink)" : "var(--ink-dim)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transition: "color 0.14s ease, background 0.14s ease",
          }}
        >
          <span style={{
            width: 30,
            height: 30,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 4,
            background: sidebarExpanded ? "var(--fill-active)" : "transparent",
          }}>
            {sidebarExpanded ? (
              <svg width="18" height="18" viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
                <path d="M6 6l10 10" />
                <path d="M16 6L6 16" />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
                <path d="M5 7h14" />
                <path d="M5 12h14" />
                <path d="M5 17h14" />
              </svg>
            )}
          </span>
        </button>

        <div style={{
          overflow: "hidden",
          display: "flex",
          alignItems: "center",
          position: "relative",
          fontFamily: "var(--mono)",
          fontSize: 11,
          padding: "0 12px",
        }}>
          <div style={{ display: "inline-flex", animation: "ticker-scroll 55s linear infinite", whiteSpace: "nowrap" }}>
            <TickerCell label="SPY" snap={snapshots.SPY} />
            <TickerCell label="QQQ" snap={snapshots.QQQ} />
            <TickerCell label="NVDA" snap={snapshots.NVDA} />
            <TickerCell label="TLT" snap={snapshots.TLT} />
            <TickerCell label="GOLD" snap={snapshots.GLD} />
            <TickerCell label="OIL" snap={snapshots.USO} />
            <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>REGIME</span>
            <span style={{ color: regime?.regime?.includes("high_vol") ? "var(--amber)" : "var(--accent)", marginRight: 18 }}>
              {(regime?.regime || "unknown").replace(/_/g, " ").toUpperCase()}
            </span>
            <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>IVR</span>
            <span className="tnum" style={{ color: "var(--ink)", marginRight: 18 }}>
              {regime?.iv_rank != null ? Math.round(regime.iv_rank) : "—"}
            </span>
            <span style={{ color: "var(--ink-dim)", marginRight: 6 }}>ACTIVE</span>
            <span style={{ color: "var(--ink)" }}>{PAGE_LABELS[activePage] || activePage}</span>
          </div>
        </div>

        <div style={{
          display: "flex",
          alignItems: "center",
          borderLeft: "1px solid var(--line-dim)",
        }} className="terminal-operator-strip">
          {[
            { label: "Exec Mode", value: execMode.charAt(0).toUpperCase() + execMode.slice(1), tone: execMode === "autopilot" ? "var(--amber)" : execMode === "copilot" ? "var(--accent)" : "var(--ink)", num: false },
            { label: "Day P&L", value: portfolio?.total_pnl != null ? `${portfolio.total_pnl >= 0 ? "+" : "-"}$${Math.abs(portfolio.total_pnl).toFixed(2)}` : "—", tone: (portfolio?.total_pnl ?? 0) >= 0 ? "var(--green)" : "var(--red)", num: true },
            { label: "Portfolio", value: portfolio?.account_value != null ? `$${Number(portfolio.account_value).toLocaleString()}` : "—", tone: "var(--ink)", num: true },
            { label: marketOpen ? "Market" : "Session", value: marketOpen ? "Open" : "Closed", tone: marketOpen ? "var(--green)" : "var(--red)", num: false },
          ].map((item) => (
            <div key={item.label} style={{
              display: "flex", alignItems: "center", gap: 7,
              padding: "0 14px", height: "100%",
              borderLeft: "1px solid var(--line-dim)",
            }}>
              <span className="kicker">{item.label}</span>
              <span className={item.num ? "tnum" : undefined}
                style={{ fontSize: 13, color: item.tone, fontWeight: 600, fontFamily: item.num ? undefined : "var(--sans)" }}>
                {item.value}
              </span>
            </div>
          ))}
          {/* Clock — relocated from the removed workspace tab bar. */}
          <span className="mono" style={{
            color: "var(--ink-dim)", fontSize: 11,
            padding: "0 14px", height: "100%",
            display: "flex", alignItems: "center",
            borderLeft: "1px solid var(--line-dim)",
          }}>
            {time.toLocaleTimeString("en-US", { timeZone: "America/Chicago", hourCycle: "h23" })} CDT
          </span>
          {/* Notification Center bell. */}
          <div style={{ padding: "0 4px 0 12px", borderLeft: "1px solid var(--line-dim)", display: "flex", alignItems: "center" }}>
            <NotificationBell />
          </div>
          {/* Profile menu — account dropdown. */}
          <div style={{ position: "relative", margin: "0 10px 0 14px" }}>
            <button
              aria-label="Account menu"
              aria-expanded={menuOpen}
              title="Account"
              onClick={() => setMenuOpen(o => !o)}
              style={{
                display: "flex", alignItems: "center", gap: 6, padding: "4px 6px",
                border: "none", background: "transparent", cursor: "pointer",
              }}
            >
              <span style={{
                width: 24, height: 24, borderRadius: "50%",
                background: "var(--fill-active)", color: "var(--ink-dim)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 11, fontWeight: 600, fontFamily: "var(--sans)",
              }}>MJ</span>
              <span style={{ color: "var(--ink-dim)", fontSize: 10 }}>▾</span>
            </button>
            {menuOpen && (
              <>
                <div onClick={() => setMenuOpen(false)}
                  style={{ position: "fixed", inset: 0, zIndex: 40 }} />
                <div style={{
                  position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 41,
                  minWidth: 180, background: "var(--bg-2)", border: "1px solid var(--line-dim)",
                  borderRadius: 6, boxShadow: "0 8px 24px rgba(0,0,0,0.4)", overflow: "hidden",
                }}>
                  <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--line-dim)" }}>
                    <div style={{ fontSize: 13, color: "var(--ink)" }}>MJ</div>
                    <div style={{ fontSize: 11, color: "var(--ink-dim)" }}>mangpijasuan@zomiok.org</div>
                  </div>
                  {[
                    { label: "Settings", act: () => onNav("settings") },
                    { label: "Broker integrations", act: () => onNav("settings") },
                    { label: "Billing", act: () => onNav("settings") },
                  ].map(item => (
                    <button key={item.label}
                      onClick={() => { item.act(); setMenuOpen(false); }}
                      style={{
                        display: "block", width: "100%", textAlign: "left",
                        padding: "8px 12px", background: "transparent", border: "none",
                        color: "var(--ink-dim)", fontSize: 13, cursor: "pointer",
                      }}
                      onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-3)")}
                      onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                    >{item.label}</button>
                  ))}
                  <button
                    onClick={() => setMenuOpen(false)}
                    style={{
                      display: "block", width: "100%", textAlign: "left",
                      padding: "8px 12px", background: "transparent",
                      borderTop: "1px solid var(--line-dim)", borderLeft: "none", borderRight: "none", borderBottom: "none",
                      color: "var(--red)", fontSize: 13, cursor: "pointer",
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-3)")}
                    onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                  >Sign out</button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sidebar nav ───────────────────────────────────────────────────────────────
function Sidebar({ active, onNav, expanded, isMobile = false }: {
  active: string;
  expanded: boolean;
  isMobile?: boolean;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  // On mobile, labels always show (it's a full overlay panel); on desktop they
  // appear only when expanded (icon rail otherwise).
  const showLabels = expanded || isMobile;
  const W = isMobile ? 220 : (expanded ? 200 : 48);

  const containerStyle: React.CSSProperties = isMobile
    ? {
        position: "absolute", top: 0, bottom: 0, left: 0, zIndex: 50,
        width: W, minWidth: W,
        transform: expanded ? "translateX(0)" : "translateX(-100%)",
        transition: "transform 0.2s ease",
        background: "var(--bg-2)", borderRight: "1px solid var(--line-dim)",
        display: "flex", flexDirection: "column", alignItems: "stretch",
        paddingTop: 0, paddingBottom: 8, overflow: "hidden",
        boxShadow: expanded ? "4px 0 24px rgba(0,0,0,0.5)" : "none",
      }
    : {
        width: W, minWidth: W,
        background: "var(--bg-2)", borderRight: "1px solid var(--line-dim)",
        display: "flex", flexDirection: "column", alignItems: "stretch",
        paddingTop: 0, paddingBottom: 8, flexShrink: 0, position: "relative",
        transition: "width 0.18s ease, min-width 0.18s ease", overflow: "hidden",
      };

  return (
    <div style={containerStyle}>

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
                justifyContent: showLabels ? "flex-start" : "center",
                paddingLeft: showLabels ? 14 : 0,
                gap: showLabels ? 10 : 0,
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
              {showLabels && (
                <span style={{
                  fontFamily: "var(--mono)",
                  fontSize: 11,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                }}>
                  {item.label}
                </span>
              )}
            </button>

            {/* Tooltip — only on the collapsed desktop icon rail */}
            {!showLabels && isHovered && (
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
          justifyContent: expanded ? "space-between" : "center",
        }}>
          {expanded && <span className="panel-title">Workspace</span>}
          <span style={{
            width: 10,
            height: 10,
            borderRadius: 999,
            background: "var(--green)",
            boxShadow: "0 0 10px rgba(24,195,126,0.7)",
          }} />
        </div>
      </div>

      <div style={{ padding: expanded ? "10px 10px 14px" : "8px 8px 14px", overflowY: "auto", display: "flex", flexDirection: "column", gap: 16 }}>
        {NAV_SECTIONS.map((section) => (
          <div key={section.title}>
            {expanded && (
              <div style={{
                fontFamily: "var(--sans)",
                fontSize: 10,
                fontWeight: 600,
                color: "var(--ink-dim)",
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                marginBottom: 5,
                paddingLeft: 4,
              }}>
                {section.title}
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {section.items.map((item) => {
                const isActive = item.key === active;
                return (
                  <button
                    key={item.key}
                    onClick={() => onNav(item.key)}
                    title={item.label}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: expanded ? 9 : 0,
                      justifyContent: expanded ? "flex-start" : "center",
                      width: "100%",
                      minHeight: 28,
                      padding: expanded ? "0 8px" : "0",
                      borderRadius: 4,
                      border: "1px solid transparent",
                      background: isActive ? "var(--fill-active)" : "transparent",
                      color: isActive ? "var(--ink)" : "var(--ink-dim)",
                      cursor: "pointer",
                    }}
                  >
                    <span style={{ color: isActive ? "var(--ink)" : "var(--ink-faint)" }}>
                      <Icon d={ICONS[item.icon]} size={16} />
                    </span>
                    {expanded && (
                      <span style={{ fontFamily: "var(--sans)", fontSize: 12 }}>{item.label}</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: "auto", borderTop: "1px solid var(--line-dim)", padding: expanded ? "12px 12px" : "12px 8px" }}>
        <KillSwitchButton variant="sidebar" expanded={expanded} />
      </div>
    </aside>
  );
}

function StatusBar({ page, onToggleSidebar }: { page: string; onToggleSidebar: () => void }) {
  return (
    <div style={{
      height: 34,
      borderTop: "1px solid var(--line-dim)",
      background: "rgba(9,14,25,0.98)",
      display: "flex",
      alignItems: "center",
      gap: 12,
      padding: "0 12px",
      fontFamily: "var(--mono)",
      fontSize: 10,
      letterSpacing: "0.08em",
      color: "var(--ink-faint)",
      flexShrink: 0,
    }}>
      <button
        onClick={onToggleSidebar}
        style={{
          border: "1px solid rgba(244,198,79,0.22)",
          background: "transparent",
          color: "var(--cyan)",
          padding: "3px 10px",
          cursor: "pointer",
          fontFamily: "var(--mono)",
          fontSize: 10,
          textTransform: "uppercase",
        }}
      >
        Menu
      </button>
      <span style={{ color: "var(--green)" }}>DATA OK</span>
      <span>BROKER LAYER READY</span>
      <span>PAGE {PAGE_LABELS[page] || page}</span>
      <div style={{ flex: 1 }} />
      <span style={{ color: "#f4c64f", fontWeight: 700 }}>OlbosQuant v5.0</span>
    </div>
  );
}

export default function TerminalLayout({
  children,
  activePage,
  onNav,
}: {
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
      <TickerStrip onToggle={() => setSidebarExpanded(p => !p)} />
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
      <StatusBar page={activePage} onToggleSidebar={() => setSidebarExpanded((value) => !value)} />
    </div>
  );
}
