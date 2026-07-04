import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, optionsFlowWsUrl } from "../api/client";

interface FlowTick {
  id?: number;
  ticker: string;
  strike: number;
  expiry: string;
  right: "C" | "P";
  exchange: string | null;
  timestamp: string;
  premium: number;
  size: number;
  trade_type: "sweep" | "block" | "single";
  sentiment: "bullish" | "bearish" | "neutral";
  iv: number | null;
  delta: number | null;
  dte: number;
  relative_volume: number | null;
  sweep_confirmed: boolean;
  large_sweep: boolean;
}

interface FlowSummaryTicker {
  ticker: string;
  bullish_premium: number;
  bearish_premium: number;
  neutral_premium: number;
  total_premium: number;
  trade_count: number;
  large_sweep_count: number;
  most_active_strike: string | null;
  bullish_ratio: number;
}

interface FlowSummary {
  as_of: string;
  total_premium_today: number;
  large_sweep_count_today: number;
  most_active_ticker: string | null;
  by_ticker: FlowSummaryTicker[];
}

const QUICK_TICKERS = ["ALL", "SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA"];
const MAX_ROWS = 250;

function fmtUsd(n: number): string {
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function fmtShort(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(0);
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-CA");
  } catch {
    return iso;
  }
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0.5;
  return Math.max(0, Math.min(1, value));
}

function sentimentColor(sentiment: FlowTick["sentiment"]): string {
  if (sentiment === "bullish") return "var(--green)";
  if (sentiment === "bearish") return "var(--red)";
  return "var(--ink-dim)";
}

function rightColor(right: FlowTick["right"]): string {
  return right === "C" ? "var(--green)" : "var(--red)";
}

function rowStyle(tick: FlowTick): React.CSSProperties {
  const style: React.CSSProperties = {
    cursor: "pointer",
    borderBottom: "1px solid var(--line-dim)",
  };
  if (tick.sentiment === "bullish") style.background = "rgba(34,197,94,0.05)";
  if (tick.sentiment === "bearish") style.background = "rgba(239,68,68,0.05)";
  if (tick.large_sweep || tick.sweep_confirmed) {
    style.borderLeft = "2px solid var(--amber)";
  }
  return style;
}

function MetricTile({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <div
      className="panel"
      style={{
        padding: "12px 14px",
        minHeight: 84,
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
      }}
    >
      <div className="kicker">{label}</div>
      <div style={{ fontFamily: "var(--mono)", fontSize: 22, color: tone || "var(--ink)", fontWeight: 700 }}>
        {value}
      </div>
      {hint ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)", lineHeight: 1.4 }}>
          {hint}
        </div>
      ) : (
        <div />
      )}
    </div>
  );
}

function Panel({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div className="panel-title">{title}</div>
        {action}
      </div>
      <div style={{ padding: 14 }}>{children}</div>
    </section>
  );
}

