/**
 * Command Overview — Trade Desk landing. Read-only queues from existing APIs.
 * Actionable, not a crowded dashboard. No order submission.
 */

import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TradeDeskTab } from "./TradeDeskTabs";

interface QueueCardProps {
  title: string;
  count: number | string;
  items: string[];
  empty: string;
  tone?: "ok" | "warn" | "crit" | "muted";
  onOpen?: () => void;
  actionLabel?: string;
}

function QueueCard({ title, count, items, empty, tone = "muted", onOpen, actionLabel }: QueueCardProps) {
  const border =
    tone === "crit" ? "rgba(239,68,68,0.35)" :
    tone === "warn" ? "rgba(245,158,11,0.35)" :
    tone === "ok" ? "rgba(34,197,94,0.3)" :
    "var(--line-dim)";

  return (
    <div
      style={{
        background: "var(--bg-2)",
        border: `1px solid ${border}`,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 160,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--ink-dim)",
          }}
        >
          {title}
        </span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 18, fontWeight: 700, color: "var(--ink)" }}>
          {count}
        </span>
      </div>
      {items.length === 0 ? (
        <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)", flex: 1 }}>
          {empty}
        </p>
      ) : (
        <ul
          style={{
            margin: 0,
            padding: 0,
            listStyle: "none",
            display: "flex",
            flexDirection: "column",
            gap: 6,
            flex: 1,
          }}
        >
          {items.slice(0, 5).map((line, i) => (
            <li
              key={i}
              style={{
                fontFamily: "var(--mono)",
                fontSize: 11,
                color: "var(--ink)",
                borderBottom: "1px solid var(--line-dim)",
                paddingBottom: 4,
              }}
            >
              {line}
            </li>
          ))}
        </ul>
      )}
      {onOpen && (
        <button
          type="button"
          className="btn-t"
          onClick={onOpen}
          style={{ alignSelf: "flex-start", fontSize: 10, letterSpacing: "0.08em" }}
        >
          {actionLabel || "Open"}
        </button>
      )}
    </div>
  );
}

interface ScoreCardProps {
  title: string;
  score: number | null;
  scoreSuffix?: string;
  scoreLabel: string;
  stats: { label: string; value: string; tone?: string }[];
  items: string[];
  empty: string;
  onOpen?: () => void;
  actionLabel?: string;
}

function ScoreCard({
  title, score, scoreSuffix = "%", scoreLabel, stats, items, empty, onOpen, actionLabel,
}: ScoreCardProps) {
  const scoreColor =
    score == null ? "var(--ink-faint)" :
    score >= 70 ? "var(--green)" :
    score >= 40 ? "var(--amber)" : "var(--red)";

  return (
    <div
      style={{
        background: "var(--bg-2)",
        border: "1px solid var(--line-dim)",
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 200,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span
          style={{
            fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.1em",
            textTransform: "uppercase", color: "var(--ink-dim)",
          }}
        >
          {title}
        </span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)" }}>
          {scoreLabel}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 28, fontWeight: 700, color: scoreColor }}>
          {score == null ? "—" : score.toFixed(0)}
        </span>
        {score != null && (
          <span style={{ fontFamily: "var(--mono)", fontSize: 14, color: scoreColor }}>{scoreSuffix}</span>
        )}
      </div>

      {stats.length > 0 && (
        <div style={{ display: "flex", gap: 0, border: "1px solid var(--line-dim)" }}>
          {stats.map((s, i) => (
            <div
              key={s.label}
              style={{
                flex: 1, padding: "6px 8px",
                borderRight: i < stats.length - 1 ? "1px solid var(--line-dim)" : undefined,
              }}
            >
              <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)", marginBottom: 2 }}>
                {s.label}
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 600, color: s.tone || "var(--ink)" }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {items.length === 0 ? (
        <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)", flex: 1 }}>
          {empty}
        </p>
      ) : (
        <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
          {items.slice(0, 5).map((line, i) => (
            <li
              key={i}
              style={{
                fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink)",
                borderBottom: "1px solid var(--line-dim)", paddingBottom: 4,
              }}
            >
              {line}
            </li>
          ))}
        </ul>
      )}

      {onOpen && (
        <button
          type="button"
          className="btn-t"
          onClick={onOpen}
          style={{ alignSelf: "flex-start", fontSize: 10, letterSpacing: "0.08em" }}
        >
          {actionLabel || "Open"}
        </button>
      )}
    </div>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 12,
        padding: "6px 0",
        borderBottom: "1px solid var(--line-dim)",
        fontFamily: "var(--mono)",
        fontSize: 11,
      }}
    >
      <span style={{ color: "var(--ink-faint)" }}>{label}</span>
      <span style={{ color: "var(--ink)", textAlign: "right" }}>{value}</span>
    </div>
  );
}

