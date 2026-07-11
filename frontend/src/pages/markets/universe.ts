/**
 * Shared market universe for the Markets module (Heatmaps, Watchlists).
 * Grouped so views can render sectioned tables/grids without extra config.
 */
export type Snap = { last_close: number | null; prev_close: number | null; change_pct: number | null };

export interface UniverseGroup {
  label: string;
  symbols: { sym: string; name: string; api?: string }[];
}

export const UNIVERSE: UniverseGroup[] = [
  {
    label: "Index & Broad",
    symbols: [
      { sym: "SPY", name: "S&P 500" },
      { sym: "QQQ", name: "Nasdaq 100" },
      { sym: "IWM", name: "Russell 2000" },
      { sym: "DIA", name: "Dow 30" },
    ],
  },
  {
    label: "Mega-cap Tech",
    symbols: [
      { sym: "NVDA", name: "NVIDIA" },
      { sym: "AAPL", name: "Apple" },
      { sym: "MSFT", name: "Microsoft" },
      { sym: "AMZN", name: "Amazon" },
      { sym: "META", name: "Meta" },
      { sym: "GOOGL", name: "Alphabet" },
      { sym: "TSLA", name: "Tesla" },
    ],
  },
  {
    label: "Rates, Metals & Energy",
    symbols: [
      { sym: "TLT", name: "20Y Treasuries" },
      { sym: "GLD", name: "Gold" },
      { sym: "SLV", name: "Silver" },
      { sym: "USO", name: "Crude Oil" },
    ],
  },
  {
    label: "Volatility & Dollar",
    symbols: [
      { sym: "DXY", name: "Dollar Index", api: "DX-Y.NYB" },
    ],
  },
];

/** Fetch one snapshot; resolves to a Snap (nulls on failure). */
export function fetchSnap(apiSym: string): Promise<Snap> {
  return fetch(`/api/market/snapshot/${apiSym}`)
    .then(r => r.json())
    .then(d => ({ last_close: d.last_close, prev_close: d.prev_close, change_pct: d.change_pct }))
    .catch(() => ({ last_close: null, prev_close: null, change_pct: null }));
}

/** Color for a % change, mapped onto the terminal palette. */
export function changeColor(pct: number | null): string {
  if (pct === null) return "var(--ink-faint)";
  if (pct >= 1.5) return "var(--green)";
  if (pct > 0) return "var(--green-dim, var(--green))";
  if (pct <= -1.5) return "var(--red)";
  if (pct < 0) return "var(--red-dim, var(--red))";
  return "var(--ink-dim)";
}
