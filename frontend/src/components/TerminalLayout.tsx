import React, { useEffect, useState } from "react";

const Icon = ({ d, size = 16 }: { d: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const ICONS: Record<string, string> = {
  chart: "M3 3v18h18 M7 14l3-3 3 2 5-7",
  dashboard: "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z M9 22V12h6v10",
  equity: "M18 20V10 M12 20V4 M6 20v-6",
  strategy: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  paper: "M22 12h-4l-3 9L9 3l-3 9H2",
  backtest: "M18 20V10 M12 20V4 M6 20v-6",
  risk: "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z M12 9v4 M12 17h.01",
  guardrails: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  journal: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8",
  research: "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z",
  analytics: "M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z",
  flow: "M3 12h4l3 8 4-16 3 8h4",
  csp: "M3 3v18h18 M8 14l3-4 3 2 4-6",
};

const NAV_SECTIONS = [
  {
    title: "Workspace",
    items: [
      { key: "chart", label: "Chart", icon: "chart", fx: "F1" },
      { key: "dashboard", label: "Dashboard", icon: "dashboard", fx: "F2" },
      { key: "signals", label: "Signals", icon: "equity", fx: "F3" },
      { key: "strategy", label: "Algo Engine", icon: "strategy", fx: "F4" },
      { key: "paper", label: "Trade Desk", icon: "paper", fx: "F5" },
    ],
  },
  {
    title: "Analytics",
    items: [
      { key: "risk", label: "Risk", icon: "risk", fx: "F6" },
      { key: "journal", label: "Journal", icon: "journal", fx: "F8" },
      { key: "research", label: "Research", icon: "research", fx: "F9" },
    ],
  },
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
            { label: "Mode", value: execMode.charAt(0).toUpperCase() + execMode.slice(1), tone: execMode === "autopilot" ? "var(--amber)" : execMode === "copilot" ? "var(--accent)" : "var(--ink)", num: false },
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

function Sidebar({
  active,
  expanded,
  onNav,
}: {
  active: string;
  expanded: boolean;
  onNav: (key: string) => void;
}) {
  const width = expanded ? 150 : 52;

  return (
    <aside style={{
      width,
      minWidth: width,
      transition: "width 0.18s ease, min-width 0.18s ease",
      background: "linear-gradient(180deg, rgba(11,18,33,0.98), rgba(8,13,24,0.98))",
      borderRight: "1px solid var(--line-dim)",
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      flexShrink: 0,
    }}>
      <div style={{ padding: expanded ? "14px 12px 8px" : "12px 0 8px", borderBottom: "1px solid var(--line-dim)" }}>
        <div style={{
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

      <div style={{ marginTop: "auto", borderTop: "1px solid var(--line-dim)", padding: expanded ? "12px 12px" : "12px 0", display: "flex", justifyContent: expanded ? "space-between" : "center", alignItems: "center" }}>
        {expanded && <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--red)", letterSpacing: "0.08em" }}>Kill Switch</span>}
        <span style={{ color: "var(--red)" }}>
          <Icon d="M18.364 5.636a9 9 0 11-12.728 0M12 3v9" size={16} />
        </span>
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
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      <TickerStrip
        activePage={activePage}
        sidebarExpanded={sidebarExpanded}
        onToggleSidebar={() => setSidebarExpanded((value) => !value)}
        onNav={onNav}
      />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar active={activePage} expanded={sidebarExpanded} onNav={onNav} />
        <main style={{ flex: 1, overflow: "auto", background: "radial-gradient(circle at top, rgba(17,30,53,0.42), transparent 26%), var(--bg)" }}>
          {children}
        </main>
      </div>
      <StatusBar page={activePage} onToggleSidebar={() => setSidebarExpanded((value) => !value)} />
    </div>
  );
}