function FlowBar({
  bullRatio,
  callRatio,
}: {
  bullRatio: number;
  callRatio: number;
}) {
  const safeBull = Math.round(clampRatio(bullRatio) * 100);
  const safeCall = Math.round(clampRatio(callRatio) * 100);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <div className="kicker" style={{ marginBottom: 6 }}>Bull / Bear Premium</div>
        <div style={{ display: "flex", height: 10, overflow: "hidden", borderRadius: 3, background: "var(--bg-4)" }}>
          <div style={{ width: `${safeBull}%`, background: "var(--green)" }} />
          <div style={{ width: `${100 - safeBull}%`, background: "var(--red)" }} />
        </div>
        <div style={{ marginTop: 6, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
          {safeBull}% bull / {100 - safeBull}% bear
        </div>
      </div>

      <div>
        <div className="kicker" style={{ marginBottom: 6 }}>Calls / Puts Premium</div>
        <div style={{ display: "flex", height: 10, overflow: "hidden", borderRadius: 3, background: "var(--bg-4)" }}>
          <div style={{ width: `${safeCall}%`, background: "var(--cyan)" }} />
          <div style={{ width: `${100 - safeCall}%`, background: "var(--orange)" }} />
        </div>
        <div style={{ marginTop: 6, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
          {safeCall}% calls / {100 - safeCall}% puts
        </div>
      </div>
    </div>
  );
}

function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button className={`btn-t ${active ? "active" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

export default function OptionsFlow() {
  const [quickTicker, setQuickTicker] = useState("ALL");
  const [tickerDraft, setTickerDraft] = useState("");
  const [tickerFilter, setTickerFilter] = useState("ALL");
  const [right, setRight] = useState<"all" | "C" | "P">("all");
  const [sentiment, setSentiment] = useState<"" | "bullish" | "bearish" | "neutral">("");
  const [tradeType, setTradeType] = useState<"" | "sweep" | "block" | "single">("");
  const [maxDte, setMaxDte] = useState<number | "">("");
  const [minPremium, setMinPremium] = useState(100000);
  const [sortMode, setSortMode] = useState<"premium" | "recent">("premium");
  const [expanded, setExpanded] = useState<number | null>(null);

  const [rows, setRows] = useState<FlowTick[]>([]);
  const [summary, setSummary] = useState<FlowSummary | null>(null);
  const [connected, setConnected] = useState(false);

  const pausedRef = useRef(false);
  const bufferRef = useRef<FlowTick[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const closedRef = useRef(false);

  const applyTickerDraft = useCallback(() => {
    const next = tickerDraft.trim().toUpperCase();
    if (!next) {
      setQuickTicker("ALL");
      setTickerFilter("ALL");
      return;
    }
    setQuickTicker(next);
    setTickerFilter(next);
  }, [tickerDraft]);

  const clearTickerFilter = useCallback(() => {
    setTickerDraft("");
    setQuickTicker("ALL");
    setTickerFilter("ALL");
  }, []);

  const filters = useMemo(
    () => ({
      ticker: tickerFilter === "ALL" ? undefined : tickerFilter,
      right: right === "all" ? undefined : right,
      sentiment: sentiment || undefined,
      trade_type: tradeType || undefined,
      max_dte: maxDte === "" ? undefined : maxDte,
      min_premium: minPremium > 0 ? minPremium : undefined,
    }),
    [maxDte, minPremium, right, sentiment, tickerFilter, tradeType],
  );

  useEffect(() => {
    let alive = true;
    api
      .getOptionsFlow({ ...filters, limit: MAX_ROWS })
      .then((response) => {
        if (!alive) return;
        setRows(response.results || []);
      })
      .catch(() => {
        if (!alive) return;
        setRows([]);
      });
    return () => {
      alive = false;
    };
  }, [filters]);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .getOptionsFlowSummary()
        .then((response) => {
          if (!alive) return;
          setSummary(response);
        })
        .catch(() => {});

    load();
    const timer = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const flushBuffer = useCallback(() => {
    if (!bufferRef.current.length) return;
    setRows((prev) => [...bufferRef.current, ...prev].slice(0, MAX_ROWS));
    bufferRef.current = [];
  }, []);

  useEffect(() => {
    closedRef.current = false;

    const connect = () => {
      if (closedRef.current) return;
      const ws = new WebSocket(optionsFlowWsUrl({ ...filters }));
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 0;
      };
      ws.onmessage = (event) => {
        try {
          const tick: FlowTick = JSON.parse(event.data);
          if (pausedRef.current) {
            bufferRef.current = [tick, ...bufferRef.current].slice(0, MAX_ROWS);
            return;
          }
          setRows((prev) => [tick, ...prev].slice(0, MAX_ROWS));
        } catch {
          // Ignore malformed ticks from the feed.
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (closedRef.current) return;
        const delay = Math.min(1000 * 2 ** retryRef.current, 30000);
        retryRef.current += 1;
        setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closedRef.current = true;
      wsRef.current?.close();
    };
  }, [filters]);

  const displayRows = useMemo(() => {
    const copy = [...rows];
    copy.sort((left, rightItem) => {
      if (sortMode === "premium") return rightItem.premium - left.premium;
      return new Date(rightItem.timestamp).getTime() - new Date(left.timestamp).getTime();
    });
    return copy;
  }, [rows, sortMode]);

  const scannerStats = useMemo(() => {
    const base = {
      callPremium: 0,
      putPremium: 0,
      bullishPremium: 0,
      bearishPremium: 0,
      neutralPremium: 0,
      largeSweeps: 0,
      totalSize: 0,
      callCount: 0,
      putCount: 0,
      bullishCount: 0,
      bearishCount: 0,
    };

    for (const row of displayRows) {
      if (row.right === "C") {
        base.callPremium += row.premium;
        base.callCount += 1;
      } else {
        base.putPremium += row.premium;
        base.putCount += 1;
      }

      if (row.sentiment === "bullish") {
        base.bullishPremium += row.premium;
        base.bullishCount += 1;
      } else if (row.sentiment === "bearish") {
        base.bearishPremium += row.premium;
        base.bearishCount += 1;
      } else {
        base.neutralPremium += row.premium;
      }

      if (row.large_sweep) base.largeSweeps += 1;
      base.totalSize += row.size;
    }

    return base;
  }, [displayRows]);

  const bullRatio = useMemo(() => {
    const denom = scannerStats.bullishPremium + scannerStats.bearishPremium;
    if (!denom) return 0.5;
    return scannerStats.bullishPremium / denom;
  }, [scannerStats.bearishPremium, scannerStats.bullishPremium]);

  const callRatio = useMemo(() => {
    const denom = scannerStats.callPremium + scannerStats.putPremium;
    if (!denom) return 0.5;
    return scannerStats.callPremium / denom;
  }, [scannerStats.callPremium, scannerStats.putPremium]);

  const dominanceLabel = useMemo(() => {
    if (bullRatio >= 0.62 && callRatio >= 0.55) return "BULLISH CALL PRESSURE";
    if (bullRatio <= 0.38 && callRatio <= 0.45) return "BEARISH PUT PRESSURE";
    if (bullRatio >= 0.58) return "BULLISH PREMIUM LEAN";
    if (bullRatio <= 0.42) return "BEARISH PREMIUM LEAN";
    return "TWO-WAY FLOW";
  }, [bullRatio, callRatio]);

  const focusTicker = useMemo(() => {
    if (tickerFilter !== "ALL") return tickerFilter;
    if (summary?.most_active_ticker) return summary.most_active_ticker;
    return displayRows[0]?.ticker || null;
  }, [displayRows, summary?.most_active_ticker, tickerFilter]);

  const focusRows = useMemo(
    () => displayRows.filter((row) => !focusTicker || row.ticker === focusTicker),
    [displayRows, focusTicker],
  );

  const focusSummary = useMemo(
    () => summary?.by_ticker?.find((item) => item.ticker === focusTicker) || null,
    [focusTicker, summary?.by_ticker],
  );

  const leaderboard = useMemo(() => {
    const items = [...(summary?.by_ticker || [])].sort((left, rightItem) => rightItem.total_premium - left.total_premium);
    if (tickerFilter !== "ALL") return items.filter((item) => item.ticker === tickerFilter);
    return items.slice(0, 8);
  }, [summary?.by_ticker, tickerFilter]);

  const standoutTrade = displayRows[0] || null;
  const biggestSweep = displayRows.find((row) => row.large_sweep || row.sweep_confirmed) || null;

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
      <section
        className="panel"
        style={{
          padding: "14px 16px",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)", marginBottom: 3 }}>Unusual Options Activity</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--ink-dim)" }}>
            <span className={`dot ${connected ? "live" : "dead"}`} />
            <span style={{ color: "var(--ink-faint)" }}>free snapshot · volume » open interest · not a real-time OPRA tape</span>
          </div>
        </div>

        {/* Inline Calls / Puts / Bullish summary — matches the production header. */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 18, alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span className="kicker">Calls</span>
            <span className="tnum" style={{ fontSize: 14, fontWeight: 600, color: "var(--green)" }}>{fmtUsd(scannerStats.callPremium)}</span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span className="kicker">Puts</span>
            <span className="tnum" style={{ fontSize: 14, fontWeight: 600, color: "var(--red)" }}>{fmtUsd(scannerStats.putPremium)}</span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span className="kicker">Bullish</span>
            <span className="tnum" style={{ fontSize: 14, fontWeight: 600, color: bullRatio >= 0.5 ? "var(--green)" : "var(--red)" }}>{Math.round(bullRatio * 100)}%</span>
          </div>
          <button className="btn-t" onClick={() => setSortMode((current) => (current === "premium" ? "recent" : "premium"))}>
            {sortMode === "premium" ? "Show recent" : "Show unusual"}
          </button>
        </div>
      </section>

      <section className="panel" style={{ padding: 14 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {QUICK_TICKERS.map((item) => (
              <FilterButton
                key={item}
                active={quickTicker === item && tickerFilter === item}
                onClick={() => {
                  setQuickTicker(item);
                  setTickerFilter(item);
                  setTickerDraft(item === "ALL" ? "" : item);
                }}
              >
                {item}
              </FilterButton>
            ))}
          </div>

          <div className="flow-toolbar-grid">
            <div style={{ display: "flex", gap: 8, alignItems: "center", minWidth: 0 }}>
              <input
                value={tickerDraft}
                onChange={(event) => setTickerDraft(event.target.value.toUpperCase())}
                onKeyDown={(event) => {
                  if (event.key === "Enter") applyTickerDraft();
                }}
                placeholder="Specific ticker: AAPL"
                style={{
                  width: "100%",
                  minWidth: 180,
                  background: "var(--bg-3)",
                  border: "1px solid var(--line-dim)",
                  color: "var(--ink)",
                  padding: "8px 10px",
                  fontFamily: "var(--mono)",
                  fontSize: 12,
                }}
              />
              <button className="btn-t active" onClick={applyTickerDraft}>Apply</button>
              <button className="btn-t" onClick={clearTickerFilter}>Clear</button>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {(["all", "C", "P"] as const).map((value) => (
                <FilterButton key={value} active={right === value} onClick={() => setRight(value)}>
                  {value === "all" ? "Calls + Puts" : value === "C" ? "Calls" : "Puts"}
                </FilterButton>
              ))}
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {[
                { value: "", label: "All Bias" },
                { value: "bullish", label: "Bull" },
                { value: "bearish", label: "Bear" },
                { value: "neutral", label: "Neutral" },
              ].map((item) => (
                <FilterButton
                  key={item.label}
                  active={sentiment === item.value}
                  onClick={() => setSentiment(item.value as "" | "bullish" | "bearish" | "neutral")}
                >
                  {item.label}
                </FilterButton>
              ))}
            </div>

            <select
              value={tradeType}
              onChange={(event) => setTradeType(event.target.value as "" | "sweep" | "block" | "single")}
              style={{
                background: "var(--bg-3)",
                border: "1px solid var(--line-dim)",
                color: "var(--ink)",
                padding: "8px 10px",
                fontFamily: "var(--mono)",
                fontSize: 12,
              }}
            >
              <option value="">All prints</option>
              <option value="sweep">Sweeps</option>
              <option value="block">Blocks</option>
              <option value="single">Singles</option>
            </select>

            <select
              value={maxDte}
              onChange={(event) => setMaxDte(event.target.value ? Number(event.target.value) : "")}
              style={{
                background: "var(--bg-3)",
                border: "1px solid var(--line-dim)",
                color: "var(--ink)",
                padding: "8px 10px",
                fontFamily: "var(--mono)",
                fontSize: 12,
              }}
            >
              <option value="">All DTE</option>
              <option value="0">0DTE</option>
              <option value="7">0-7 DTE</option>
              <option value="30">0-30 DTE</option>
              <option value="60">0-60 DTE</option>
            </select>

            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className="kicker">Min Premium</span>
              <input
                type="range"
                min={0}
                max={1_000_000}
                step={25_000}
                value={minPremium}
                onChange={(event) => setMinPremium(Number(event.target.value))}
                style={{ width: 160 }}
              />
              <span style={{ fontFamily: "var(--mono)", minWidth: 64, color: "var(--cyan)" }}>
                {fmtUsd(minPremium)}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="flow-metrics-grid">
        <MetricTile
          label="Calls Premium"
          value={fmtUsd(scannerStats.callPremium)}
          tone="var(--green)"
          hint={`${scannerStats.callCount} call prints`}
        />
        <MetricTile
          label="Puts Premium"
          value={fmtUsd(scannerStats.putPremium)}
          tone="var(--red)"
          hint={`${scannerStats.putCount} put prints`}
        />
        <MetricTile
          label="Bull / Bear"
          value={`${pct(bullRatio)} / ${pct(1 - bullRatio)}`}
          tone={bullRatio >= 0.5 ? "var(--green)" : "var(--red)"}
          hint="premium-weighted directional split"
        />
        <MetricTile
          label="Large Sweeps"
          value={String(scannerStats.largeSweeps)}
          tone="var(--amber)"
          hint={summary ? `${summary.large_sweep_count_today} across the day` : "scanner window"}
        />
        <MetricTile
          label="Focus Ticker"
          value={focusTicker || "—"}
          tone="var(--cyan)"
          hint={focusSummary?.most_active_strike ? `hot strike ${focusSummary.most_active_strike}` : "no concentrated strike yet"}
        />
        <MetricTile
          label="Tape Size"
          value={fmtShort(scannerStats.totalSize)}
          tone="var(--ink)"
          hint={summary?.most_active_ticker ? `today leader ${summary.most_active_ticker}` : "watching live flow"}
        />
      </section>

      <div className="flow-scanner-grid">
        <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
          <Panel
            title="Unusual Options Activity"
            action={(
              <div style={{ display: "flex", alignItems: "center", gap: 10, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                <span>{displayRows.length} rows</span>
                <span>hover pauses stream</span>
              </div>
            )}
          >
            <div
              onMouseEnter={() => {
                pausedRef.current = true;
              }}
              onMouseLeave={() => {
                pausedRef.current = false;
                flushBuffer();
              }}
              style={{ maxHeight: "calc(100vh - 420px)", overflow: "auto", margin: "-14px" }}
            >
              <table className="t-table" style={{ width: "100%", fontFamily: "var(--mono)", fontSize: 12 }}>
                <thead>
                  <tr style={{ position: "sticky", top: 0, background: "var(--bg-3)", zIndex: 1 }}>
                    <Th>Time</Th>
                    <Th>Ticker</Th>
                    <Th>Bias</Th>
                    <Th>C/P</Th>
                    <Th>Strike</Th>
                    <Th>Exp</Th>
                    <Th align="right">DTE</Th>
                    <Th align="right">Premium</Th>
                    <Th align="right">Size</Th>
                    <Th align="right">Vol/OI</Th>
                    <Th align="right">IV</Th>
                    <Th>Type</Th>
                    <Th>Flags</Th>
                  </tr>
                </thead>
                <tbody>
                  {displayRows.length === 0 && (
                    <tr>
                      <td colSpan={13} style={{ padding: 24, textAlign: "center", color: "var(--ink-dim)" }}>
                        No options flow matched this scanner. Try lowering the premium filter or clearing the ticker.
                      </td>
                    </tr>
                  )}
                  {displayRows.map((row, index) => {
                    const key = row.id ?? `${row.timestamp}-${index}`;
                    const open = expanded === (row.id ?? index);
                    return (
                      <React.Fragment key={key}>
                        <tr style={rowStyle(row)} onClick={() => setExpanded(open ? null : row.id ?? index)}>
                          <td>{fmtTime(row.timestamp)}</td>
                          <td style={{ color: "var(--cyan)", fontWeight: 700 }}>{row.ticker}</td>
                          <td style={{ color: sentimentColor(row.sentiment), fontWeight: 700 }}>{row.sentiment.toUpperCase()}</td>
                          <td style={{ color: rightColor(row.right), fontWeight: 700 }}>{row.right}</td>
                          <td>{row.strike}</td>
                          <td>{fmtDate(row.expiry)}</td>
                          <td style={{ textAlign: "right" }}>{row.dte}</td>
                          <td style={{ textAlign: "right", color: row.premium >= 500000 ? "var(--amber)" : "var(--ink)" }}>
                            {fmtUsd(row.premium)}
                          </td>
                          <td style={{ textAlign: "right" }}>{fmtShort(row.size)}</td>
                          <td style={{ textAlign: "right", color: "var(--amber)" }}>
                            {row.relative_volume != null ? `${row.relative_volume.toFixed(1)}x` : "—"}
                          </td>
                          <td style={{ textAlign: "right" }}>
                            {row.iv != null ? `${Math.round(row.iv * 100)}%` : "—"}
                          </td>
                          <td style={{ textTransform: "uppercase", color: row.trade_type === "sweep" ? "var(--amber)" : "var(--ink-dim)" }}>
                            {row.trade_type}
                          </td>
                          <td>
                            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                              {row.large_sweep && <span className="mode-badge aggressive">large</span>}
                              {row.sweep_confirmed && <span className="mode-badge balanced">sweep</span>}
                              {!row.large_sweep && !row.sweep_confirmed && <span style={{ color: "var(--ink-faint)" }}>-</span>}
                            </div>
                          </td>
                        </tr>
                        {open && (
                          <tr style={{ background: "var(--bg-4)" }}>
                            <td colSpan={13} style={{ padding: "10px 14px" }}>
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 18, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
                                <span>Delta {row.delta != null ? row.delta.toFixed(2) : "—"}</span>
                                <span>Exchange {row.exchange || "—"}</span>
                                <span>Premium / contract {row.size ? fmtUsd(row.premium / row.size) : "—"}</span>
                                <span>
                                  Narrative{" "}
                                  <span style={{ color: sentimentColor(row.sentiment) }}>
                                    {row.sentiment === "bullish"
                                      ? "upside appetite"
                                      : row.sentiment === "bearish"
                                        ? "downside hedge or speculative pressure"
                                        : "neutral / structure-driven"}
                                  </span>
                                </span>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
          <Panel title="Flow Bias">
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <FlowBar bullRatio={bullRatio} callRatio={callRatio} />
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
                <BiasCell
                  label="Bullish Premium"
                  value={fmtUsd(scannerStats.bullishPremium)}
                  tone="var(--green)"
                />
                <BiasCell
                  label="Bearish Premium"
                  value={fmtUsd(scannerStats.bearishPremium)}
                  tone="var(--red)"
                />
                <BiasCell
                  label="Top Print"
                  value={standoutTrade ? `${standoutTrade.ticker} ${standoutTrade.right} ${standoutTrade.strike}` : "—"}
                  tone="var(--cyan)"
                />
                <BiasCell
                  label="Sweep Focus"
                  value={biggestSweep ? `${biggestSweep.ticker} ${biggestSweep.right}` : "None"}
                  tone="var(--amber)"
                />
              </div>
            </div>
          </Panel>

          <Panel title="Ticker Pressure">
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {leaderboard.length === 0 && (
                <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
                  No summary snapshot available for this ticker yet.
                </div>
              )}
              {leaderboard.map((item) => {
                const bull = clampRatio(item.bullish_ratio);
                return (
                  <button
                    key={item.ticker}
                    onClick={() => {
                      setTickerDraft(item.ticker);
                      setQuickTicker(item.ticker);
                      setTickerFilter(item.ticker);
                    }}
                    style={{
                      textAlign: "left",
                      background: item.ticker === focusTicker ? "rgba(212,175,55,0.08)" : "var(--bg-3)",
                      border: item.ticker === focusTicker ? "1px solid rgba(212,175,55,0.38)" : "1px solid var(--line-dim)",
                      padding: "10px 12px",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 15, color: "var(--ink)", fontWeight: 700 }}>
                        {item.ticker}
                      </span>
                      <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 11, color: bull >= 0.5 ? "var(--green)" : "var(--red)" }}>
                        {pct(bull)} bull
                      </span>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
                      <MiniStat label="Premium" value={fmtUsd(item.total_premium)} tone="var(--cyan)" />
                      <MiniStat label="Trades" value={String(item.trade_count)} tone="var(--ink)" />
                      <MiniStat label="Large" value={String(item.large_sweep_count)} tone="var(--amber)" />
                    </div>
                    <div style={{ marginTop: 8, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                      Active strike {item.most_active_strike || "—"}
                    </div>
                  </button>
                );
              })}
            </div>
          </Panel>

          <Panel title={focusTicker ? `${focusTicker} Focus` : "Ticker Focus"}>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.7 }}>
                {focusTicker
                  ? `${focusTicker} is the active focus. Use this panel to compare call appetite, put pressure, and whether the tape is being driven by sweeps or broad participation.`
                  : "Pick a ticker from the tape or pressure list to inspect its directional flow."}
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
                <BiasCell
                  label="Calls"
                  value={String(focusRows.filter((row) => row.right === "C").length)}
                  tone="var(--green)"
                />
                <BiasCell
                  label="Puts"
                  value={String(focusRows.filter((row) => row.right === "P").length)}
                  tone="var(--red)"
                />
                <BiasCell
                  label="Bullish"
                  value={fmtUsd(focusSummary?.bullish_premium || 0)}
                  tone="var(--green)"
                />
                <BiasCell
                  label="Bearish"
                  value={fmtUsd(focusSummary?.bearish_premium || 0)}
                  tone="var(--red)"
                />
                <BiasCell
                  label="Top Strike"
                  value={focusSummary?.most_active_strike || "—"}
                  tone="var(--cyan)"
                />
                <BiasCell
                  label="Large Sweeps"
                  value={String(focusSummary?.large_sweep_count || 0)}
                  tone="var(--amber)"
                />
              </div>

              <div style={{ borderTop: "1px solid var(--line-dim)", paddingTop: 12 }}>
                <div className="kicker" style={{ marginBottom: 8 }}>Scanner Read</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.8 }}>
                  {focusSummary
                    ? `${focusTicker} shows ${pct(focusSummary.bullish_ratio)} bullish premium, ${focusSummary.trade_count} tracked prints, and concentration around ${focusSummary.most_active_strike || "no clear strike"}.
                    ${focusSummary.large_sweep_count > 0 ? "Large sweeps are present, which usually means institutional urgency." : "No large sweeps yet, so read this as lighter conviction."}`
                    : "No aggregated ticker summary yet. The live tape is still usable, but conviction signals are limited until more prints arrive."}
                </div>
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return <th style={{ textAlign: align }}>{children}</th>;
}

function BiasCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-3)", padding: "10px 12px" }}>
      <div className="kicker" style={{ marginBottom: 8 }}>{label}</div>
      <div style={{ fontFamily: "var(--mono)", fontSize: 14, color: tone, fontWeight: 700 }}>{value}</div>
    </div>
  );
}

function MiniStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div>
      <div className="kicker" style={{ marginBottom: 4 }}>{label}</div>
      <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: tone }}>{value}</div>
    </div>
  );
}
