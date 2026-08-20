/**
 * 0DTE Decision Desk — read-only / Copilot evidence. Autopilot explicitly off.
 */

import React, { useEffect, useState } from "react";
import { api } from "../../api/client";

export default function ZeroDteDesk({ symbol }: { symbol: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);
    // Short-dated flow recommendations — evidence only.
    api
      .getOptionsFlow({ ticker: symbol, limit: 40 })
      .then((d) => setRows(d.results || []))
      .catch((e: any) => {
        setRows([]);
        setError(e?.message || "Flow unavailable");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [symbol]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, overflow: "auto", height: "100%" }}>
      <div>
        <h2 style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 14, letterSpacing: "0.08em", color: "var(--ink)" }}>
          0DTE DECISION DESK
        </h2>
        <p style={{ margin: "6px 0 0", fontFamily: "var(--mono)", fontSize: 11, color: "var(--amber)", lineHeight: 1.5 }}>
          Read-only evidence for {symbol}. Autopilot for 0DTE remains disabled.
          No order submission from this panel.
        </p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: 8,
        }}
      >
        {[
          { label: "Autopilot", value: "DISABLED", tone: "var(--red)" },
          { label: "Mode", value: "Read-only / Copilot", tone: "var(--cyan)" },
          { label: "Underlying", value: symbol, tone: "var(--ink)" },
          { label: "Data", value: "Options flow tape", tone: "var(--ink-dim)" },
        ].map((c) => (
          <div key={c.label} className="instrument-card" style={{ padding: "10px 12px" }}>
            <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)", letterSpacing: "0.08em" }}>
              {c.label.toUpperCase()}
            </div>
            <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: c.tone, marginTop: 4 }}>{c.value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
          Recent flow (not institutional intent)
        </span>
        <button type="button" className="btn-t" style={{ fontSize: 10 }} onClick={load} disabled={loading}>
          {loading ? "…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>{error}</div>
      )}

      {rows.length === 0 && !loading ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
          No flow rows for {symbol}. Enable options flow data or pick another underlying.
        </div>
      ) : (
        <div style={{ border: "1px solid var(--line-dim)", overflow: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--mono)", fontSize: 11 }}>
            <thead>
              <tr style={{ background: "var(--bg-3)", color: "var(--ink-dim)", textAlign: "left" }}>
                {["Contract", "Side", "Premium", "Vol", "OI", "DTE"].map((h) => (
                  <th key={h} style={{ padding: "8px 10px", borderBottom: "1px solid var(--line-dim)", fontWeight: 500 }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 25).map((r, i) => (
                <tr key={i} style={{ borderBottom: "1px solid var(--line-dim)" }}>
                  <td style={{ padding: "6px 10px", color: "var(--ink)" }}>
                    {r.contract || r.symbol || r.ticker || "—"}
                  </td>
                  <td style={{ padding: "6px 10px", color: "var(--ink-dim)" }}>
                    {r.side || r.option_type || r.call_put || "—"}
                  </td>
                  <td style={{ padding: "6px 10px", color: "var(--ink)" }}>
                    {r.premium != null ? `$${Number(r.premium).toFixed(0)}` : "—"}
                  </td>
                  <td style={{ padding: "6px 10px", color: "var(--ink-dim)" }}>{r.volume ?? "—"}</td>
                  <td style={{ padding: "6px 10px", color: "var(--ink-dim)" }}>{r.open_interest ?? r.oi ?? "—"}</td>
                  <td style={{ padding: "6px 10px", color: "var(--cyan)" }}>{r.dte ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
