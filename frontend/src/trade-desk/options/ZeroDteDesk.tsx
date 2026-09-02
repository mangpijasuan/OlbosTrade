/**
 * 0DTE Decision Desk — read-only / Copilot evidence. Autopilot explicitly off.
 */

import React, { useEffect, useState } from "react";
import { api } from "../../api/client";
import { StatTile } from "../../components/ui";

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
      <div className="instrument-card page-header">
        <div>
          <div className="page-header__title">0DTE Decision Desk</div>
          <p className="page-header__sub" style={{ color: "var(--amber)" }}>
            Read-only evidence for {symbol}. Autopilot for 0DTE remains disabled — no order submission from this panel.
          </p>
        </div>
        <button type="button" className="btn-ghost" onClick={load} disabled={loading}>
          {loading ? "…" : "Refresh"}
        </button>
      </div>

      <div className="instrument-stat-strip" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
        <StatTile variant="divider" size="sm" label="Autopilot" value="Disabled" tone="var(--red)" />
        <StatTile variant="divider" size="sm" label="Mode" value="Read-only" tone="var(--accent)" />
        <StatTile variant="divider" size="sm" label="Underlying" value={symbol} />
        <StatTile variant="divider" size="sm" label="Data" value="Flow tape" />
      </div>

      {error && (
        <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>{error}</div>
      )}

      {rows.length === 0 && !loading ? (
        <div className="instrument-card instrument-card--flat empty-chassis empty-chassis--compact">
          <p className="empty-chassis__title">No flow rows for {symbol}</p>
          <p className="empty-chassis__hint">Enable options flow data or pick another underlying.</p>
        </div>
      ) : (
        <div className="instrument-card" style={{ overflow: "auto" }}>
          <table className="t-table">
            <thead>
              <tr>
                {["Contract", "Side", "Premium", "Vol", "OI", "DTE"].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 25).map((r, i) => (
                <tr key={i}>
                  <td className="mono" style={{ color: "var(--ink)" }}>
                    {r.contract || r.symbol || r.ticker || "—"}
                  </td>
                  <td className="mono" style={{ color: "var(--ink-dim)" }}>
                    {r.side || r.option_type || r.call_put || "—"}
                  </td>
                  <td className="tnum" style={{ color: "var(--ink)" }}>
                    {r.premium != null ? `$${Number(r.premium).toFixed(0)}` : "—"}
                  </td>
                  <td className="tnum" style={{ color: "var(--ink-dim)" }}>{r.volume ?? "—"}</td>
                  <td className="tnum" style={{ color: "var(--ink-dim)" }}>{r.open_interest ?? r.oi ?? "—"}</td>
                  <td className="tnum" style={{ color: "var(--accent)" }}>{r.dte ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
