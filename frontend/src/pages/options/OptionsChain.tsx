/**
 * Options Chain — live calls/puts for a symbol from the connected broker
 * (/api/market/options-chain/{symbol}). Requires a broker connection (IBKR);
 * shows the underlying error if the gateway is down.
 */
import React, { useEffect, useState } from "react";
import { Button } from "../../components/ui";

interface Contract {
  strike: number; bid: number; ask: number; last: number;
  volume: number; open_interest: number; delta: number | null; iv: number | null;
}
interface ChainResponse {
  symbol: string; expiry: string; underlying_price?: number;
  calls?: Contract[]; puts?: Contract[]; error?: string;
}

function ContractRow({ c, atm }: { c: Contract; atm: boolean }) {
  return (
    <tr style={atm ? { background: "var(--bg-3)" } : undefined}>
      <td className="mono" style={{ fontWeight: atm ? 600 : 400 }}>{c.strike}</td>
      <td className="mono">{c.bid.toFixed(2)}</td>
      <td className="mono">{c.ask.toFixed(2)}</td>
      <td className="mono">{c.last.toFixed(2)}</td>
      <td className="mono" style={{ color: "var(--ink-dim)" }}>{c.volume.toLocaleString("en-US")}</td>
      <td className="mono" style={{ color: "var(--ink-dim)" }}>{c.open_interest.toLocaleString("en-US")}</td>
      <td className="mono" style={{ color: "var(--cyan)" }}>{c.delta != null ? c.delta.toFixed(2) : "—"}</td>
      <td className="mono" style={{ color: "var(--ink-dim)" }}>{c.iv != null ? `${(c.iv * 100).toFixed(0)}%` : "—"}</td>
    </tr>
  );
}

export default function OptionsChain({
  symbol: controlledSymbol,
  onSymbolChange,
}: {
  symbol?: string;
  onSymbolChange?: (symbol: string) => void;
} = {}) {
  const [internalSymbol, setInternalSymbol] = useState(controlledSymbol || "SPY");
  const symbol = controlledSymbol ?? internalSymbol;
  const setSymbol = (sym: string) => {
    if (controlledSymbol === undefined) setInternalSymbol(sym);
    onSymbolChange?.(sym);
  };
  const [input, setInput] = useState(symbol);
  const [data, setData] = useState<ChainResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setInput(symbol);
  }, [symbol]);

  const load = (sym: string) => {
    setLoading(true);
    fetch(`/api/market/options-chain/${encodeURIComponent(sym)}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData({ symbol: sym, expiry: "", error: "unreachable" }))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(symbol); }, [symbol]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const sym = input.trim().toUpperCase();
    if (sym) setSymbol(sym);
  };

  const spot = data?.underlying_price ?? null;
  const nearestStrike = (rows: Contract[] | undefined) =>
    !rows || spot == null ? null
      : rows.reduce((a, b) => Math.abs(b.strike - spot) < Math.abs(a.strike - spot) ? b : a).strike;
  const atmCallStrike = nearestStrike(data?.calls);
  const atmPutStrike  = nearestStrike(data?.puts);

  const cols = ["Strike", "Bid", "Ask", "Last", "Vol", "OI", "Delta", "IV"];

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">Options Chain</span>
        <form onSubmit={submit} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Symbol"
            style={{
              width: 90, fontFamily: "var(--mono)", fontSize: 12, textTransform: "uppercase",
              background: "var(--bg-2)", border: "1px solid var(--line-dim)", color: "var(--ink)",
              padding: "4px 8px",
            }}
          />
          <Button type="submit" style={{ padding: "4px 10px", fontSize: 10 }}>Load</Button>
        </form>
        {spot != null && (
          <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cyan)" }}>
            {data?.symbol} spot {spot.toFixed(2)}
          </span>
        )}
        {data?.expiry && (
          <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
            exp {data.expiry}
          </span>
        )}
      </div>

      {loading ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-faint)", padding: 24 }}>
          Loading chain…
        </div>
      ) : data?.error ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--red)", padding: 24 }}>
          ⚠ {data.error} — check the broker connection in Data & Integrations → Broker Gateway.
        </div>
      ) : (
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 340 }}>
            <div style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: "var(--green)", marginBottom: 6 }}>CALLS</div>
            <table className="t-table">
              <thead><tr>{cols.map(h => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>
                {(data?.calls ?? []).map(c => <ContractRow key={c.strike} c={c} atm={c.strike === atmCallStrike} />)}
              </tbody>
            </table>
          </div>
          <div style={{ flex: 1, minWidth: 340 }}>
            <div style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: "var(--red)", marginBottom: 6 }}>PUTS</div>
            <table className="t-table">
              <thead><tr>{cols.map(h => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>
                {(data?.puts ?? []).map(p => <ContractRow key={p.strike} c={p} atm={p.strike === atmPutStrike} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
