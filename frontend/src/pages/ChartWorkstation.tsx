import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { usePaperTrade } from "../hooks/usePaperTrade";
import { useRisk } from "../hooks/useRisk";

type Timeframe = "5m" | "15m" | "1h" | "1d";

interface ChartBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface WatchSnapshot {
  symbol: string;
  last_close: number | null;
  change_pct: number | null;
}

interface Signal {
  id: string;
  ticker: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  generated_at: string;
  reasons?: string[];
  trade_plan?: {
    entry_price?: number;
    stop_price?: number;
    target_price?: number;
    shares?: number;
    risk_reward?: number;
    risk_dollars?: number;
  };
  indicators?: {
    rsi?: number;
    macd?: number;
    bb_pct_b?: number;
    volume_ratio?: number;
  };
}

const WATCHLIST = ["AAPL", "NVDA", "MSFT", "META", "AMZN", "QQQ", "SPY"];
const TIMEFRAMES: { key: Timeframe; label: string; limit: number }[] = [
  { key: "5m", label: "5M", limit: 78 },
  { key: "15m", label: "15M", limit: 96 },
  { key: "1h", label: "1H", limit: 90 },
  { key: "1d", label: "1D", limit: 120 },
];

function fmtMoney(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  return `$${value.toFixed(digits)}`;
}

function fmtSigned(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(digits)}`;
}

function fmtPct(value: number | null | undefined, digits = 1) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function normalizeReasons(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string");
  if (typeof value === "string" && value.trim()) return [value];
  return [];
}

function pathFromPoints(points: Array<{ x: number; y: number }>) {
  if (!points.length) return "";
  return points.map((p, idx) => `${idx === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" ");
}

function movingAverage(bars: ChartBar[], period: number) {
  return bars.map((bar, idx) => {
    if (idx < period - 1) return null;
    const slice = bars.slice(idx - period + 1, idx + 1);
    return slice.reduce((sum, item) => sum + item.close, 0) / period;
  });
}

function rollingVwap(bars: ChartBar[]) {
  let cumulativePV = 0;
  let cumulativeVolume = 0;
  return bars.map((bar) => {
    const typical = (bar.high + bar.low + bar.close) / 3;
    cumulativePV += typical * Math.max(bar.volume, 1);
    cumulativeVolume += Math.max(bar.volume, 1);
    return cumulativePV / cumulativeVolume;
  });
}

