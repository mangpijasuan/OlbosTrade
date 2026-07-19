/**
 * Equity order composer — evaluate via backend, submit via existing /api/trade-desk/signal.
 * Frontend never invents eligibility; blocked evaluations disable submit.
 */

import React, { useEffect, useState } from "react";
import { api, apiAuthHeaders } from "../../api/client";
import type { EligibilitySnapshot } from "./EquityIntelligenceRail";

export default function EquityOrderComposer({
  symbol,
  onEvaluated,
}: {
  symbol: string;
  onEvaluated: (e: EligibilitySnapshot | null) => void;
}) {
  const [action, setAction] = useState<"BUY" | "SELL">("BUY");
  const [shares, setShares] = useState(10);
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [orderType, setOrderType] = useState<"market" | "limit">("limit");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [evalResult, setEvalResult] = useState<EligibilitySnapshot | null>(null);

  useEffect(() => {
    let alive = true;
    api.getSnapshot(symbol)
      .then((s: any) => {
        if (!alive || typeof s.last_close !== "number") return;
        const px = s.last_close;
        setEntry(px.toFixed(2));
        setStop((px * 0.98).toFixed(2));
        setTarget((px * 1.04).toFixed(2));
      })
      .catch(() => {});
    setEvalResult(null);
    onEvaluated(null);
    setMsg(null);
    return () => { alive = false; };
  }, [symbol]); // eslint-disable-line react-hooks/exhaustive-deps

  const entryN = parseFloat(entry);
  const stopN = parseFloat(stop);
  const targetN = parseFloat(target);
  const riskPerShare =
    Number.isFinite(entryN) && Number.isFinite(stopN) ? Math.abs(entryN - stopN) : null;
  const riskDollars = riskPerShare != null ? riskPerShare * shares : null;
  const reward =
    Number.isFinite(entryN) && Number.isFinite(targetN) ? Math.abs(targetN - entryN) : null;
  const rr = riskPerShare && reward ? reward / riskPerShare : null;

  const evaluate = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/api/trade-desk/evaluate-equity", {
        method: "POST",
        headers: apiAuthHeaders(),
        body: JSON.stringify({
          ticker: symbol,
          action,
          shares,
          entry_price: entryN,
          stop_price: stopN,
          target_price: Number.isFinite(targetN) ? targetN : null,
          order_type: orderType,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || `Evaluate failed (${res.status})`);
      const snap: EligibilitySnapshot = {
        final_status: body.final_status,
        block_reasons: body.block_reasons || [],
        warnings: body.warnings || [],
        environment: body.environment,
        execution_mode: body.execution_mode,
        evaluated_at: body.evaluated_at,
      };
      setEvalResult(snap);
      onEvaluated(snap);
      setMsg(`Evaluated: ${snap.final_status.replace(/_/g, " ")}`);
    } catch (e: any) {
      setMsg(e?.message || "Evaluate failed");
      setEvalResult(null);
      onEvaluated(null);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!evalResult || evalResult.final_status === "BLOCKED") {
      setMsg("Evaluate first. Blocked intents cannot be submitted.");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/api/trade-desk/signal", {
        method: "POST",
        headers: apiAuthHeaders(),
        body: JSON.stringify({
          ticker: symbol,
          action,
          shares,
          asset_type: "equity",
          entry_price: entryN,
          stop_price: stopN,
          target_price: Number.isFinite(targetN) ? targetN : entryN,
          kelly_fraction: 0.1,
          confidence: 0.5,
          source: "equity_desk_composer",
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || `Submit failed (${res.status})`);
      setMsg(body.message || `Queued: ${body.status}`);
    } catch (e: any) {
      setMsg(e?.message || "Submit failed");
    } finally {
      setBusy(false);
    }
  };

  const blocked = evalResult?.final_status === "BLOCKED";
  const canSubmit = !!evalResult && !blocked;

  const field = (label: string, children: React.ReactNode) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontFamily: "var(--mono)", fontSize: 10 }}>
      <span style={{ color: "var(--ink-faint)", letterSpacing: "0.08em" }}>{label}</span>
      {children}
    </label>
  );

  const inputStyle: React.CSSProperties = {
    fontFamily: "var(--mono)",
    fontSize: 12,
    padding: "6px 8px",
    background: "var(--bg-3)",
    color: "var(--ink)",
    border: "1px solid var(--line)",
  };

  return (
    <div
      style={{
        borderTop: "1px solid var(--line-dim)",
        background: "var(--bg-2)",
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        flexShrink: 0,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.1em", color: "var(--ink-dim)" }}>
          ORDER COMPOSER · {symbol}
        </span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          Evaluate is authoritative · submit uses existing desk queue
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))", gap: 8 }}>
        {field(
          "SIDE",
          <select value={action} onChange={(e) => setAction(e.target.value as "BUY" | "SELL")} style={inputStyle}>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>,
        )}
        {field(
          "TYPE",
          <select value={orderType} onChange={(e) => setOrderType(e.target.value as "market" | "limit")} style={inputStyle}>
            <option value="limit">LIMIT</option>
            <option value="market">MARKET</option>
          </select>,
        )}
        {field(
          "SHARES",
          <input type="number" min={1} value={shares} onChange={(e) => setShares(Math.max(1, Number(e.target.value) || 1))} style={inputStyle} />,
        )}
        {field("ENTRY", <input value={entry} onChange={(e) => setEntry(e.target.value)} style={inputStyle} />)}
        {field("STOP", <input value={stop} onChange={(e) => setStop(e.target.value)} style={inputStyle} />)}
        {field("TARGET", <input value={target} onChange={(e) => setTarget(e.target.value)} style={inputStyle} />)}
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
        <span>
          EST VALUE{" "}
          <b style={{ color: "var(--ink)" }}>
            {Number.isFinite(entryN) ? `$${(entryN * shares).toFixed(0)}` : "—"}
          </b>
        </span>
        <span>
          MAX LOSS{" "}
          <b style={{ color: "var(--amber)" }}>
            {riskDollars != null ? `$${riskDollars.toFixed(0)}` : "—"}
          </b>
        </span>
        <span>
          R:R <b style={{ color: "var(--cyan)" }}>{rr != null ? `${rr.toFixed(2)}x` : "—"}</b>
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button type="button" className="btn-t" disabled={busy || !Number.isFinite(entryN) || !Number.isFinite(stopN)} onClick={evaluate}>
          {busy ? "…" : "EVALUATE"}
        </button>
        <button
          type="button"
          className="btn-t"
          disabled={busy || !canSubmit}
          onClick={submit}
          style={canSubmit ? { borderColor: "var(--cyan)", color: "var(--cyan)" } : undefined}
          title={blocked ? "Blocked by backend evaluation" : "Queue via /api/trade-desk/signal"}
        >
          SUBMIT TO DESK
        </button>
        {msg && (
          <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: blocked ? "var(--red)" : "var(--ink-dim)" }}>
            {msg}
          </span>
        )}
      </div>
    </div>
  );
}
