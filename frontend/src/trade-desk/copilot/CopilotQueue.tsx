/**
 * Copilot Queue v2 — pending approvals + recent audit.
 * Approve/reject use existing trade-desk APIs → _execute_signal on approve.
 * No TradeIntent modify / re-eval in this thin phase.
 */

import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import SignalAttribution from "../../components/SignalAttribution";
import type { SignalAttributionData } from "../../types/signal";
import MetricHint from "../../components/MetricHint";
import { Badge } from "../../components/ui";
import {
  lifecycleColor,
  lifecycleFromExecution,
  lifecycleLabel,
} from "../executionStatus";

export default function CopilotQueue() {
  const [pending, setPending] = useState<any[]>([]);
  const [log, setLog] = useState<any[]>([]);
  const [mode, setMode] = useState<string>("—");
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    Promise.all([
      (api.getPendingApprovals() as any).catch(() => ({ pending: [], mode: "—" })),
      (api.getExecutionLog() as any).catch(() => ({ log: [] })),
      (api.getExecutionMode() as any).catch(() => ({ mode: "—" })),
    ])
      .then(([p, l, m]) => {
        setPending((p as any).pending || []);
        setLog((l as any).log || []);
        setMode(
          String((p as any).mode || (m as any).mode || "—").toUpperCase(),
        );
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  const act = async (id: string, action: "approve" | "reject") => {
    setActing(id);
    setError(null);
    try {
      if (action === "approve") await (api.approveSignal(id) as any);
      else await (api.rejectSignal(id) as any);
      refresh();
    } catch (e: any) {
      setError(e?.message || `${action} failed`);
    } finally {
      setActing(null);
    }
  };

  const recent = log.slice(0, 40);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div
        style={{
          padding: "10px 16px",
          borderBottom: "1px solid var(--line-dim)",
          background: "var(--bg-3)",
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <span className="panel-title">COPILOT QUEUE</span>
        <Badge kind="tag" tone="var(--amber)">{`MODE ${mode}`}</Badge>
        {pending.length > 0 && (
          <Badge kind="tag" tone="var(--orange)">{`${pending.length} PENDING`}</Badge>
        )}
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)", flex: 1 }}>
          Approve routes through existing OMS. Size edits require a new signal (no modify → re-eval yet).
        </span>
        <button type="button" className="btn-t" style={{ fontSize: 10 }} onClick={refresh}>
          Refresh
        </button>
      </div>

      {error && (
        <div
          style={{
            padding: "8px 16px",
            fontFamily: "var(--mono)",
            fontSize: 11,
            color: "var(--red)",
            borderBottom: "1px solid var(--line-dim)",
          }}
        >
          {error}
        </div>
      )}

      {loading ? (
        <div
          style={{
            padding: 40,
            textAlign: "center",
            fontFamily: "var(--mono)",
            color: "var(--ink-faint)",
            fontSize: 11,
          }}
        >
          Loading…
        </div>
      ) : pending.length === 0 ? (
        <div
          style={{
            padding: 40,
            textAlign: "center",
            fontFamily: "var(--mono)",
            color: "var(--ink-faint)",
            fontSize: 11,
          }}
        >
          No pending approvals — queue is clear
          <div style={{ marginTop: 8, fontSize: 10 }}>
            Switch to Copilot mode to route new signals here for approval.
          </div>
        </div>
      ) : (
        <div style={{ overflowY: "auto", flex: "0 1 auto", maxHeight: "55%" }}>
          {pending.map((s: any) => (
            <div
              key={s.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                padding: "12px 16px",
                borderBottom: "1px solid var(--line-dim)",
                background: "var(--bg-2)",
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>
                    {s.ticker}
                  </span>
                  <Badge kind="tag" tone="var(--ink-dim)">{s.asset_type?.toUpperCase() || "EQUITY"}</Badge>
                  <SignalAttribution
                    data={
                      {
                        direction: s.action || s.strategy?.toUpperCase() || "BUY",
                        source: s.source ?? "unknown",
                        timeframe: null,
                        confidence: typeof s.confidence === "number" ? s.confidence : null,
                        updatedAt: s.queued_at ?? null,
                        authority: "advisory",
                      } as SignalAttributionData
                    }
                    size="sm"
                  />
                  <Badge kind="tag" tone="var(--amber)">{s.regime?.toUpperCase() || "—"}</Badge>
                </div>
                {s.spread && (
                  <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                    {s.spread.option_type?.toUpperCase()} spread{" "}
                    {s.spread.short_strike}/{s.spread.long_strike} exp {s.spread.expiration} · credit:{" "}
                    <span style={{ color: "var(--green)" }}>${s.spread.net_credit?.toFixed(2)}</span> · max loss:{" "}
                    <span style={{ color: "var(--red)" }}>${s.spread.max_loss?.toFixed(2)}</span>
                  </div>
                )}
                {s.intelligence && (
                  <div
                    style={{
                      display: "flex",
                      gap: 14,
                      marginTop: 6,
                      flexWrap: "wrap",
                      fontFamily: "var(--mono)",
                      fontSize: 10,
                    }}
                  >
                    <span style={{ color: "var(--ink-dim)" }}>
                      <MetricHint id="POP" />{" "}
                      <b style={{ color: (s.intelligence.pop ?? 0) >= 0.7 ? "var(--green)" : "var(--amber)" }}>
                        {((s.intelligence.pop ?? 0) * 100).toFixed(0)}%
                      </b>
                    </span>
                    <span style={{ color: "var(--ink-dim)" }}>
                      <MetricHint id="EV" />{" "}
                      <b style={{ color: (s.intelligence.expected_value ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                        ${(s.intelligence.expected_value ?? 0).toFixed(0)}
                      </b>
                    </span>
                    <span style={{ color: "var(--ink-dim)" }}>
                      <MetricHint id="Kelly" />{" "}
                      <b style={{ color: "var(--cyan)" }}>
                        {((s.intelligence.kelly_fraction ?? 0) * 100).toFixed(1)}%
                      </b>
                    </span>
                  </div>
                )}
                {!s.spread && (
                  <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                    Equity · queued {s.queued_at ? new Date(s.queued_at).toLocaleString() : "—"}
                  </div>
                )}
              </div>
              <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                <button
                  type="button"
                  className="btn-t"
                  disabled={acting === s.id}
                  onClick={() => act(s.id, "approve")}
                  style={{ color: "var(--green)", borderColor: "rgba(34,197,94,0.5)", fontSize: 11 }}
                >
                  APPROVE
                </button>
                <button
                  type="button"
                  className="btn-t danger"
                  disabled={acting === s.id}
                  onClick={() => act(s.id, "reject")}
                  style={{ fontSize: 11 }}
                >
                  REJECT
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div
        style={{
          padding: "10px 16px",
          borderBottom: "1px solid var(--line-dim)",
          borderTop: "1px solid var(--line-dim)",
          background: "var(--bg-3)",
        }}
      >
        <span className="panel-title">RECENT DECISIONS</span>
      </div>
      <div style={{ flex: 1, overflowY: "auto" }}>
        {recent.length === 0 ? (
          <div
            style={{
              padding: 32,
              textAlign: "center",
              fontFamily: "var(--mono)",
              color: "var(--ink-faint)",
              fontSize: 11,
            }}
          >
            NO AUDIT HISTORY
          </div>
        ) : (
          <table className="t-table">
            <thead>
              <tr>
                {["Time", "Ticker", "Type", "Action", "By", "Status", "Reason"].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {recent.map((e: any, i: number) => {
                const life = lifecycleFromExecution(e);
                const ts = e.executed_at || e.rejected_at;
                return (
                  <tr key={e.signal_id || i}>
                    <td className="mono" style={{ fontSize: 10, color: "var(--ink-dim)" }}>
                      {ts ? new Date(ts).toLocaleString() : "—"}
                    </td>
                    <td className="mono" style={{ color: "var(--ink)" }}>
                      {e.ticker || "—"}
                    </td>
                    <td>
                      <Badge kind="tag" tone="var(--ink-dim)">{e.asset_type?.toUpperCase() || "EQ"}</Badge>
                    </td>
                    <td className="mono" style={{ fontSize: 10 }}>
                      {e.action || e.strategy || "—"}
                    </td>
                    <td className="mono" style={{ fontSize: 10, color: "var(--amber)" }}>
                      {e.executed_by || e.approved_by || e.rejected_by || "—"}
                    </td>
                    <td>
                      <Badge kind="tag" tone={lifecycleColor(life)}>{lifecycleLabel(life)}</Badge>
                    </td>
                    <td className="mono" style={{ fontSize: 10, color: "var(--ink-dim)", maxWidth: 220 }}>
                      {e.reason || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
