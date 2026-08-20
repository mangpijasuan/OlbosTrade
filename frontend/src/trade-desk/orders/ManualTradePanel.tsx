/**
 * Manual trade panel — places a real equity order immediately via
 * /api/trade-desk/manual-trade, subject to the same fail-closed pipeline
 * (kill switch, market hours, guardrails, portfolio/duplicate/account-mode/
 * margin gates) as autopilot/copilot approvals. Distinct from
 * EquityOrderComposer, whose "submit" queues an order for later approval
 * via /api/trade-desk/signal — this panel executes now.
 */

import React, { useState } from "react";
import { apiAuthHeaders } from "../../api/client";
import HoldToConfirmButton from "../../components/HoldToConfirmButton";
import {
  lifecycleFromExecution,
  lifecycleLabel,
  lifecycleColor,
} from "../executionStatus";

// Backend has no per-order size cap for market orders specifically: a market
// order's entry_price is null, so execution_portfolio_gate.py's dollar-risk
// check (entry_price * shares) evaluates to $0 regardless of share count —
// that gate cannot catch an oversized market order. This client-side cap is
// the only thing standing between a typo and an enormous order for that
// case, so don't remove it as "dead-looking validation."
const MAX_SHARES = 10_000;

type Action = "BUY" | "SELL";
type OrderType = "market" | "limit";

interface ManualTradeResult {
  result?: string;
  reason?: string;
  order_id?: string;
  order_status?: string;
  entry_price?: number;
  ticker?: string;
}

export default function ManualTradePanel() {
  const [ticker, setTicker] = useState("");
  const [action, setAction] = useState<Action>("BUY");
  const [shares, setShares] = useState(10);
  const [orderType, setOrderType] = useState<OrderType>("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ManualTradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const tickerClean = ticker.trim().toUpperCase();
  const limitPriceN = parseFloat(limitPrice);
  const overSized = shares > MAX_SHARES;
  const canSubmit =
    !busy &&
    tickerClean.length > 0 &&
    shares >= 1 &&
    !overSized &&
    (orderType === "market" || Number.isFinite(limitPriceN));

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/trade-desk/manual-trade", {
        method: "POST",
        headers: apiAuthHeaders(),
        body: JSON.stringify({
          ticker: tickerClean,
          action,
          shares,
          order_type: orderType,
          limit_price: orderType === "limit" ? limitPriceN : null,
        }),
      });
      const body = await res.json();
      if (!res.ok) {
        // manual_trade()'s one result:"error" path raises HTTPException(500,
        // detail=...) — detail is the only useful signal for that failure,
        // so parse it rather than a generic "API error 500" string.
        throw new Error(body?.detail || `Order failed (${res.status})`);
      }
      setResult(body as ManualTradeResult);
    } catch (e: any) {
      setError(e?.message || "Order failed");
    } finally {
      setBusy(false);
    }
  };

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

  const lifecycle = result ? lifecycleFromExecution(result) : null;

  return (
    <div style={{ padding: 16, maxWidth: 560, display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="instrument-card" style={{
        padding: "10px 14px",
        border: "1px solid var(--amber)30", borderLeft: "2px solid var(--amber)",
        fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.7,
      }}>
        Bypasses signal scoring and IV filters — still subject to kill switch,
        market hours, and all risk guardrails. This places a real order
        immediately, it does not queue for approval.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: 10 }}>
        {field(
          "TICKER",
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            style={inputStyle}
          />,
        )}
        {field(
          "SIDE",
          <select value={action} onChange={(e) => setAction(e.target.value as Action)} style={inputStyle}>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>,
        )}
        {field(
          "SHARES",
          <input
            type="number"
            min={1}
            value={shares}
            onChange={(e) => setShares(Math.max(1, Number(e.target.value) || 1))}
            style={overSized ? { ...inputStyle, border: "1px solid var(--red)" } : inputStyle}
          />,
        )}
        {field(
          "ORDER TYPE",
          <select value={orderType} onChange={(e) => setOrderType(e.target.value as OrderType)} style={inputStyle}>
            <option value="market">MARKET</option>
            <option value="limit">LIMIT</option>
          </select>,
        )}
        {orderType === "limit" &&
          field(
            "LIMIT PRICE",
            <input value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)} style={inputStyle} />,
          )}
      </div>

      {overSized && (
        <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--red)" }}>
          {shares.toLocaleString()} shares exceeds the {MAX_SHARES.toLocaleString()}-share sanity limit for this panel.
        </div>
      )}

      {/* Review echo — built from the same state as the request body, so it
          cannot drift from what's actually submitted. */}
      <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
        About to submit:{" "}
        <b style={{ color: "var(--ink)" }}>
          {action} {shares.toLocaleString()} {tickerClean || "—"} @{" "}
          {orderType === "market" ? "MARKET" : Number.isFinite(limitPriceN) ? `$${limitPriceN.toFixed(2)} LIMIT` : "—"}
        </b>
      </div>

      <HoldToConfirmButton
        label="HOLD TO SUBMIT ORDER"
        confirmingLabel="SUBMITTING"
        holdMs={1200}
        disabled={!canSubmit || busy}
        onConfirm={submit}
      />

      {error && (
        <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>{error}</div>
      )}

      {result && lifecycle && (
        <div className="instrument-card" style={{
          padding: "10px 12px",
          border: `1px solid ${lifecycleColor(lifecycle)}40`, borderLeft: `2px solid ${lifecycleColor(lifecycle)}`,
          fontFamily: "var(--mono)", fontSize: 11,
        }}>
          <div style={{ color: lifecycleColor(lifecycle), fontWeight: 600, marginBottom: 4 }}>
            {lifecycleLabel(lifecycle)}
          </div>
          {(lifecycle === "blocked" || lifecycle === "skipped") && result.reason && (
            <div style={{ color: "var(--ink-dim)" }}>
              Blocked by risk guardrails: {result.reason}
            </div>
          )}
          {lifecycle === "submitted" && (
            <div style={{ color: "var(--ink-dim)" }}>
              {result.ticker} — order {result.order_id} ({result.order_status})
              {result.entry_price != null ? ` @ $${result.entry_price}` : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