function ChartCanvas({
  bars,
  levels,
}: {
  bars: ChartBar[];
  levels: Array<{ label: string; value: number; color: string }>;
}) {
  if (!bars.length) {
    return (
      <div style={{
        height: 460,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--ink-faint)",
        fontFamily: "var(--mono)",
        fontSize: 11,
      }}>
        NO CHART DATA
      </div>
    );
  }

  const width = 960;
  const height = 460;
  const priceHeight = 340;
  const volumeHeight = 70;
  const pad = { top: 18, right: 72, bottom: 34, left: 18 };
  const contentWidth = width - pad.left - pad.right;
  const candleWidth = Math.max(4, Math.min(10, contentWidth / bars.length - 2));
  const sma20 = movingAverage(bars, 20);
  const vwap = rollingVwap(bars);
  const priceValues = [
    ...bars.flatMap((bar) => [bar.high, bar.low]),
    ...levels.map((level) => level.value),
  ];
  const minPrice = Math.min(...priceValues) * 0.995;
  const maxPrice = Math.max(...priceValues) * 1.005;
  const priceRange = Math.max(maxPrice - minPrice, 0.01);
  const maxVolume = Math.max(...bars.map((bar) => bar.volume), 1);

  const xForIndex = (idx: number) => pad.left + (contentWidth * idx) / Math.max(bars.length - 1, 1);
  const yForPrice = (price: number) => pad.top + ((maxPrice - price) / priceRange) * (priceHeight - pad.top);
  const yForVolume = (volume: number) => priceHeight + 18 + volumeHeight - (volume / maxVolume) * volumeHeight;

  const smaPath = pathFromPoints(
    sma20.flatMap((value, idx) => value == null ? [] : [{ x: xForIndex(idx), y: yForPrice(value) }]),
  );
  const vwapPath = pathFromPoints(vwap.map((value, idx) => ({ x: xForIndex(idx), y: yForPrice(value) })));
  const last = bars[bars.length - 1];

  return (
    <div style={{ position: "relative", height }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "100%", display: "block" }}>
        <rect x="0" y="0" width={width} height={height} fill="transparent" />

        {Array.from({ length: 5 }).map((_, idx) => {
          const y = pad.top + ((priceHeight - pad.top) * idx) / 4;
          const price = maxPrice - (priceRange * idx) / 4;
          return (
            <g key={idx}>
              <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 6" />
              <text x={width - pad.right + 8} y={y + 4} fill="rgba(148,163,184,0.8)" fontFamily="var(--mono)" fontSize="10">
                {price.toFixed(2)}
              </text>
            </g>
          );
        })}

        {bars.map((bar, idx) => {
          const x = xForIndex(idx);
          const openY = yForPrice(bar.open);
          const closeY = yForPrice(bar.close);
          const highY = yForPrice(bar.high);
          const lowY = yForPrice(bar.low);
          const isUp = bar.close >= bar.open;
          const color = isUp ? "#18c37e" : "#ff5f6d";
          const bodyY = Math.min(openY, closeY);
          const bodyH = Math.max(Math.abs(closeY - openY), 1.2);

          return (
            <g key={`${bar.timestamp}-${idx}`}>
              <line x1={x} y1={highY} x2={x} y2={lowY} stroke={color} strokeWidth="1.2" />
              <rect
                x={x - candleWidth / 2}
                y={bodyY}
                width={candleWidth}
                height={bodyH}
                fill={isUp ? "rgba(24,195,126,0.9)" : "rgba(255,95,109,0.9)"}
                stroke={color}
                strokeWidth="1"
              />
              <rect
                x={x - candleWidth / 2}
                y={yForVolume(bar.volume)}
                width={candleWidth}
                height={volumeHeight - (yForVolume(bar.volume) - (priceHeight + 18))}
                fill={isUp ? "rgba(24,195,126,0.32)" : "rgba(255,95,109,0.32)"}
              />
            </g>
          );
        })}

        {smaPath && <path d={smaPath} fill="none" stroke="#f4c64f" strokeWidth="2.1" />}
        {vwapPath && <path d={vwapPath} fill="none" stroke="#8e7cfb" strokeWidth="1.8" strokeDasharray="5 5" />}

        {levels.map((level) => {
          const y = yForPrice(level.value);
          return (
            <line
              key={level.label}
              x1={pad.left}
              y1={y}
              x2={width - pad.right}
              y2={y}
              stroke={level.color}
              strokeWidth="1.2"
              strokeDasharray="6 5"
              opacity="0.9"
            />
          );
        })}

        <text x={pad.left} y={height - 14} fill="rgba(100,116,139,0.9)" fontFamily="var(--mono)" fontSize="10">
          {new Date(last.timestamp).toLocaleString()}
        </text>
        <text x={width - pad.right} y={height - 14} fill="rgba(100,116,139,0.9)" fontFamily="var(--mono)" fontSize="10">
          Vol {Math.round(last.volume).toLocaleString()}
        </text>
      </svg>

      {levels.map((level) => {
        const top = pad.top + ((maxPrice - level.value) / priceRange) * (priceHeight - pad.top) - 12;
        return (
          <div
            key={level.label}
            style={{
              position: "absolute",
              right: 12,
              top: Math.max(4, Math.min(top, priceHeight - 24)),
              display: "flex",
              alignItems: "center",
              gap: 8,
              pointerEvents: "none",
            }}
          >
            <span style={{
              padding: "2px 8px",
              background: level.color,
              color: "#07111f",
              fontFamily: "var(--mono)",
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.06em",
            }}>
              {level.label}
            </span>
            <span style={{
              padding: "2px 8px",
              background: "rgba(6,11,23,0.88)",
              border: `1px solid ${level.color}55`,
              color: level.color,
              fontFamily: "var(--mono)",
              fontSize: 10,
            }}>
              {level.value.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function InfoCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="panel" style={{ overflow: "hidden" }}>
      <div className="panel-head">
        <span className="panel-title">{title}</span>
        {action}
      </div>
      <div style={{ padding: 14 }}>{children}</div>
    </section>
  );
}

export default function ChartWorkstation() {
  const { positions, portfolio } = usePaperTrade();
  const { guardrailStatus, reconciliation, killSwitch } = useRisk();

  const [symbol, setSymbol] = useState("AAPL");
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [watchSnapshots, setWatchSnapshots] = useState<Record<string, WatchSnapshot>>({});
  const [signals, setSignals] = useState<Signal[]>([]);
  const [regime, setRegime] = useState<any>(null);
  const [ivRank, setIvRank] = useState<any>(null);
  const [chartBars, setChartBars] = useState<ChartBar[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

  const loadWatchlist = async () => {
    const entries = await Promise.all(
      WATCHLIST.map(async (ticker) => {
        try {
          const snap = await (api.getSnapshot(ticker) as Promise<WatchSnapshot>);
          return [ticker, { symbol: ticker, last_close: snap.last_close, change_pct: snap.change_pct }] as const;
        } catch {
          return [ticker, { symbol: ticker, last_close: null, change_pct: null }] as const;
        }
      }),
    );
    setWatchSnapshots(Object.fromEntries(entries));
  };

  const loadSignals = async () => {
    try {
      const res: any = await api.getEquitySignals(12);
      setSignals(res.signals || []);
    } catch {
      setSignals([]);
    }
  };

  useEffect(() => {
    loadWatchlist();
    loadSignals();
    (api.getRegime() as Promise<any>).then(setRegime).catch(() => setRegime(null));
  }, []);

  useEffect(() => {
    (api.getIVRank(symbol) as Promise<any>).then(setIvRank).catch(() => setIvRank(null));
  }, [symbol]);

  useEffect(() => {
    const config = TIMEFRAMES.find((item) => item.key === timeframe) || TIMEFRAMES[1];
    setChartLoading(true);
    setChartError(null);
    (api.getEquityChart(symbol, { timeframe, limit: config.limit }) as Promise<any>)
      .then((res) => setChartBars(res.bars || []))
      .catch((err: Error) => {
        setChartBars([]);
        setChartError(err.message);
      })
      .finally(() => setChartLoading(false));
  }, [symbol, timeframe]);

  const selectedSignal = useMemo(
    () => signals.find((item) => item.ticker === symbol) || signals[0] || null,
    [signals, symbol],
  );
  const selectedSnapshot = watchSnapshots[symbol];
  const latestBar = chartBars[chartBars.length - 1] || null;
  const recentBars = chartBars.slice(-20);
  const support = recentBars.length ? Math.min(...recentBars.map((bar) => bar.low)) : latestBar?.low ?? 0;
  const resistance = recentBars.length ? Math.max(...recentBars.map((bar) => bar.high)) : latestBar?.high ?? 0;
  const entry = selectedSignal?.trade_plan?.entry_price ?? latestBar?.close ?? 0;
  const stop = selectedSignal?.trade_plan?.stop_price ?? support;
  const target = selectedSignal?.trade_plan?.target_price ?? resistance;
  const levels = [
    { label: "TA ENTRY", value: entry, color: "#f4c64f" },
    { label: "TA TARGET", value: target, color: "#ff5f6d" },
    { label: "SUPPORT", value: support, color: "#5ba6ff" },
    { label: "RESISTANCE", value: resistance, color: "#f4c64f" },
  ].filter((level) => level.value > 0);

  const actionableSignals = signals.filter((item) => item.action !== "HOLD");
  const netLiq = portfolio?.account_value ?? portfolio?.starting_capital ?? 0;
  const dayPnl = guardrailStatus?.daily_pnl ?? portfolio?.total_pnl ?? 0;

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
        gap: 10,
      }} className="workstation-top-strip">
        {[
          { label: "Mode", value: killSwitch?.active ? "HALTED" : "AUTOPILOT READY", tone: killSwitch?.active ? "var(--red)" : "var(--amber)" },
          { label: "Day P&L", value: fmtSigned(dayPnl), tone: dayPnl >= 0 ? "var(--green)" : "var(--red)" },
          { label: "Portfolio", value: fmtMoney(netLiq, 2), tone: "var(--cyan)" },
          { label: "Reconciliation", value: reconciliation?.clean ? "CLEAN" : "WATCH", tone: reconciliation?.clean ? "var(--green)" : "var(--amber)" },
        ].map((item) => (
          <div key={item.label} className="panel" style={{ padding: "12px 14px" }}>
            <div className="kicker" style={{ marginBottom: 8 }}>{item.label}</div>
            <div className="data-val sm" style={{ color: item.tone }}>{item.value}</div>
          </div>
        ))}
      </div>

      <div className="workstation-grid">
        <div className="workstation-col">
          <InfoCard title="Market Watch">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {WATCHLIST.map((ticker) => {
                const snap = watchSnapshots[ticker];
                const active = ticker === symbol;
                return (
                  <button
                    key={ticker}
                    onClick={() => setSymbol(ticker)}
                    style={{
                      border: active ? "1px solid rgba(244,198,79,0.5)" : "1px solid var(--line-dim)",
                      background: active ? "rgba(244,198,79,0.08)" : "var(--bg-2)",
                      padding: "10px 12px",
                      textAlign: "left",
                      cursor: "pointer",
                      color: "var(--ink)",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 14, fontWeight: 700 }}>{ticker}</span>
                      <span style={{
                        fontFamily: "var(--mono)",
                        fontSize: 11,
                        color: (snap?.change_pct ?? 0) >= 0 ? "var(--green)" : "var(--red)",
                      }}>
                        {fmtPct(snap?.change_pct, 2)}
                      </span>
                    </div>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
                      {fmtMoney(snap?.last_close, 2)}
                    </div>
                  </button>
                );
              })}
            </div>
          </InfoCard>

          <InfoCard title="Positions">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {positions.length === 0 ? (
                <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
                  NO OPEN POSITIONS
                </div>
              ) : positions.slice(0, 6).map((position: any) => (
                <div key={`${position.symbol}-${position.entry_date || "open"}`} style={{
                  border: "1px solid var(--line-dim)",
                  padding: "10px 12px",
                  background: "rgba(255,255,255,0.01)",
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 14, color: "var(--ink)" }}>{position.symbol}</span>
                    <span style={{
                      fontFamily: "var(--mono)",
                      fontSize: 12,
                      color: (position.unrealized_pnl ?? 0) >= 0 ? "var(--green)" : "var(--red)",
                    }}>
                      {fmtSigned(position.unrealized_pnl)}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                    <span>{position.quantity ?? "—"} sh</span>
                    <span>@ {fmtMoney(position.avg_cost, 2)}</span>
                    <span>hold {position.hold_days ?? 0}d</span>
                  </div>
                </div>
              ))}
            </div>
          </InfoCard>
        </div>

        <div className="workstation-center">
          <section className="panel" style={{ overflow: "hidden" }}>
            <div className="panel-head" style={{ gap: 12, flexWrap: "wrap" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
                <span style={{ fontFamily: "var(--mono)", fontSize: 28, fontWeight: 700, color: "var(--cyan)" }}>{symbol}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-dim)" }}>
                  {selectedSnapshot?.last_close != null ? fmtMoney(selectedSnapshot.last_close, 2) : "—"} · {fmtPct(selectedSnapshot?.change_pct, 2)}
                </span>
              </div>
              <div style={{ display: "flex", gap: 8, marginLeft: "auto", flexWrap: "wrap" }}>
                {TIMEFRAMES.map((item) => (
                  <button
                    key={item.key}
                    className={`btn-t ${timeframe === item.key ? "active" : ""}`}
                    onClick={() => setTimeframe(item.key)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ padding: 14 }}>
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
                gap: 10,
                marginBottom: 12,
              }} className="workstation-metrics-grid">
                {[
                  { label: "Signal", value: selectedSignal?.action || "HOLD", tone: selectedSignal?.action === "BUY" ? "var(--green)" : selectedSignal?.action === "SELL" ? "var(--red)" : "var(--ink-dim)" },
                  { label: "Confidence", value: selectedSignal ? `${Math.round(selectedSignal.confidence * 100)}%` : "—", tone: "var(--amber)" },
                  { label: "IV Rank", value: ivRank?.iv_rank != null ? `${Math.round(ivRank.iv_rank)}` : "—", tone: "var(--cyan)" },
                  { label: "RSI", value: selectedSignal?.indicators?.rsi != null ? selectedSignal.indicators.rsi.toFixed(1) : "—", tone: "var(--ink)" },
                  { label: "Volume x", value: selectedSignal?.indicators?.volume_ratio != null ? selectedSignal.indicators.volume_ratio.toFixed(2) : "—", tone: "var(--ink)" },
                ].map((item) => (
                  <div key={item.label} style={{ background: "var(--bg-3)", padding: "10px 12px", border: "1px solid var(--line-dim)" }}>
                    <div className="kicker" style={{ marginBottom: 8 }}>{item.label}</div>
                    <div className="data-val sm" style={{ color: item.tone }}>{item.value}</div>
                  </div>
                ))}
              </div>

              <div style={{ border: "1px solid var(--line-dim)", background: "linear-gradient(180deg, rgba(6,11,23,0.45), rgba(6,11,23,0.9))" }}>
                {chartLoading ? (
                  <div style={{
                    height: 460,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "var(--mono)",
                    fontSize: 11,
                    color: "var(--ink-faint)",
                  }}>
                    LOADING CHART…
                  </div>
                ) : (
                  <ChartCanvas bars={chartBars} levels={levels} />
                )}
              </div>
              {chartError && (
                <div style={{ marginTop: 10, fontFamily: "var(--mono)", fontSize: 10, color: "var(--red)" }}>
                  {chartError}
                </div>
              )}
            </div>
          </section>

          <div className="workstation-bottom-grid">
            <InfoCard title="TA Trade Plan">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 }} className="workstation-plan-grid">
                {[
                  { label: "Entry", value: fmtMoney(entry, 2), tone: "var(--cyan)" },
                  { label: "Stop", value: fmtMoney(stop, 2), tone: "var(--red)" },
                  { label: "Target", value: fmtMoney(target, 2), tone: "var(--green)" },
                  { label: "R:R", value: selectedSignal?.trade_plan?.risk_reward != null ? `${selectedSignal.trade_plan.risk_reward.toFixed(2)}x` : "—", tone: "var(--amber)" },
                ].map((item) => (
                  <div key={item.label} style={{ border: "1px solid var(--line-dim)", padding: "12px 12px", background: "var(--bg-3)" }}>
                    <div className="kicker" style={{ marginBottom: 8 }}>{item.label}</div>
                    <div className="data-val sm" style={{ color: item.tone }}>{item.value}</div>
                  </div>
                ))}
              </div>
            </InfoCard>

            <InfoCard title="Context Stack">
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <span className="mode-badge balanced">{regime?.regime ? regime.regime.replace(/_/g, " ") : "unknown"}</span>
                  <span className="mode-badge conservative">VIX {regime?.vix != null ? regime.vix.toFixed(1) : "—"}</span>
                  <span className="mode-badge aggressive">IVR {ivRank?.iv_rank != null ? Math.round(ivRank.iv_rank) : "—"}</span>
                </div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.7 }}>
                  {normalizeReasons(selectedSignal?.reasons).length
                    ? normalizeReasons(selectedSignal?.reasons).join(" · ")
                    : "Signal stack will describe momentum, trend, volume, and volatility context when available."}
                </div>
              </div>
            </InfoCard>
          </div>
        </div>

        <div className="workstation-col workstation-right">
          <InfoCard
            title="Research & Execution"
            action={(
              <button className="btn-t" onClick={() => loadSignals()}>
                Refresh
              </button>
            )}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{
                border: "1px solid var(--line-dim)",
                padding: "10px 12px",
                background: "var(--bg-3)",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--green)" }}>
                    Macro {regime?.equity_allowed ? "BULL" : "PAUSED"}
                  </span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
                    VIX {regime?.vix != null ? regime.vix.toFixed(1) : "—"}
                  </span>
                </div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.7 }}>
                  {regime?.description || "Regime engine warming up. Once available, this panel will summarize volatility, trend, and execution allowance."}
                </div>
              </div>

              {(actionableSignals.length ? actionableSignals : signals).slice(0, 4).map((item) => (
                <button
                  key={item.id}
                  onClick={() => setSymbol(item.ticker)}
                  style={{
                    textAlign: "left",
                    background: item.ticker === symbol ? "rgba(244,198,79,0.08)" : "var(--bg-2)",
                    border: item.ticker === symbol ? "1px solid rgba(244,198,79,0.4)" : "1px solid var(--line-dim)",
                    padding: "12px 14px",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 16, color: "var(--ink)", fontWeight: 700 }}>{item.ticker}</span>
                    <span className={`mode-badge ${item.action === "BUY" ? "conservative" : item.action === "SELL" ? "scalper" : "balanced"}`}>
                      {item.action}
                    </span>
                    <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 12, color: "var(--amber)" }}>
                      {Math.round(item.confidence * 100)}%
                    </span>
                  </div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.7 }}>
                    {normalizeReasons(item.reasons).slice(0, 3).join(" · ") || "Signal narrative not available yet."}
                  </div>
                </button>
              ))}
            </div>
          </InfoCard>

          <InfoCard title="Operator Safety">
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                { label: "Kill Switch", value: killSwitch?.active ? "ACTIVE" : "ARMED", tone: killSwitch?.active ? "var(--red)" : "var(--green)" },
                { label: "Daily Loss", value: fmtPct(guardrailStatus?.daily_loss_pct, 2), tone: "var(--red)" },
                { label: "Open Positions", value: String(portfolio?.open_positions ?? positions.length ?? 0), tone: "var(--ink)" },
                { label: "Win Rate", value: portfolio?.win_rate != null ? `${Math.round(portfolio.win_rate * 100)}%` : "—", tone: "var(--cyan)" },
              ].map((row) => (
                <div key={row.label} style={{ display: "flex", justifyContent: "space-between", gap: 16, borderBottom: "1px solid var(--line-dim)", paddingBottom: 8 }}>
                  <span className="kicker">{row.label}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: row.tone }}>{row.value}</span>
                </div>
              ))}
            </div>
          </InfoCard>
        </div>
      </div>
    </div>
  );
}
