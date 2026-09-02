import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";

export function usePaperTrade() {
  const [positions, setPositions]   = useState<any[]>([]);
  const [portfolio, setPortfolio]   = useState<any>(null);
  const [greeks, setGreeks]         = useState<any>(null);
  const [lastSignal, setLastSignal] = useState<any>(null);
  const [cycleLog, setCycleLog]     = useState<any[]>([]);
  const [loading, setLoading]       = useState(false);
  // Distinguishes "portfolio is genuinely unfetched/failed" from "not yet
  // loaded" — a fetch failure must never be indistinguishable from a
  // legitimate absence of data, so callers can show an explicit
  // unavailable state instead of a stale or fabricated value.
  const [portfolioError, setPortfolioError] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [p, port, g, hist] = await Promise.all([
        api.getPositions() as any,
        api.getPortfolio() as any,
        api.getGreeksSummary() as any,
        api.getTradeHistory() as any,
      ]);
      setPositions(p.positions ?? []);
      setPortfolio(port.portfolio ?? null);
      setPortfolioError(false);
      setGreeks(g);
      const trades: any[] = hist.trades ?? [];
      setCycleLog(trades);
      if (trades.length > 0) setLastSignal(trades[0]);
    } catch {
      // Keep the last-known portfolio value (avoids flicker on a transient
      // blip) but flag that the most recent attempt failed, so a caller
      // with no last-known value at all can render "unavailable" instead
      // of falling through to a fabricated default.
      setPortfolioError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const runCycle = useCallback(async () => {
    setLoading(true);
    try {
      // Trigger a manual signal cycle via the paper-trade toggle endpoint
      await (api as any).runSignalCycle?.();
      await refresh();
    } catch {
      await refresh();
    }
  }, [refresh]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30000); // re-poll every 30s
    return () => clearInterval(interval);
  }, [refresh]);

  return { positions, portfolio, portfolioError, greeks, lastSignal, cycleLog, loading, refresh, runCycle };
}