export default function CommandOverview({
  onNavigateTab,
}: {
  onNavigateTab: (tab: TradeDeskTab) => void;
}) {
  const [pending, setPending] = useState<any[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [execLog, setExecLog] = useState<any[]>([]);
  const [positions, setPositions] = useState<any[]>([]);
  const [regime, setRegime] = useState("—");
  const [ks, setKs] = useState("—");
  const [broker, setBroker] = useState("—");
  const [riskBudget, setRiskBudget] = useState("—");
  const [equitySignals, setEquitySignals] = useState<any[]>([]);
  const [optionsSignals, setOptionsSignals] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [pend, log, pos, reg, kill, br, risk, eqSig, optSig] = await Promise.all([
          api.getPendingApprovals().catch(() => ({ pending: [], count: 0 })),
          api.getExecutionLog().catch(() => ({ events: [] })),
          api.getPositions().catch(() => ({ positions: [] })),
          api.getRegime().catch(() => ({})),
          api.getTradeDeskKillSwitch().catch(() =>
            api.getKillSwitchStatus().catch(() => ({})),
          ),
          fetch("/api/market/broker").then((r) => r.json()).catch(() => ({})),
          api.getPortfolioState().catch(() => ({})),
          api.getEquitySignals(20).catch(() => ({ signals: [] })),
          api.getOptionsSignals(20).catch(() => ({ signals: [] })),
        ]);
        if (!alive) return;
        const p = (pend as any).pending || [];
        setPending(p);
        setPendingCount((pend as any).count ?? p.length);
        setExecLog((log as any).events || (log as any).log || []);
        setPositions((pos as any).positions || (Array.isArray(pos) ? pos : []));
        const r = (reg as any).regime || (reg as any).regime_type;
        setRegime(typeof r === "string" ? r.replace(/_/g, " ") : "Unavailable");
        const engaged = !!(kill as any).engaged || !!(kill as any).is_engaged;
        setKs(engaged ? "ENGAGED" : "Clear");
        setBroker(
          `${((br as any).broker || "—").toUpperCase()} · ${(br as any).status || "unknown"}` +
          ((br as any).paper_mode === false ? " · LIVE" : (br as any).paper_mode ? " · PAPER" : ""),
        );
        const s = (risk as any).state || risk;
        if (typeof s.daily_loss_pct === "number" && typeof s.max_daily_loss_pct === "number") {
          setRiskBudget(
            `${(Math.max(0, s.max_daily_loss_pct - s.daily_loss_pct) * 100).toFixed(1)}% daily remaining`,
          );
        } else {
          setRiskBudget("Unavailable");
        }
        setEquitySignals((eqSig as any).signals || []);
        setOptionsSignals((optSig as any).signals || []);
        setError(null);
      } catch (e: any) {
        if (alive) setError(e?.message || "Failed to load overview");
      }
    };
    load();
    const t = setInterval(load, 20000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const rejected = execLog.filter((e) => {
    const st = (e.status || e.result?.status || e.kind || "").toString().toLowerCase();
    return st.includes("reject") || st.includes("block") || st.includes("fail");
  });

  const opportunityLines = pending.slice(0, 5).map((p) => {
    const t = p.ticker || p.signal?.ticker || "?";
    const a = p.action || p.signal?.action || "";
    return `${t} ${a}`.trim();
  });

  const reviewLines = pending.map((p) => {
    const t = p.ticker || "?";
    const src = p.source || p.signal?.source || "pending";
    return `${t} · ${src}`;
  });

  const riskLines: string[] = [];
  if (ks === "ENGAGED") riskLines.push("Kill switch engaged — trading halted");
  if (riskBudget !== "—" && riskBudget !== "Unavailable") riskLines.push(`Budget: ${riskBudget}`);

  const exceptionLines = rejected.slice(0, 5).map((e) => {
    const t = e.ticker || e.signal_id || e.kind || "event";
    const st = e.status || e.result?.status || e.kind || "exception";
    return `${t} · ${st}`;
  });

  // Equities score card — actionable (non-HOLD) signals from the background
  // scanner, same feed EquitySignals.tsx reads (/api/equity/signals).
  const actionableEquity = equitySignals.filter((s) => s.action === "BUY" || s.action === "SELL");
  const equityAvgConfidence =
    actionableEquity.length > 0
      ? (actionableEquity.reduce((sum, s) => sum + (s.confidence || 0), 0) / actionableEquity.length) * 100
      : null;
  const equityBuyCount = actionableEquity.filter((s) => s.action === "BUY").length;
  const equitySellCount = actionableEquity.filter((s) => s.action === "SELL").length;
  const equityLines = actionableEquity.slice(0, 5).map((s) => {
    const conf = typeof s.confidence === "number" ? `${(s.confidence * 100).toFixed(0)}%` : "—";
    return `${s.ticker} ${s.action} · ${conf}`;
  });

  // Options score card — recent spread signals (/api/options/signals),
  // confidence there is POP when available (see main.py signal builder).
  const optionsAvgConfidence =
    optionsSignals.length > 0
      ? (optionsSignals.reduce((sum, s) => sum + (s.confidence || 0), 0) / optionsSignals.length) * 100
      : null;
  const optionsCreditCount = optionsSignals.filter((s) => (s.spread?.net_credit ?? 0) > 0).length;
  const optionsDebitCount = optionsSignals.filter((s) => (s.spread?.net_credit ?? 0) < 0).length;
  const optionsLines = optionsSignals.slice(0, 5).map((s) => {
    const strat = s.strategy ? s.strategy.replace(/_/g, " ") : s.action || "—";
    const conf = typeof s.confidence === "number" ? `${(s.confidence * 100).toFixed(0)}%` : "—";
    return `${s.ticker} ${strat} · ${conf}`;
  });

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16, maxWidth: 1100 }}>
      <div>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--mono)",
            fontSize: 15,
            letterSpacing: "0.08em",
            color: "var(--ink)",
          }}
        >
          COMMAND OVERVIEW
        </h2>
        <p style={{ margin: "6px 0 0", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
          Decision queues from live desk state. Read-only — execution stays on existing Trade Desk paths.
        </p>
      </div>

      {error && (
        <div
          style={{
            border: "1px solid rgba(239,68,68,0.35)",
            padding: "10px 12px",
            fontFamily: "var(--mono)",
            fontSize: 11,
            color: "var(--red)",
          }}
        >
          {error}
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
          gap: 0,
          border: "1px solid var(--line-dim)",
          background: "var(--bg-2)",
          padding: "4px 12px",
        }}
      >
        <StatusRow label="Regime" value={regime} />
        <StatusRow label="Kill switch" value={ks} />
        <StatusRow label="Broker" value={broker} />
        <StatusRow label="Risk budget" value={riskBudget} />
        <StatusRow label="Open positions" value={String(positions.length)} />
        <StatusRow label="Copilot queue" value={String(pendingCount)} />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
          gap: 12,
        }}
      >
        <QueueCard
          title="Opportunities"
          count={pendingCount}
          items={opportunityLines}
          empty="No queued opportunities. Scans and signals appear here when Copilot has work."
          tone={pendingCount > 0 ? "ok" : "muted"}
          onOpen={() => onNavigateTab("copilot")}
          actionLabel="Open Copilot"
        />
        <QueueCard
          title="Reviews required"
          count={pendingCount}
          items={reviewLines}
          empty="No approvals waiting."
          tone={pendingCount > 0 ? "warn" : "muted"}
          onOpen={() => onNavigateTab("copilot")}
          actionLabel="Review queue"
        />
        <QueueCard
          title="Risk actions"
          count={riskLines.length || (ks === "ENGAGED" ? 1 : 0)}
          items={riskLines.length ? riskLines : ["No mandatory risk actions from current status."]}
          empty="No risk actions."
          tone={ks === "ENGAGED" ? "crit" : "muted"}
          onOpen={() => onNavigateTab("positions")}
          actionLabel="Positions"
        />
        <QueueCard
          title="Execution exceptions"
          count={rejected.length}
          items={exceptionLines}
          empty="No recent rejects/blocks in the execution log."
          tone={rejected.length > 0 ? "crit" : "muted"}
          onOpen={() => onNavigateTab("execution")}
          actionLabel="Execution log"
        />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
          gap: 12,
        }}
      >
        <ScoreCard
          title="Equities"
          score={equityAvgConfidence}
          scoreLabel="avg confidence"
          stats={[
            { label: "BUY", value: String(equityBuyCount), tone: "var(--green)" },
            { label: "SELL", value: String(equitySellCount), tone: "var(--red)" },
            { label: "SIGNALS", value: String(actionableEquity.length) },
          ]}
          items={equityLines}
          empty="No actionable equity signals right now."
          onOpen={() => onNavigateTab("equities")}
          actionLabel="Desk signals"
        />
        <ScoreCard
          title="Options"
          score={optionsAvgConfidence}
          scoreLabel="avg confidence"
          stats={[
            { label: "CREDIT", value: String(optionsCreditCount), tone: "var(--green)" },
            { label: "DEBIT", value: String(optionsDebitCount), tone: "var(--amber)" },
            { label: "SIGNALS", value: String(optionsSignals.length) },
          ]}
          items={optionsLines}
          empty="No recent options spread signals."
          onOpen={() => onNavigateTab("options")}
          actionLabel="Spread Scanner"
        />
      </div>
    </div>
  );
}
