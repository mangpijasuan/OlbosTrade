/**
 * Build deduplicated Alpha Edge watchlists from open positions + live scans.
 */

export type AlphaEdgeSource = "held" | "scan";

export interface AlphaEdgeCandidate {
  ticker: string;
  source: AlphaEdgeSource;
  /** Scan confidence 0..1 when from a signal row */
  scanConfidence?: number;
  scanAction?: string;
  generatedAt?: string;
}

export interface PositionRow {
  symbol?: string;
  underlying?: string;
  asset_type?: string;
  spread_type?: string;
  tracked?: boolean;
}

export interface EquitySignalRow {
  ticker: string;
  action: string;
  confidence: number;
  generated_at: string;
  earnings_gated?: boolean;
}

export interface OptionsSignalRow {
  ticker: string;
  action: string;
  confidence?: number;
  signal_score?: number;
  generated_at: string;
}

const CYCLE_BUCKET_MS = 10 * 60 * 1000;

function cycleBucket(generatedAt: string): number {
  return Math.floor(new Date(generatedAt).getTime() / CYCLE_BUCKET_MS);
}

export function positionTicker(p: PositionRow): string {
  return (p.symbol || p.underlying || "").trim().toUpperCase();
}

function isEquityPosition(p: PositionRow): boolean {
  if (p.asset_type === "equity") return true;
  if (p.asset_type === "options") return false;
  const st = (p.spread_type || "").toLowerCase();
  return st.startsWith("equity");
}

function signalConfidence(sig: { confidence?: number; signal_score?: number }): number {
  if (typeof sig.confidence === "number") return sig.confidence;
  if (typeof sig.signal_score === "number") return sig.signal_score;
  return 0;
}

/** Positions first, then scan candidates; dedupe by ticker (held wins). */
export function buildAlphaEdgeCandidates(
  positions: PositionRow[],
  signals: EquitySignalRow[] | OptionsSignalRow[],
  assetType: "equity" | "options",
  opts?: { maxScan?: number },
): AlphaEdgeCandidate[] {
  const maxScan = opts?.maxScan ?? 20;
  const byTicker = new Map<string, AlphaEdgeCandidate>();

  for (const p of positions) {
    const ticker = positionTicker(p);
    if (!ticker) continue;
    const equity = isEquityPosition(p);
    if (assetType === "equity" && !equity) continue;
    if (assetType === "options" && equity) continue;
    byTicker.set(ticker, { ticker, source: "held" });
  }

  const actionable =
    assetType === "equity"
      ? (signals as EquitySignalRow[]).filter(
          s =>
            (s.action === "BUY" || s.action === "SELL") &&
            !s.earnings_gated,
        )
      : (signals as OptionsSignalRow[]).filter(
          s => s.action === "BUY_SPREAD" || s.action === "SELL_SPREAD",
        );

  const latestCycle = actionable.reduce(
    (max, s) => Math.max(max, cycleBucket(s.generated_at)),
    0,
  );

  const recent = actionable
    .filter(s => cycleBucket(s.generated_at) >= latestCycle - 1)
    .sort((a, b) => {
      const cycleDiff = cycleBucket(b.generated_at) - cycleBucket(a.generated_at);
      if (cycleDiff !== 0) return cycleDiff;
      return signalConfidence(b) - signalConfidence(a);
    });

  let scanCount = 0;
  for (const sig of recent) {
    const ticker = sig.ticker.trim().toUpperCase();
    if (!ticker || byTicker.has(ticker)) continue;
    if (scanCount >= maxScan) break;
    byTicker.set(ticker, {
      ticker,
      source: "scan",
      scanConfidence: signalConfidence(sig),
      scanAction: sig.action,
      generatedAt: sig.generated_at,
    });
    scanCount += 1;
  }

  const held = [...byTicker.values()].filter(c => c.source === "held");
  const scan = [...byTicker.values()].filter(c => c.source === "scan");
  return [...held, ...scan];
}
